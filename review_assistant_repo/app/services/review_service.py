from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.analyzers.rules import RuleEngine
from app.config import get_settings
from app.exporters.notebook import NotebookCommentInserter
from app.llm.service import get_llm_service
from app.models import Artifact, CriterionResult, Project, ProjectFile, ProjectLineage
from app.parsers.datalens import DataLensParser
from app.parsers.html import HTMLParser
from app.parsers.notebook import NotebookParser
from app.parsers.pdf import PDFParser
from app.parsers.sql import SQLParser
from app.retrieval.local_examples import get_retrieval_backend
from app.services.capture_summary import build_capture_summary
from app.services.comment_dedup import dedupe_notebook_insertions
from app.services.criteria_summary import build_criteria_execution_summary_from_merged
from app.services.finding_policy import (
    apply_low_confidence_and_quality_policy,
    build_manual_review_summary,
    coerce_source_stage_metadata,
)
from app.services.iteration_fix_service import (
    compute_iteration_fixes,
    get_parent_project_id_for_child,
)
from app.services.iteration_metadata_quality import (
    normalize_iteration_fix_summary,
    normalize_notebook_execution,
)
from app.services.notebook_execution import NotebookExecutionResult, execute_notebook_to_file
from app.services.parser_summary import build_parser_summary
from app.services.review_builder import build_iteration_fix_markdown_section, build_review_markdown
from app.services.review_metrics import review_metrics
from app.services.review_snapshot import persist_review_snapshot
from app.services.verdict import build_verdict
from app.storage.supabase_storage import supabase_storage_configured, upload_path
from app.utils.config_loader import (
    list_criteria_maps,
    list_style_profiles,
    load_criteria_map,
    load_style_profile,
)
from app.utils.logging_json import log_event
from app.utils.notebook_html import build_notebook_comment_html
from app.utils.practicum_input import normalize_practicum_input_channel

logger = logging.getLogger(__name__)


def _notebook_exec_metadata_for_iteration(
    settings,
    exec_result: NotebookExecutionResult | None,
) -> dict[str, Any]:
    """Metadata for iteration-fix policy and API (notebook runtime)."""
    if not settings.enable_notebook_execution:
        return {"notebook_execution_disabled": True}
    if exec_result is None:
        return {"notebook_execution_disabled": True}
    meta: dict[str, Any] = dict(exec_result.to_metadata())
    sr = (exec_result.skip_reason or "").lower()
    meta["notebook_execution_import_unavailable"] = bool(exec_result.skipped and "import" in sr)
    return meta


class ReviewPipelineError(Exception):
    """Raised when review fails after status was set to processing; DB row is marked failed."""


class ReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.rule_engine = RuleEngine()
        self.notebook_parser = NotebookParser()
        self.sql_parser = SQLParser()
        self.pdf_parser = PDFParser()
        self.html_parser = HTMLParser()
        self.datalens_parser = DataLensParser()

    def upload_project(
        self,
        source_type: str,
        style_profile_code: str,
        criteria_map_code: str,
        original_filename: str | None = None,
        source_url: str | None = None,
        uploaded_file_path: str | None = None,
        review_training_project: str | None = None,
        practicum_input_channel: str | None = None,
        previous_project_id: str | None = None,
    ) -> Project:
        if criteria_map_code not in list_criteria_maps():
            raise ValueError(f"Unknown criteria map: {criteria_map_code!r}")
        if style_profile_code not in list_style_profiles():
            raise ValueError(f"Unknown style profile: {style_profile_code!r}")
        settings = get_settings()
        meta: dict = {}
        if review_training_project and str(review_training_project).strip():
            meta["review_training_project"] = str(review_training_project).strip()
        ch, ch_flags = normalize_practicum_input_channel(practicum_input_channel, source_type=source_type)
        meta["practicum_input_channel"] = ch
        meta["practicum_input_explicit"] = ch_flags["explicit"]
        project = Project(
            id=str(uuid.uuid4()),
            source_type=source_type,
            original_filename=original_filename,
            source_url=source_url,
            status="uploaded",
            style_profile_code=style_profile_code,
            criteria_map_code=criteria_map_code,
            metadata_json=meta,
        )
        self.db.add(project)
        self.db.flush()

        if previous_project_id:
            if previous_project_id == project.id:
                raise ValueError("previous_project_id cannot equal the new project id")
            prev = self.db.get(Project, previous_project_id)
            if not prev:
                raise ValueError("Previous project not found")
            if prev.source_type != source_type:
                raise ValueError("Previous project source_type does not match upload")
            prev_lineage = self.db.get(ProjectLineage, prev.id)
            parent_iter = prev_lineage.iteration_no if prev_lineage else 1
            self.db.add(
                ProjectLineage(
                    project_id=project.id,
                    parent_project_id=prev.id,
                    iteration_no=int(parent_iter) + 1,
                )
            )
            meta["previous_project_id"] = previous_project_id
        else:
            self.db.add(
                ProjectLineage(
                    project_id=project.id,
                    parent_project_id=None,
                    iteration_no=1,
                )
            )

        if uploaded_file_path:
            project_dir = Path(settings.files_root) / project.id
            project_dir.mkdir(parents=True, exist_ok=True)
            destination = project_dir / (original_filename or Path(uploaded_file_path).name)
            shutil.copy(uploaded_file_path, destination)
            if supabase_storage_configured():
                try:
                    upload_path(
                        destination,
                        object_name=f"{project.id}/{destination.name}",
                    )
                    meta.setdefault("supabase_storage_object", f"{project.id}/{destination.name}")
                except Exception as exc:
                    meta.setdefault("supabase_upload_error", str(exc))
            file_row = ProjectFile(
                id=str(uuid.uuid4()),
                project_id=project.id,
                kind="original",
                storage_path=str(destination),
                mime_type=destination.suffix,
                metadata_json={},
            )
            self.db.add(file_row)

        self.db.commit()
        self.db.refresh(project)
        return project

    def run_review(self, project_id: str) -> Project:
        project = self.db.get(Project, project_id)
        if not project:
            raise ValueError("Project not found")

        settings = get_settings()
        review_metrics.record_start()
        t_rev = time.perf_counter()
        if settings.review_structured_logs:
            log_event(logger, logging.INFO, "review_start", project_id=project_id)

        project.status = "processing"
        self.db.query(Artifact).filter(Artifact.project_id == project.id).delete()
        self.db.query(CriterionResult).filter(CriterionResult.project_id == project.id).delete()
        self.db.query(ProjectFile).filter(
            ProjectFile.project_id == project.id,
            ProjectFile.kind.in_(
                [
                    "reviewed",
                    "pdf_page_image",
                    "pdf_page_overlay",
                    "capture_screenshot",
                    "capture_overlay",
                    "notebook_executed",
                ]
            ),
        ).delete(synchronize_session=False)
        self.db.commit()
        self.db.refresh(project)

        try:
            project = self._run_review_pipeline(project_id, project)
            dur_ms = (time.perf_counter() - t_rev) * 1000
            summ = (project.metadata_json or {}).get("criteria_execution_summary") or {}
            lc = int(summ.get("low_confidence_findings_approx") or 0)
            review_metrics.record_finish(True, dur_ms, low_confidence_findings=lc)
            if settings.review_structured_logs:
                log_event(
                    logger,
                    logging.INFO,
                    "review_done",
                    project_id=project_id,
                    duration_ms=round(dur_ms, 2),
                    low_confidence_findings=lc,
                    final_verdict=project.final_verdict,
                )
        except Exception as exc:
            dur_ms = (time.perf_counter() - t_rev) * 1000
            review_metrics.record_finish(False, dur_ms, error=str(exc))
            if settings.review_structured_logs:
                log_event(
                    logger,
                    logging.WARNING,
                    "review_failed",
                    project_id=project_id,
                    duration_ms=round(dur_ms, 2),
                    error=str(exc)[:500],
                )
            self.db.rollback()
            failed = self.db.get(Project, project_id)
            if failed is not None:
                failed.status = "failed"
                meta = dict(failed.metadata_json or {})
                meta["error"] = str(exc)
                failed.metadata_json = meta
                self.db.commit()
            raise ReviewPipelineError(str(exc)) from exc

        self.db.refresh(project)
        return project

    def _run_review_pipeline(self, project_id: str, project: Project) -> Project:
        criteria = load_criteria_map(project.criteria_map_code)
        style_profile = load_style_profile(project.style_profile_code)

        settings_pipe = get_settings()
        deadline = None
        if settings_pipe.review_pipeline_timeout_sec and settings_pipe.review_pipeline_timeout_sec > 0:
            deadline = time.perf_counter() + float(settings_pipe.review_pipeline_timeout_sec)

        def _deadline_check() -> None:
            if deadline is not None and time.perf_counter() > deadline:
                raise ReviewPipelineError("review_pipeline_timeout")

        pipeline_started = time.perf_counter()

        original_file = next((f for f in project.files if f.kind == "original"), None)
        notebook_obj = None
        parse_meta: dict[str, Any] = {}
        notebook_exec_meta: dict[str, Any] = {}

        if project.source_type == "ipynb":
            if not original_file:
                raise ValueError("Notebook file not found")
            settings_nb = get_settings()
            orig_path = str(original_file.storage_path)
            parse_path = orig_path
            if settings_nb.enable_notebook_execution:
                project_dir = Path(settings_nb.files_root) / project.id
                project_dir.mkdir(parents=True, exist_ok=True)
                executed_path = project_dir / "executed.ipynb"
                exec_result = execute_notebook_to_file(
                    orig_path,
                    str(executed_path),
                    cwd=project_dir,
                    timeout_sec=float(settings_nb.notebook_execution_timeout_sec),
                )
                notebook_exec_meta = _notebook_exec_metadata_for_iteration(settings_nb, exec_result)
                if exec_result.ok and exec_result.output_path:
                    parse_path = str(exec_result.output_path)
                    self.db.add(
                        ProjectFile(
                            id=str(uuid.uuid4()),
                            project_id=project.id,
                            kind="notebook_executed",
                            storage_path=str(exec_result.output_path),
                            mime_type=".ipynb",
                            metadata_json={},
                        )
                    )
                    self.db.flush()
            else:
                notebook_exec_meta = _notebook_exec_metadata_for_iteration(settings_nb, None)

            parsed_artifacts, notebook_obj = self.notebook_parser.parse(parse_path)
            notebook_obj = self.notebook_parser.clean_notebook(notebook_obj)
        elif project.source_type == "sql":
            if not original_file:
                raise ValueError("SQL file not found")
            parsed_artifacts, parse_meta = self.sql_parser.parse(original_file.storage_path)
        elif project.source_type == "pdf":
            if not original_file:
                raise ValueError("PDF file not found")
            settings = get_settings()
            analysis_dir = str(Path(settings.files_root) / project.id / "analysis")
            parsed_artifacts, parse_meta = self.pdf_parser.parse(original_file.storage_path, output_dir=analysis_dir)
        elif project.source_type == "html":
            if not original_file:
                raise ValueError("HTML file not found")
            parsed_artifacts, parse_meta = self.html_parser.parse(original_file.storage_path)
        elif project.source_type == "datalens":
            settings = get_settings()
            capture_dir = str(Path(settings.files_root) / project.id / "captures")
            parsed_artifacts, parse_meta = self.datalens_parser.parse(project.source_url or "", capture_dir=capture_dir)
        else:
            raise ValueError(f"Unsupported source type: {project.source_type}")

        artifact_dicts: list[dict[str, Any]] = []
        position_to_db_id: dict[int, str] = {}

        for item in parsed_artifacts:
            row = Artifact(
                id=str(uuid.uuid4()),
                project_id=project.id,
                artifact_type=item.artifact_type,
                position_idx=item.position_idx,
                section_name=item.section_name,
                raw_text=item.raw_text,
                normalized_text=item.normalized_text,
                metadata_json=item.metadata,
            )
            self.db.add(row)
            self.db.flush()
            artifact_dict = {
                "id": row.id,
                "artifact_type": row.artifact_type,
                "position_idx": row.position_idx,
                "section_name": row.section_name,
                "raw_text": row.raw_text,
                "normalized_text": row.normalized_text,
                "metadata_json": row.metadata_json,
            }
            artifact_dicts.append(artifact_dict)
            if row.position_idx is not None:
                position_to_db_id[row.position_idx] = row.id

        for generated_file in parse_meta.get("generated_files", []) if isinstance(parse_meta, dict) else []:
            self.db.add(
                ProjectFile(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    kind=generated_file["kind"],
                    storage_path=generated_file["storage_path"],
                    mime_type=generated_file.get("mime_type"),
                    page_no=generated_file.get("page_no"),
                    metadata_json=generated_file.get("metadata_json", {}),
                )
            )

        screenshot_paths = parse_meta.get("screenshot_paths", []) if isinstance(parse_meta, dict) else []
        for index, screenshot_path in enumerate(screenshot_paths):
            self.db.add(
                ProjectFile(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    kind="capture_screenshot",
                    storage_path=screenshot_path,
                    mime_type="image/png",
                    page_no=index,
                    metadata_json={"source": "datalens_capture", "screenshot_index": index},
                )
            )

        _deadline_check()
        t_after_parse = time.perf_counter()
        timeline: list[dict[str, Any]] = [
            {"stage": "parse_and_persist", "duration_ms": round((t_after_parse - pipeline_started) * 1000, 2)},
        ]

        t_rules = time.perf_counter()
        raw_results = self.rule_engine.run(artifact_dicts, criteria)
        timeline.append({"stage": "rule_engine", "duration_ms": round((time.perf_counter() - t_rules) * 1000, 2)})
        _deadline_check()

        llm_service = get_llm_service()
        retrieval = get_retrieval_backend()

        positives = []
        required_fixes = []
        extra_recommendations = []
        notebook_insertions = []
        seen_criteria = set()

        training_slug = ((project.metadata_json or {}).get("review_training_project") or "").strip() or None

        merged_results = []
        t_crit = time.perf_counter()
        for criterion, result in zip(criteria, raw_results, strict=True):
            status = result["status"]
            severity = criterion["severity"]
            criterion_code = criterion["code"]
            if criterion_code in seen_criteria:
                continue
            seen_criteria.add(criterion_code)

            comment_templates = criterion.get("comment_templates", {})
            generated_comment = None
            fail_text = ""

            if status == "pass":
                pass
            else:
                fail_text = comment_templates.get("fail", criterion.get("description") or criterion.get("title") or criterion["code"])
                generated_comment = fail_text
                settings = get_settings()
                if settings.enable_llm_comment_generation and llm_service.is_available:
                    section_hint: str | None = None
                    if project.source_type == "ipynb":
                        anchor = result.get("anchor_position_idx")
                        if anchor is not None:
                            for a in artifact_dicts:
                                if a.get("position_idx") == anchor:
                                    sn = a.get("section_name")
                                    if sn:
                                        section_hint = str(sn)
                                    break
                    examples = retrieval.retrieve(
                        query=fail_text,
                        criterion_code=criterion_code,
                        limit=3,
                        filter_source_project=training_slug,
                        filter_section_name=section_hint,
                    )
                    improved = llm_service.generate_comment(
                        {
                            "title": criterion.get("title", ""),
                            "description": criterion.get("description", ""),
                            "template": fail_text,
                            "evidence": result.get("evidence", []),
                            "retrieval_examples": [
                                {
                                    "text": e.text,
                                    "tags": e.tags,
                                    "from_reviewer_reference": e.from_reviewer_reference,
                                    "source_kind": e.source_kind,
                                    "author_role": e.author_role,
                                    "source_project": e.source_project,
                                    "source_notebook": e.source_notebook,
                                    "section_name": e.section_name,
                                    "student_context": (e.student_context[:800] if e.student_context else ""),
                                }
                                for e in examples
                            ],
                        }
                    )
                    if improved:
                        generated_comment = improved
                        fail_text = improved

            result_meta = dict(result.get("metadata") or {})
            if "source_stage" not in result_meta:
                mode = criterion.get("detection_mode", "rule")
                result_meta["source_stage"] = {"rule": "rule", "hybrid": "semantic", "visual": "visual"}.get(mode, str(mode))
            if result_meta.get("llm_used"):
                result_meta["source_stage"] = "llm"
                result_meta["llm_semantic"] = True
            result_meta.setdefault("criterion_code", criterion_code)
            cat = criterion.get("category")
            if cat is not None:
                result_meta["category"] = cat

            det_mode = criterion.get("detection_mode")
            result_meta = coerce_source_stage_metadata(result_meta, det_mode if isinstance(det_mode, str) else None)

            settings = get_settings()
            outcome = apply_low_confidence_and_quality_policy(
                status=status,
                severity=severity,
                confidence=result.get("confidence"),
                metadata=result_meta,
                criterion_code=criterion_code,
                min_confidence_for_required_fail=settings.finding_min_confidence_for_required_fail,
                enabled=settings.finding_policy_enabled,
            )
            final_status = outcome.status
            result_meta = outcome.metadata

            if final_status == "pass":
                positives.append(criterion["title"])
            else:
                if not fail_text:
                    fail_text = comment_templates.get("fail", criterion.get("description") or criterion.get("title") or criterion["code"])
                    generated_comment = fail_text
                if severity == "required" and final_status in ("fail", "unknown"):
                    required_fixes.append(fail_text)
                elif final_status != "pass":
                    extra_recommendations.append(fail_text)

                if project.source_type == "ipynb":
                    anchor_position_idx = result["anchor_position_idx"]
                    if anchor_position_idx is None:
                        anchor_position_idx = max(
                            (int(a["position_idx"] or 0) for a in artifact_dicts),
                            default=0,
                        )
                    comment_level = "danger" if severity == "required" and final_status in ("fail", "unknown") else "warning"
                    comment_html = build_notebook_comment_html(
                        title="Корректировка решения:",
                        body=fail_text,
                        level=comment_level,
                    )
                    notebook_insertions.append({"anchor_position_idx": anchor_position_idx, "comment_html": comment_html})

            merged = {
                "criterion_code": criterion_code,
                "severity": severity,
                "status": final_status,
                "confidence": result.get("confidence"),
                "anchor_position_idx": result.get("anchor_position_idx"),
                "evidence": result.get("evidence", []),
                "generated_comment": generated_comment,
                "metadata": result_meta,
                "category": criterion.get("category"),
            }
            merged_results.append(merged)

            cr_row = CriterionResult(
                id=str(uuid.uuid4()),
                project_id=project.id,
                criterion_code=criterion_code,
                severity=severity,
                status=final_status,
                confidence=result.get("confidence"),
                anchor_artifact_id=position_to_db_id.get(int(result["anchor_position_idx"]))
                if result.get("anchor_position_idx") is not None
                else None,
                evidence_json=result.get("evidence", []),
                generated_comment=generated_comment,
                metadata_json=result_meta,
            )
            self.db.add(cr_row)

        timeline.append({"stage": "criteria_merge_policy", "duration_ms": round((time.perf_counter() - t_crit) * 1000, 2)})
        _deadline_check()

        snapshot_batch_id = persist_review_snapshot(self.db, project.id, merged_results)

        t_verdict = time.perf_counter()
        final_verdict = build_verdict(merged_results)
        verdict_label = style_profile["verdict_labels"][final_verdict]

        sql_fix_bullets: list[str] = []
        if project.source_type == "sql":
            for m in merged_results:
                if m.get("status") == "pass":
                    continue
                for ev in m.get("evidence") or []:
                    if isinstance(ev, dict):
                        hint = ev.get("recommended_fix_hint")
                        prob = ev.get("problem_type")
                        if hint:
                            prefix = f"({prob}) " if prob else ""
                            sql_fix_bullets.append(f"- {prefix}{hint}")
        sql_fix_section = "\n".join(dict.fromkeys(sql_fix_bullets)) if sql_fix_bullets else None

        review_md = build_review_markdown(
            project_type=project.source_type,
            positives=positives,
            required_fixes=required_fixes,
            extra_recommendations=extra_recommendations,
            verdict_label=verdict_label,
            sql_fix_section=sql_fix_section,
        )
        settings = get_settings()
        if settings.enable_llm and llm_service.is_available:
            polished = llm_service.synthesize_review(
                {
                    "fallback_review": review_md,
                    "sections": {
                        "positives": positives,
                        "required_fixes": required_fixes,
                        "extra": extra_recommendations,
                        "verdict": verdict_label,
                    },
                }
            )
            if polished:
                review_md = polished

        parent_id = get_parent_project_id_for_child(self.db, project.id)
        exec_for_iteration = notebook_exec_meta if project.source_type == "ipynb" else {}
        if parent_id:
            _, iteration_fix_summary = compute_iteration_fixes(
                self.db,
                project.id,
                parent_id,
                merged_results,
                exec_for_iteration,
            )
        else:
            iteration_fix_summary = {"has_parent_link": False, "status": "no_parent_link"}
        iteration_fix_summary["current_snapshot_batch_id"] = snapshot_batch_id

        fix_section = build_iteration_fix_markdown_section(iteration_fix_summary)
        if fix_section:
            review_md = f"{review_md.rstrip()}\n\n{fix_section}"

        project.review_markdown = review_md
        project.final_verdict = final_verdict
        project.status = "done"

        timeline.append({"stage": "verdict_and_markdown", "duration_ms": round((time.perf_counter() - t_verdict) * 1000, 2)})
        timeline.append({"stage": "total_wall", "duration_ms": round((time.perf_counter() - pipeline_started) * 1000, 2)})

        meta_out = dict(parse_meta) if isinstance(parse_meta, dict) else {}
        meta_out["criteria_execution_summary"] = build_criteria_execution_summary_from_merged(merged_results)
        meta_out["parser_summary"] = build_parser_summary(meta_out, project.source_type)
        meta_out["review_pipeline_timeline"] = timeline
        meta_out["quality_summary"] = build_manual_review_summary(merged_results)
        meta_out["notebook_execution"] = (
            notebook_exec_meta if project.source_type == "ipynb" else {"notebook_execution_not_applicable": True}
        )
        meta_out["iteration_fix_summary"] = iteration_fix_summary
        if project.source_type == "datalens":
            meta_out["capture_summary"] = build_capture_summary(meta_out)
        prev = project.metadata_json or {}
        if "review_training_project" in prev:
            meta_out["review_training_project"] = prev["review_training_project"]
        for k, v in prev.items():
            if k.startswith("practicum_"):
                meta_out[k] = v
        if project.source_type == "html" and isinstance(parse_meta, dict):
            detected = bool(parse_meta.get("practicum_revisor_html_detected"))
            meta_out["practicum_revisor_html_detected"] = detected
            cur_ch = meta_out.get("practicum_input_channel")
            explicit = bool(meta_out.get("practicum_input_explicit"))
            if detected and cur_ch == "html" and not explicit:
                meta_out["practicum_input_channel"] = "revisor"
        meta_out["iteration_fix_summary"] = normalize_iteration_fix_summary(meta_out.get("iteration_fix_summary"))
        meta_out["notebook_execution"] = normalize_notebook_execution(meta_out.get("notebook_execution"))
        project.metadata_json = meta_out

        if project.source_type == "ipynb" and notebook_obj is not None:
            exporter = NotebookCommentInserter()
            notebook_insertions = dedupe_notebook_insertions(notebook_insertions)
            reviewed_notebook = exporter.insert_comments(notebook_obj, notebook_insertions)
            settings = get_settings()
            reviewed_path = Path(settings.exports_root) / project.id / "reviewed.ipynb"
            exporter.save(reviewed_notebook, str(reviewed_path))
            reviewed_file = ProjectFile(
                id=str(uuid.uuid4()),
                project_id=project.id,
                kind="reviewed",
                storage_path=str(reviewed_path),
                mime_type=".ipynb",
                metadata_json={},
            )
            self.db.add(reviewed_file)

        self.db.commit()
        self.db.refresh(project)
        return project
