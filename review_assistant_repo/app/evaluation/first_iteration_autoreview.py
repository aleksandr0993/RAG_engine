from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import nbformat

from app.analyzers.rules import RuleEngine
from app.config import get_settings
from app.exporters.notebook import NotebookCommentInserter
from app.llm.service import LLMService, get_llm_service
from app.parsers.notebook import NotebookParser
from app.retrieval.reviewer_insertions import (
    detect_alert_color,
    extract_reviewer_insertions,
    extract_features,
    load_insertion_rows,
    plain_text,
    choose_insertion_anchor,
)
from app.services.comment_dedup import dedupe_notebook_insertions
from app.services.finding_policy import apply_low_confidence_and_quality_policy, coerce_source_stage_metadata
from app.utils.config_loader import load_criteria_map
from app.utils.notebook_html import build_notebook_comment_html

_EXPLICIT_REVIEW_VERSION_RE = re.compile(r"Комментарий\s+ревьюера\s*\d+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[\wа-яА-ЯёЁ]+", re.UNICODE)


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 2}


def text_similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _alert_from_level(level: str) -> str:
    return "danger" if level == "danger" else "warning"


def _status_from_memory_kind(row: dict[str, Any]) -> str:
    kind = str(row.get("comment_kind") or "")
    if kind == "criterion_success":
        return "memory_success"
    if kind == "non_criterion_praise":
        return "memory_praise"
    if str(row.get("alert_color") or "") == "danger":
        return "memory_fail"
    return "memory_warn"


def _status_from_llm_classification(comment_kind: str, alert_color: str) -> str:
    if comment_kind == "criterion_success":
        return "memory_success"
    if comment_kind == "non_criterion_praise":
        return "memory_praise"
    if alert_color == "danger":
        return "memory_fail"
    return "memory_warn"


def _kind_from_memory_status(status: str) -> str:
    if status == "memory_success":
        return "criterion_success"
    if status == "memory_praise":
        return "non_criterion_praise"
    if status in {"memory_fail", "memory_warn"}:
        return "actionable_feedback"
    return "unknown"


def _public_gold_row(row: dict[str, Any]) -> dict[str, Any]:
    anchor = row.get("anchor_before") or {}
    return {
        "example_id": row.get("example_id"),
        "reviewed_notebook": row.get("reviewed_notebook"),
        "comment_text": row.get("comment_text"),
        "alert_color": row.get("alert_color"),
        "criterion_code": row.get("criterion_code"),
        "praise_code": row.get("praise_code"),
        "comment_kind": row.get("comment_kind"),
        "section_path": row.get("section_path") or [],
        "anchor_position_idx": row.get("anchor_position_idx"),
        "anchor_cell_type": anchor.get("cell_type") or "",
        "anchor_features": anchor.get("features") or [],
        "anchor_content_hash": anchor.get("content_hash") or "",
    }


def _memory_row_is_first_iteration(row: dict[str, Any]) -> bool:
    text = str(row.get("comment_text") or "")
    if _EXPLICIT_REVIEW_VERSION_RE.search(text):
        return False
    return int(row.get("review_iteration") or 1) == 1


def extract_gold_first_review_comments(
    *,
    restored_notebook: Path,
    reviewed_notebook: Path,
    project: str,
) -> list[dict[str, Any]]:
    rows = extract_reviewer_insertions(restored_notebook, reviewed_notebook, project_type=project)
    gold: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("comment_text") or "")
        if _EXPLICIT_REVIEW_VERSION_RE.search(text):
            continue
        if int(row.get("review_iteration") or 1) != 1:
            continue
        gold.append(_public_gold_row(row))
    return gold


def _parse_artifacts(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parsed, notebook_obj = NotebookParser().parse(str(path), strip_review_comments=True)
    artifacts: list[dict[str, Any]] = []
    for item in parsed:
        artifacts.append(
            {
                "artifact_type": item.artifact_type,
                "position_idx": item.position_idx,
                "section_name": item.section_name,
                "raw_text": item.raw_text,
                "normalized_text": item.normalized_text,
                "metadata_json": item.metadata,
            }
        )
    return artifacts, notebook_obj


def _artifact_text(artifact: dict[str, Any]) -> str:
    return str(artifact.get("normalized_text") or artifact.get("raw_text") or "")


def _artifact_features(artifact: dict[str, Any]) -> set[str]:
    return set(extract_features(_artifact_text(artifact)))


def _anchor_context(artifacts: list[dict[str, Any]], anchor_idx: int | None) -> dict[str, Any]:
    if anchor_idx is None:
        return {}
    ordered = sorted(
        [a for a in artifacts if a.get("position_idx") is not None],
        key=lambda item: int(item.get("position_idx") or 0),
    )
    current_pos = next((i for i, item in enumerate(ordered) if int(item.get("position_idx") or -1) == int(anchor_idx)), None)
    if current_pos is None:
        return {}
    return {
        "anchor_position_idx": anchor_idx,
        "cells": [
            {
                "position_idx": item.get("position_idx"),
                "artifact_type": item.get("artifact_type"),
                "section_name": item.get("section_name"),
                "text": _artifact_text(item)[:1800],
            }
            for item in ordered[max(0, current_pos - 1) : current_pos + 2]
        ],
    }


def _memory_candidate_score(artifact: dict[str, Any], row: dict[str, Any]) -> float:
    art_features = _artifact_features(artifact)
    row_features = set((row.get("anchor_before") or {}).get("features") or [])
    feature_score = len(art_features & row_features) / len(row_features) if row_features else 0.0
    text_score = text_similarity(_artifact_text(artifact), str((row.get("local_context") or {}).get("before_text") or ""))
    section_path = " ".join(str(x).lower() for x in (row.get("section_path") or []))
    section = str(artifact.get("section_name") or "").lower()
    section_score = 1.0 if section and section in section_path else 0.0
    kind_bonus = 0.10 if row.get("comment_kind") in {"actionable_feedback", "criterion_success", "non_criterion_praise"} else 0.0
    return round(0.50 * feature_score + 0.30 * text_score + 0.10 * section_score + kind_bonus, 4)


def _best_memory_anchor(artifacts: list[dict[str, Any]], row: dict[str, Any]) -> tuple[int | None, float]:
    best_idx: int | None = None
    best_score = 0.0
    for artifact in artifacts:
        meta = artifact.get("metadata_json") or artifact.get("metadata") or {}
        if meta.get("is_reviewer_comment") or meta.get("is_middle_reviewer_comment") or meta.get("is_student_comment"):
            continue
        pos = artifact.get("position_idx")
        if pos is None:
            continue
        score = _memory_candidate_score(artifact, row)
        if score > best_score:
            best_idx = int(pos)
            best_score = score
    return best_idx, best_score


def generate_all_first_iteration_memory_candidates(
    *,
    artifacts: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    project: str,
    exclude_reviewed_notebook: str | None = None,
    min_score: float = 0.35,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in memory_rows:
        if exclude_reviewed_notebook and row.get("reviewed_notebook") == exclude_reviewed_notebook:
            continue
        row_project = str(row.get("project_type") or row.get("source_project") or "")
        if row_project and row_project != project:
            continue
        if not _memory_row_is_first_iteration(row):
            continue
        anchor_idx, score = _best_memory_anchor(artifacts, row)
        if anchor_idx is None or score < min_score:
            continue
        status = _status_from_memory_kind(row)
        comment_text = str(row.get("comment_text") or "")
        alert_color = str(row.get("alert_color") or detect_alert_color(comment_text) or "unknown")
        candidates.append(
            {
                "criterion_code": str(row.get("criterion_code") or ""),
                "praise_code": str(row.get("praise_code") or ""),
                "status": status,
                "severity": "memory",
                "confidence": score,
                "anchor_position_idx": anchor_idx,
                "alert_color": alert_color,
                "comment_kind": row.get("comment_kind") or _kind_from_memory_status(status),
                "comment_text": comment_text,
                "comment_html": build_notebook_comment_html("Комментарий:", comment_text, level=alert_color),
                "evidence": [],
                "metadata": {
                    "source_stage": "memory_retrieval",
                    "memory_candidate_score": score,
                    "memory_example_id": row.get("example_id"),
                    "memory_reviewed_notebook": row.get("reviewed_notebook"),
                    "memory_source_notebook": row.get("source_notebook"),
                },
            }
        )

    candidates.sort(
        key=lambda item: (
            -float(item.get("confidence") or 0),
            str(item.get("criterion_code") or ""),
            int(item.get("anchor_position_idx") or 0),
        )
    )
    return candidates


def generate_first_iteration_memory_candidates(
    *,
    artifacts: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    project: str,
    exclude_reviewed_notebook: str | None = None,
    min_score: float = 0.35,
    max_candidates: int = 40,
    max_per_criterion_kind: int = 4,
) -> list[dict[str, Any]]:
    candidates = generate_all_first_iteration_memory_candidates(
        artifacts=artifacts,
        memory_rows=memory_rows,
        project=project,
        exclude_reviewed_notebook=exclude_reviewed_notebook,
        min_score=min_score,
    )
    picked: list[dict[str, Any]] = []
    per_group: Counter[tuple[str, str]] = Counter()
    seen_text_anchor: set[tuple[str, int]] = set()
    for item in candidates:
        key = (str(item.get("criterion_code") or ""), str(item.get("comment_kind") or item.get("status") or ""))
        if per_group[key] >= max_per_criterion_kind:
            continue
        text_key = (plain_text(str(item.get("comment_text") or "")).lower(), int(item.get("anchor_position_idx") or 0))
        if text_key in seen_text_anchor:
            continue
        seen_text_anchor.add(text_key)
        per_group[key] += 1
        picked.append(item)
        if len(picked) >= max_candidates:
            break
    return picked


def _rank_auc(points: list[tuple[float, int]]) -> float | None:
    positives = [score for score, label in points if label == 1]
    negatives = [score for score, label in points if label == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    total = len(positives) * len(negatives)
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return round(wins / total, 4)


def _average_precision(points: list[tuple[float, int]]) -> float | None:
    positives = sum(1 for _, label in points if label == 1)
    if positives == 0:
        return None
    ranked = sorted(points, key=lambda item: item[0], reverse=True)
    hits = 0
    precision_sum = 0.0
    for idx, (_score, label) in enumerate(ranked, start=1):
        if label != 1:
            continue
        hits += 1
        precision_sum += hits / idx
    return round(precision_sum / positives, 4)


def label_memory_candidates_for_auc(
    candidates: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    *,
    min_match_score: float = 0.35,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    unmatched_gold = set(range(len(gold)))
    labeled: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: float(item.get("confidence") or 0), reverse=True):
        best: tuple[float, int] | None = None
        for gi in unmatched_gold:
            gold_row = gold[gi]
            if gold_row.get("criterion_code") and candidate.get("criterion_code") != gold_row.get("criterion_code"):
                continue
            score = _match_score(candidate, gold_row)
            if best is None or score > best[0]:
                best = (score, gi)
        label = 0
        matched_gold_index: int | None = None
        match_score = 0.0
        if best is not None and best[0] >= min_match_score:
            match_score, matched_gold_index = best
            unmatched_gold.remove(matched_gold_index)
            label = 1
        row = dict(candidate)
        row["auc_label"] = label
        row["matched_gold_index"] = matched_gold_index
        row["match_score"] = match_score
        labeled.append(row)

    points = [(float(row.get("confidence") or 0), int(row["auc_label"])) for row in labeled]
    positives = sum(label for _, label in points)
    summary = {
        "candidate_total": len(labeled),
        "positive_candidates": positives,
        "negative_candidates": len(labeled) - positives,
        "roc_auc": _rank_auc(points),
        "pr_auc_average_precision": _average_precision(points),
    }
    return labeled, summary


def apply_llm_judge_generator(
    candidates: list[dict[str, Any]],
    *,
    artifacts: list[dict[str, Any]],
    llm_service: LLMService | None = None,
    enable_judge: bool = False,
    enable_generator: bool = False,
    enable_classifier: bool = False,
    enable_anchor_validator: bool = False,
    max_candidates: int = 30,
) -> list[dict[str, Any]]:
    if not (enable_judge or enable_generator or enable_classifier or enable_anchor_validator):
        return candidates

    llm = llm_service or get_llm_service()
    if not llm.is_available:
        out: list[dict[str, Any]] = []
        for item in candidates:
            updated = dict(item)
            meta = dict(updated.get("metadata") or {})
            meta["llm_skipped"] = "llm_unavailable"
            updated["metadata"] = meta
            out.append(updated)
        return out

    refined: list[dict[str, Any]] = []
    for idx, item in enumerate(candidates):
        updated = dict(item)
        meta = dict(updated.get("metadata") or {})
        if idx >= max_candidates:
            refined.append(updated)
            continue

        context = {
            "candidate": {
                "criterion_code": updated.get("criterion_code"),
                "praise_code": updated.get("praise_code"),
                "comment_kind": updated.get("comment_kind"),
                "alert_color": updated.get("alert_color"),
                "comment_text": updated.get("comment_text"),
                "memory_candidate_score": meta.get("memory_candidate_score") or updated.get("confidence"),
            },
            "anchor_context": _anchor_context(artifacts, updated.get("anchor_position_idx")),
        }

        keep = True
        anchor_valid = True
        if enable_classifier:
            prompt = (
                "Ты классифицируешь комментарий ревьюера к учебной Jupyter-тетрадке.\n"
                "Верни только JSON: {"
                '"comment_kind": "actionable_feedback|criterion_success|non_criterion_praise|reviewer_note", '
                '"criterion_code": "... или пусто", '
                '"praise_code": "... или пусто", '
                '"alert_color": "danger|warning|success|unknown", '
                '"confidence": 0..1, '
                '"rationale": "..."}.\n'
                "actionable_feedback = нужно исправить; criterion_success = похвала по критерию; "
                "non_criterion_praise = общая похвала; reviewer_note = служебная заметка/не вставлять как проверку.\n"
                f"Данные:\n{json.dumps(context, ensure_ascii=False)[:12000]}"
            )
            result = llm.chat([{"role": "user", "content": prompt}], temperature=0.1)
            meta["llm_classifier_used"] = bool(result.ok)
            if result.ok:
                parsed = _extract_json_object(result.text)
                if parsed:
                    llm_kind = str(parsed.get("comment_kind") or "").strip()
                    llm_alert = str(parsed.get("alert_color") or "").strip()
                    if llm_kind in {"actionable_feedback", "criterion_success", "non_criterion_praise", "reviewer_note"}:
                        updated["comment_kind"] = llm_kind
                        meta["llm_comment_kind"] = llm_kind
                    if llm_alert in {"danger", "warning", "success", "unknown"}:
                        updated["alert_color"] = llm_alert
                        meta["llm_alert_color"] = llm_alert
                    criterion_code = str(parsed.get("criterion_code") or "").strip()
                    praise_code = str(parsed.get("praise_code") or "").strip()
                    if criterion_code:
                        updated["criterion_code"] = criterion_code
                    if praise_code:
                        updated["praise_code"] = praise_code
                    if llm_kind == "reviewer_note":
                        keep = False
                    if llm_kind in {"actionable_feedback", "criterion_success", "non_criterion_praise"}:
                        updated["status"] = _status_from_llm_classification(
                            llm_kind,
                            str(updated.get("alert_color") or "warning"),
                        )
                    meta["llm_classifier_confidence"] = parsed.get("confidence")
                    meta["llm_classifier_rationale"] = str(parsed.get("rationale") or "")[:500]
                else:
                    meta["llm_classifier_error"] = "unparseable_response"
            else:
                meta["llm_classifier_error"] = result.error or "llm_call_failed"

        if enable_judge:
            prompt = (
                "Ты оцениваешь, стоит ли вставлять комментарий ревьюера в учебную Jupyter-тетрадку.\n"
                "Верни только JSON: {\"keep\": true|false, \"confidence\": 0..1, \"rationale\": \"...\"}.\n"
                "Оставляй комментарий только если он конкретно относится к anchor_context и не является лишним дублем.\n"
                f"Данные:\n{json.dumps(context, ensure_ascii=False)[:12000]}"
            )
            result = llm.chat([{"role": "user", "content": prompt}], temperature=0.1)
            meta["llm_judge_used"] = bool(result.ok)
            if result.ok:
                parsed = _extract_json_object(result.text)
                if parsed:
                    keep = bool(parsed.get("keep", True))
                    meta["llm_judge_keep"] = keep
                    meta["llm_judge_confidence"] = parsed.get("confidence")
                    meta["llm_judge_rationale"] = str(parsed.get("rationale") or "")[:500]
                else:
                    meta["llm_judge_error"] = "unparseable_response"
            else:
                meta["llm_judge_error"] = result.error or "llm_call_failed"

        if not keep:
            meta["source_stage"] = "llm"
            updated["metadata"] = meta
            refined.append(updated)
            continue

        if enable_anchor_validator:
            validator_context = {
                **context,
                "candidate": {
                    **context["candidate"],
                    "criterion_code": updated.get("criterion_code"),
                    "praise_code": updated.get("praise_code"),
                    "comment_kind": updated.get("comment_kind"),
                    "alert_color": updated.get("alert_color"),
                    "comment_text": updated.get("comment_text"),
                },
            }
            prompt = (
                "Ты проверяешь место вставки комментария ревьюера в Jupyter-тетрадке.\n"
                "Верни только JSON: {"
                '"valid": true|false, '
                '"confidence": 0..1, '
                '"rationale": "...", '
                '"better_anchor_hint": "... или пусто"}.\n'
                "valid=true только если anchor_context действительно расположен рядом с проблемой, решением или похвалой, "
                "к которой относится комментарий. Если связь слабая, ставь valid=false.\n"
                f"Данные:\n{json.dumps(validator_context, ensure_ascii=False)[:12000]}"
            )
            result = llm.chat([{"role": "user", "content": prompt}], temperature=0.1)
            meta["llm_anchor_validator_used"] = bool(result.ok)
            if result.ok:
                parsed = _extract_json_object(result.text)
                if parsed:
                    anchor_valid = bool(parsed.get("valid", True))
                    meta["llm_anchor_valid"] = anchor_valid
                    meta["llm_anchor_confidence"] = parsed.get("confidence")
                    meta["llm_anchor_rationale"] = str(parsed.get("rationale") or "")[:500]
                    hint = str(parsed.get("better_anchor_hint") or "").strip()
                    if hint:
                        meta["llm_anchor_better_hint"] = hint[:500]
                else:
                    meta["llm_anchor_validator_error"] = "unparseable_response"
            else:
                meta["llm_anchor_validator_error"] = result.error or "llm_call_failed"

        if not anchor_valid:
            meta["source_stage"] = "llm"
            updated["metadata"] = meta
            refined.append(updated)
            continue

        if enable_generator:
            prompt = (
                "Ты адаптируешь комментарий ревьюера под текущую тетрадку, сохраняя стиль автора.\n"
                "Верни только JSON: {\"comment_text\": \"...\", \"rationale\": \"...\"}.\n"
                "Не добавляй приветствие или итоговый комментарий. Не упоминай, что ты LLM.\n"
                f"Данные:\n{json.dumps(context, ensure_ascii=False)[:12000]}"
            )
            result = llm.chat([{"role": "user", "content": prompt}], temperature=0.25)
            meta["llm_generator_used"] = bool(result.ok)
            if result.ok:
                parsed = _extract_json_object(result.text)
                generated = str((parsed or {}).get("comment_text") or "").strip()
                if generated:
                    updated["comment_text"] = generated
                    updated["comment_html"] = build_notebook_comment_html(
                        "Комментарий:",
                        generated,
                        level=str(updated.get("alert_color") or "warning"),
                    )
                    meta["llm_generator_rationale"] = str((parsed or {}).get("rationale") or "")[:500]
                else:
                    meta["llm_generator_error"] = "empty_or_unparseable_response"
            else:
                meta["llm_generator_error"] = result.error or "llm_call_failed"

        if (
            meta.get("llm_judge_used")
            or meta.get("llm_generator_used")
            or meta.get("llm_classifier_used")
            or meta.get("llm_anchor_validator_used")
        ):
            meta["source_stage"] = "llm"
        updated["metadata"] = meta
        refined.append(updated)
    return refined


def run_offline_autoreview(
    *,
    restored_notebook: Path,
    criteria_map: str,
    project: str,
    reviewer_insertions_path: Path | None = None,
    exclude_reviewed_notebook: str | None = None,
    include_memory_candidates: bool = True,
    memory_candidate_min_score: float = 0.35,
    max_memory_candidates: int = 30,
    enable_llm_judge: bool = False,
    enable_llm_generator: bool = False,
    enable_llm_classifier: bool = False,
    enable_llm_anchor_validator: bool = False,
    llm_max_candidates: int = 30,
    llm_service: LLMService | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    criteria = load_criteria_map(criteria_map)
    artifacts, notebook_obj = _parse_artifacts(restored_notebook)
    raw_results = RuleEngine().run(artifacts, criteria)
    settings = get_settings()
    memory_rows = load_insertion_rows(reviewer_insertions_path) if reviewer_insertions_path else []
    if exclude_reviewed_notebook:
        memory_rows = [r for r in memory_rows if r.get("reviewed_notebook") != exclude_reviewed_notebook]
    all_memory_candidates = (
        generate_all_first_iteration_memory_candidates(
            artifacts=artifacts,
            memory_rows=memory_rows,
            project=project,
            exclude_reviewed_notebook=None,
            min_score=0.0,
        )
        if memory_rows
        else []
    )

    predicted: list[dict[str, Any]] = []
    notebook_insertions: list[dict[str, Any]] = []
    for criterion, result in zip(criteria, raw_results, strict=True):
        criterion_code = str(criterion["code"])
        severity = str(criterion.get("severity") or "")
        status = str(result.get("status") or "unknown")
        metadata = coerce_source_stage_metadata(dict(result.get("metadata") or {}), criterion.get("detection_mode"))
        outcome = apply_low_confidence_and_quality_policy(
            status=status,
            severity=severity,
            confidence=result.get("confidence"),
            metadata=metadata,
            criterion_code=criterion_code,
            min_confidence_for_required_fail=settings.finding_min_confidence_for_required_fail,
            enabled=settings.finding_policy_enabled,
        )
        final_status = outcome.status
        if final_status == "pass":
            continue

        templates = criterion.get("comment_templates") or {}
        comment_text = templates.get("fail") or criterion.get("description") or criterion.get("title") or criterion_code
        level = "danger" if severity == "required" and final_status in {"fail", "unknown"} else "warning"
        anchor_position_idx = result.get("anchor_position_idx")
        meta = dict(outcome.metadata)
        if memory_rows and (anchor_position_idx is None or not result.get("evidence")):
            learned = choose_insertion_anchor(
                artifacts,
                memory_rows,
                project_type=project,
                criterion_code=criterion_code,
                alert_color=_alert_from_level(level),
                query_text=str(comment_text),
                min_score=settings.reviewer_insertion_min_score,
            )
            if learned is not None:
                anchor_position_idx = learned.position_idx
                meta["reviewer_insertion_memory"] = {
                    "score": learned.score,
                    "example_id": learned.example.get("example_id"),
                    "source_notebook": learned.example.get("source_notebook"),
                }
        if anchor_position_idx is None:
            anchor_position_idx = max((int(a.get("position_idx") or 0) for a in artifacts), default=0)

        html = build_notebook_comment_html("Корректировка решения:", str(comment_text), level=level)
        predicted.append(
            {
                "criterion_code": criterion_code,
                "status": final_status,
                "severity": severity,
                "confidence": outcome.confidence,
                "anchor_position_idx": int(anchor_position_idx),
                "alert_color": _alert_from_level(level),
                "comment_text": str(comment_text),
                "comment_html": html,
                "evidence": result.get("evidence") or [],
                "metadata": meta,
            }
        )
        notebook_insertions.append({"anchor_position_idx": int(anchor_position_idx), "comment_html": html})

    if include_memory_candidates and memory_rows:
        memory_candidates = generate_first_iteration_memory_candidates(
            artifacts=artifacts,
            memory_rows=memory_rows,
            project=project,
            exclude_reviewed_notebook=exclude_reviewed_notebook,
            min_score=memory_candidate_min_score,
            max_candidates=max_memory_candidates,
        )
        memory_candidates = apply_llm_judge_generator(
            memory_candidates,
            artifacts=artifacts,
            llm_service=llm_service,
            enable_judge=enable_llm_judge,
            enable_generator=enable_llm_generator,
            enable_classifier=enable_llm_classifier,
            enable_anchor_validator=enable_llm_anchor_validator,
            max_candidates=llm_max_candidates,
        )
        existing = {
            (str(item.get("criterion_code") or ""), int(item.get("anchor_position_idx") or 0), str(item.get("comment_text") or ""))
            for item in predicted
        }
        for item in memory_candidates:
            meta = item.get("metadata") or {}
            if meta.get("llm_judge_keep") is False or meta.get("llm_anchor_valid") is False:
                continue
            key = (str(item.get("criterion_code") or ""), int(item.get("anchor_position_idx") or 0), str(item.get("comment_text") or ""))
            if key in existing:
                continue
            predicted.append(item)
            notebook_insertions.append({"anchor_position_idx": int(item["anchor_position_idx"]), "comment_html": item["comment_html"]})
            existing.add(key)

    deduped = dedupe_notebook_insertions(notebook_insertions)
    reviewed_obj = NotebookCommentInserter().insert_comments(notebook_obj, deduped)
    return predicted, reviewed_obj, all_memory_candidates


def _match_score(pred: dict[str, Any], gold: dict[str, Any]) -> float:
    score = 0.0
    if pred.get("criterion_code") and pred.get("criterion_code") == gold.get("criterion_code"):
        score += 0.45
    if pred.get("alert_color") == gold.get("alert_color"):
        score += 0.15
    p_anchor = pred.get("anchor_position_idx")
    g_anchor = gold.get("anchor_position_idx")
    if p_anchor is not None and g_anchor is not None:
        delta = abs(int(p_anchor) - int(g_anchor))
        score += max(0.0, 0.25 - min(delta, 5) * 0.05)
    score += 0.15 * text_similarity(str(pred.get("comment_text") or ""), str(gold.get("comment_text") or ""))
    return round(score, 4)


def compare_predictions(predicted: list[dict[str, Any]], gold: list[dict[str, Any]]) -> dict[str, Any]:
    unmatched_pred = set(range(len(predicted)))
    matches: list[dict[str, Any]] = []
    missed: list[dict[str, Any]] = []

    for gi, gold_row in enumerate(gold):
        best: tuple[float, int] | None = None
        for pi in unmatched_pred:
            pred = predicted[pi]
            if gold_row.get("criterion_code") and pred.get("criterion_code") != gold_row.get("criterion_code"):
                continue
            score = _match_score(pred, gold_row)
            if best is None or score > best[0]:
                best = (score, pi)
        if best is None or best[0] < 0.35:
            missed.append({"gold_index": gi, **gold_row})
            continue
        _, pi = best
        unmatched_pred.remove(pi)
        pred = predicted[pi]
        p_anchor = pred.get("anchor_position_idx")
        g_anchor = gold_row.get("anchor_position_idx")
        delta = abs(int(p_anchor) - int(g_anchor)) if p_anchor is not None and g_anchor is not None else None
        matches.append(
            {
                "gold_index": gi,
                "predicted_index": pi,
                "score": best[0],
                "anchor_delta": delta,
                "criterion_match": pred.get("criterion_code") == gold_row.get("criterion_code"),
                "alert_match": pred.get("alert_color") == gold_row.get("alert_color"),
                "text_similarity": text_similarity(str(pred.get("comment_text") or ""), str(gold_row.get("comment_text") or "")),
                "gold": gold_row,
                "predicted": pred,
            }
        )

    extra = [{"predicted_index": pi, **predicted[pi]} for pi in sorted(unmatched_pred)]
    actionable_gold = [g for g in gold if g.get("comment_kind") == "actionable_feedback"]
    actionable_missed = [m for m in missed if m.get("comment_kind") == "actionable_feedback"]
    anchor_deltas = [m["anchor_delta"] for m in matches if m.get("anchor_delta") is not None]
    return {
        "summary": {
            "gold_total": len(gold),
            "gold_actionable": len(actionable_gold),
            "predicted_total": len(predicted),
            "matched_total": len(matches),
            "missed_total": len(missed),
            "missed_actionable": len(actionable_missed),
            "extra_total": len(extra),
            "precision_approx": round(len(matches) / len(predicted), 4) if predicted else 0.0,
            "recall_approx": round(len(matches) / len(gold), 4) if gold else 0.0,
            "actionable_recall_approx": round((len(actionable_gold) - len(actionable_missed)) / len(actionable_gold), 4)
            if actionable_gold
            else 0.0,
            "anchor_exact": sum(1 for d in anchor_deltas if d == 0),
            "anchor_within_1": sum(1 for d in anchor_deltas if d <= 1),
            "anchor_within_2": sum(1 for d in anchor_deltas if d <= 2),
            "anchor_mean_delta": round(sum(anchor_deltas) / len(anchor_deltas), 4) if anchor_deltas else None,
            "gold_comment_kind_counts": dict(Counter(g.get("comment_kind") or "unknown" for g in gold)),
            "predicted_status_counts": dict(Counter(p.get("status") or "unknown" for p in predicted)),
            "predicted_source_stage_counts": dict(
                Counter((p.get("metadata") or {}).get("source_stage") or "unknown" for p in predicted)
            ),
        },
        "matches": matches,
        "missed_gold": missed,
        "extra_predicted": extra,
    }


def render_report(payload: dict[str, Any]) -> str:
    s = payload["comparison"]["summary"]
    auc = payload.get("candidate_auc") or {}
    lines = [
        "# First-iteration autoreview evaluation",
        "",
        f"- Reviewed notebook: `{payload['reviewed_notebook']}`",
        f"- Restored notebook: `{payload['restored_notebook']}`",
        f"- Criteria map: `{payload['criteria_map']}`",
        "",
        "## Summary",
        "",
        f"- Gold comments: {s['gold_total']} (actionable: {s['gold_actionable']})",
        f"- Predicted comments: {s['predicted_total']}",
        f"- Matched: {s['matched_total']}",
        f"- Missed gold: {s['missed_total']} (actionable: {s['missed_actionable']})",
        f"- Extra predicted: {s['extra_total']}",
        f"- Approx precision / recall: {s['precision_approx']} / {s['recall_approx']}",
        f"- Actionable recall: {s['actionable_recall_approx']}",
        f"- Anchor exact / within 1 / within 2: {s['anchor_exact']} / {s['anchor_within_1']} / {s['anchor_within_2']}",
        f"- Anchor mean delta: {s['anchor_mean_delta']}",
        f"- Gold kinds: {json.dumps(s['gold_comment_kind_counts'], ensure_ascii=False)}",
        f"- Predicted statuses: {json.dumps(s['predicted_status_counts'], ensure_ascii=False)}",
        f"- Predicted source stages: {json.dumps(s.get('predicted_source_stage_counts', {}), ensure_ascii=False)}",
        f"- Memory candidate ROC-AUC: {auc.get('roc_auc')}",
        f"- Memory candidate PR-AUC/AP: {auc.get('pr_auc_average_precision')}",
        f"- Memory candidates labeled: {auc.get('candidate_total')} "
        f"(TP: {auc.get('positive_candidates')}, FP: {auc.get('negative_candidates')})",
        "",
        "## Missed Gold",
        "",
    ]
    missed = payload["comparison"]["missed_gold"][:30]
    if not missed:
        lines.append("No missed gold comments.")
    else:
        lines.extend(["| Kind | Criterion | Alert | Comment |", "|---|---|---|---|"])
        for row in missed:
            text = str(row.get("comment_text") or "").replace("\n", " ")[:180]
            lines.append(f"| {row.get('comment_kind')} | `{row.get('criterion_code')}` | {row.get('alert_color')} | {text} |")
    lines.extend(["", "## Extra Predicted", ""])
    extra = payload["comparison"]["extra_predicted"][:30]
    if not extra:
        lines.append("No extra predicted comments.")
    else:
        lines.extend(["| Status | Criterion | Anchor | Comment |", "|---|---|---:|---|"])
        for row in extra:
            text = str(row.get("comment_text") or "").replace("\n", " ")[:180]
            lines.append(f"| {row.get('status')} | `{row.get('criterion_code')}` | {row.get('anchor_position_idx')} | {text} |")
    lines.append("")
    return "\n".join(lines)


def evaluate_first_iteration(
    *,
    reviewed_notebook: Path,
    restored_notebook: Path,
    project: str,
    criteria_map: str,
    out_dir: Path,
    reviewer_insertions_path: Path | None = None,
    include_memory_candidates: bool = True,
    memory_candidate_min_score: float = 0.35,
    max_memory_candidates: int = 30,
    enable_llm_judge: bool = False,
    enable_llm_generator: bool = False,
    enable_llm_classifier: bool = False,
    enable_llm_anchor_validator: bool = False,
    llm_max_candidates: int = 30,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    gold = extract_gold_first_review_comments(
        restored_notebook=restored_notebook,
        reviewed_notebook=reviewed_notebook,
        project=project,
    )
    predicted, reviewed_obj, all_memory_candidates = run_offline_autoreview(
        restored_notebook=restored_notebook,
        criteria_map=criteria_map,
        project=project,
        reviewer_insertions_path=reviewer_insertions_path,
        exclude_reviewed_notebook=reviewed_notebook.name,
        include_memory_candidates=include_memory_candidates,
        memory_candidate_min_score=memory_candidate_min_score,
        max_memory_candidates=max_memory_candidates,
        enable_llm_judge=enable_llm_judge,
        enable_llm_generator=enable_llm_generator,
        enable_llm_classifier=enable_llm_classifier,
        enable_llm_anchor_validator=enable_llm_anchor_validator,
        llm_max_candidates=llm_max_candidates,
    )
    comparison = compare_predictions(predicted, gold)
    labeled_candidates, candidate_auc_summary = label_memory_candidates_for_auc(all_memory_candidates, gold)
    predicted_reviewed = out_dir / "predicted_reviewed.ipynb"
    nbformat.write(reviewed_obj, predicted_reviewed)
    _write_jsonl(gold, out_dir / "gold_first_review_comments.jsonl")
    _write_jsonl(predicted, out_dir / "predicted_insertions.jsonl")
    _write_jsonl(labeled_candidates, out_dir / "all_memory_candidates_labeled.jsonl")
    payload = {
        "reviewed_notebook": str(reviewed_notebook),
        "restored_notebook": str(restored_notebook),
        "criteria_map": criteria_map,
        "project": project,
        "artifacts": {
            "gold_jsonl": str(out_dir / "gold_first_review_comments.jsonl"),
            "predicted_jsonl": str(out_dir / "predicted_insertions.jsonl"),
            "all_memory_candidates_labeled_jsonl": str(out_dir / "all_memory_candidates_labeled.jsonl"),
            "predicted_reviewed_notebook": str(predicted_reviewed),
            "comparison_json": str(out_dir / "comparison.json"),
            "report_md": str(out_dir / "report.md"),
        },
        "comparison": comparison,
        "candidate_auc": candidate_auc_summary,
    }
    (out_dir / "comparison.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload
