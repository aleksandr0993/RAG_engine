from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import nbformat

from app.parsers.notebook import infer_notebook_comment_role, is_review_role_cell
from app.retrieval.reviewer_insertions import (
    detect_alert_color,
    extract_reviewer_insertions,
    is_empty_project_reviewer_comment,
    is_system_reviewer_comment,
    normalize_cell_source,
    plain_text,
    write_insertion_rows,
)


def _classify_notebook_read_error(path: Path, exc: Exception) -> tuple[str, str]:
    error_type = type(exc).__name__
    message = str(exc)
    try:
        prefix = path.read_text(encoding="utf-8", errors="replace")[:12000].lower()
    except OSError:
        return error_type, message
    if "<!doctype html" in prefix or "<html" in prefix:
        if "data-notebook-path" in prefix:
            return "NotebookHtmlShellError", "File is a Jupyter HTML shell, not notebook JSON with cells."
        return "NotebookHtmlExportError", "File is HTML, not notebook JSON."
    return error_type, message


def discover_notebooks(input_path: Path, work_dir: Path) -> tuple[list[Path], Path | None]:
    if input_path.is_dir():
        return sorted(input_path.rglob("*.ipynb")), None
    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        extract_dir = work_dir / "_archive_extract"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(input_path) as zf:
            zf.extractall(extract_dir)
        return sorted(extract_dir.rglob("*.ipynb")), extract_dir
    if input_path.is_file() and (
        input_path.name.endswith(".tar")
        or input_path.name.endswith(".tar.gz")
        or input_path.name.endswith(".tgz")
    ):
        extract_dir = work_dir / "_archive_extract"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(input_path) as tf:
            _safe_extract_tar(tf, extract_dir)
        return sorted(extract_dir.rglob("*.ipynb")), extract_dir
    if input_path.is_file() and input_path.suffix.lower() == ".ipynb":
        return [input_path], None
    raise ValueError(f"Unsupported input: {input_path}")


def _safe_extract_tar(tf: tarfile.TarFile, extract_dir: Path) -> None:
    base = extract_dir.resolve()
    for member in tf.getmembers():
        target = (extract_dir / member.name).resolve()
        if base != target and base not in target.parents:
            raise ValueError(f"Unsafe path in archive: {member.name}")
    tf.extractall(extract_dir)


def _safe_rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _reviewer_marker_present(source: str) -> bool:
    role = infer_notebook_comment_role(source)
    if is_review_role_cell(role):
        return True
    text = plain_text(source)
    lowered = text.lower()
    return (
        "комментарий ревьюера" in lowered
        or "комментарий мидл" in lowered
        or ("ревьюер" in lowered and is_system_reviewer_comment(text))
    )


def restore_student_source_from_review(
    reviewed_path: Path,
    restored_path: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        nb = nbformat.read(reviewed_path, as_version=4)
    except Exception as exc:
        error_type, error_message = _classify_notebook_read_error(reviewed_path, exc)
        return (
            {
                "status": "error",
                "error_type": error_type,
                "error_message": error_message,
            },
            None,
        )

    restored = nbformat.from_dict(nb)
    filtered_cells = []
    removed_by_role: Counter[str] = Counter()
    removed_by_alert_color: Counter[str] = Counter()
    removed_cells = 0
    reviewer_comments_found = 0
    student_comments_removed = 0
    empty_project_comment_found = False

    for cell in nb.cells:
        source = normalize_cell_source(cell.get("source", ""))
        role = infer_notebook_comment_role(source)
        alert_color = detect_alert_color(source)
        remove = False
        remove_role = role

        if is_review_role_cell(role):
            remove = True
            reviewer_comments_found += 1
        elif role == "student" and "<div" in source:
            remove = True
            student_comments_removed += 1
        elif _reviewer_marker_present(source):
            remove = True
            remove_role = "reviewer"
            reviewer_comments_found += 1

        if remove:
            removed_cells += 1
            removed_by_role[remove_role] += 1
            if alert_color != "unknown":
                removed_by_alert_color[alert_color] += 1
            if is_empty_project_reviewer_comment(plain_text(source)):
                empty_project_comment_found = True
            continue
        filtered_cells.append(cell)

    restored["cells"] = filtered_cells
    restored_path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(restored, restored_path)

    remaining_markers = 0
    for cell in restored.cells:
        source = normalize_cell_source(cell.get("source", ""))
        if _reviewer_marker_present(source):
            remaining_markers += 1

    stats = {
        "status": "ok",
        "cells_before": len(nb.cells),
        "cells_after_restore": len(filtered_cells),
        "removed_cells": removed_cells,
        "removed_ratio": round(removed_cells / len(nb.cells), 4) if nb.cells else 0.0,
        "reviewer_comments_found": reviewer_comments_found,
        "student_comments_removed": student_comments_removed,
        "empty_project_comment_found": empty_project_comment_found,
        "removed_by_role": dict(removed_by_role),
        "removed_by_alert_color": dict(removed_by_alert_color),
        "remaining_reviewer_markers": remaining_markers,
    }
    return stats, restored


def _row_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    color_counts = Counter(str(row.get("alert_color") or "unknown") for row in rows)
    kind_counts = Counter(str(row.get("comment_kind") or "unknown") for row in rows)
    praise_counts = Counter(str(row.get("praise_code") or "") for row in rows if row.get("praise_code"))
    criteria_relevant_rows = [row for row in rows if row.get("comment_kind") != "non_criterion_praise"]
    unknown_criterion_count = sum(1 for row in criteria_relevant_rows if not row.get("criterion_code"))
    unknown_alert_count = color_counts.get("unknown", 0)
    weak_anchor_count = sum(
        1
        for row in criteria_relevant_rows
        if not ((row.get("anchor_before") or {}).get("content_hash"))
        or not ((row.get("anchor_before") or {}).get("features"))
    )
    comments = [plain_text(str(row.get("comment_text") or "")).lower() for row in rows]
    dup_count = sum(count - 1 for count in Counter(comments).values() if count > 1)
    total = len(rows)
    return {
        "insertions_extracted": total,
        "alert_counts": dict(color_counts),
        "comment_kind_counts": dict(kind_counts),
        "praise_counts": dict(praise_counts),
        "unknown_criterion_count": unknown_criterion_count,
        "unknown_criterion_ratio": round(unknown_criterion_count / len(criteria_relevant_rows), 4)
        if criteria_relevant_rows
        else 0.0,
        "unknown_alert_count": unknown_alert_count,
        "unknown_alert_ratio": round(unknown_alert_count / total, 4) if total else 0.0,
        "weak_anchor_count": weak_anchor_count,
        "weak_anchor_ratio": round(weak_anchor_count / len(criteria_relevant_rows), 4) if criteria_relevant_rows else 0.0,
        "duplicate_comment_count": dup_count,
        "duplicate_comment_ratio": round(dup_count / total, 4) if total else 0.0,
    }


def _student_work_text(restored_nb: dict[str, Any] | None) -> str:
    if restored_nb is None:
        return ""
    parts: list[str] = []
    for cell in restored_nb.get("cells", []):
        source = normalize_cell_source(cell.get("source", ""))
        role = infer_notebook_comment_role(source)
        if is_review_role_cell(role) or role == "student":
            continue
        if source:
            parts.append(source)
    return "\n".join(parts)


def _is_empty_project_review(stats: dict[str, Any], restored_nb: dict[str, Any] | None, rows: list[dict[str, Any]]) -> bool:
    if stats.get("status") != "ok":
        return False
    if stats.get("empty_project_comment_found"):
        return True
    comments = [plain_text(str(row.get("comment_text") or "")) for row in rows]
    has_empty_marker = any(is_empty_project_reviewer_comment(comment) for comment in comments)
    if not has_empty_marker:
        return False
    student_text = _student_work_text(restored_nb)
    return len(student_text) < 500 or int(stats.get("cells_after_restore") or 0) <= 3


def _manual_review_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("status") == "ignored_empty_project":
        return []
    if row.get("status") != "ok":
        return [f"invalid_notebook:{row.get('error_type') or 'unknown'}"]
    if row.get("reviewer_comments_found", 0) == 0:
        reasons.append("no_reviewer_comments_detected")
    if row.get("removed_cells", 0) == 0:
        reasons.append("no_cells_removed")
    if float(row.get("removed_ratio") or 0) > 0.40:
        reasons.append(f"removed_cells_ratio={row.get('removed_ratio')}")
    if row.get("remaining_reviewer_markers", 0) > 0:
        reasons.append(f"reviewer_markers_remain={row.get('remaining_reviewer_markers')}")
    if row.get("student_comments_removed", 0) > 0 and row.get("reviewer_comments_found", 0) == 0:
        reasons.append("student_comments_without_reviewer_comments")
    if float(row.get("unknown_criterion_ratio") or 0) > 0.30:
        reasons.append(f"unknown_criterion_ratio={row.get('unknown_criterion_ratio')}")
    if float(row.get("unknown_alert_ratio") or 0) > 0.30:
        reasons.append(f"unknown_alert_ratio={row.get('unknown_alert_ratio')}")
    if float(row.get("weak_anchor_ratio") or 0) > 0.30:
        reasons.append(f"weak_anchor_ratio={row.get('weak_anchor_ratio')}")
    if float(row.get("duplicate_comment_ratio") or 0) > 0.30:
        reasons.append(f"duplicate_comment_ratio={row.get('duplicate_comment_ratio')}")
    if row.get("insertions_extracted", 0) == 0:
        reasons.append("no_insertions_extracted")
    return reasons


def _restored_name(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]
    return f"{path.stem}__{digest}__student_source.ipynb"


def build_reviewer_insertion_memory_from_archive(
    *,
    input_path: Path,
    project: str,
    work_dir: Path,
    output: Path,
    report_md: Path,
    report_json: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    restored_dir = work_dir / "restored_sources"
    restored_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = work_dir / "manifest.jsonl"
    problem_files_path = work_dir / "problem_files.txt"

    notebooks, _extract_dir = discover_notebooks(input_path, work_dir)
    seen_hashes: set[str] = set()
    manifest: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    ignored_empty_projects = 0

    for notebook_path in notebooks:
        try:
            digest = hashlib.sha1(notebook_path.read_bytes()).hexdigest()
        except OSError:
            digest = hashlib.sha1(str(notebook_path).encode("utf-8")).hexdigest()
        file_hash = digest
        if file_hash in seen_hashes:
            continue
        seen_hashes.add(file_hash)

        restored_path = restored_dir / _restored_name(notebook_path)
        stats, _restored_nb = restore_student_source_from_review(notebook_path, restored_path)
        row: dict[str, Any] = {
            "reviewed_path": str(notebook_path),
            "reviewed_relpath": _safe_rel(notebook_path, input_path if input_path.is_dir() else work_dir),
            "restored_path": str(restored_path),
            "project": project,
            **stats,
        }
        rows: list[dict[str, Any]] = []
        if stats.get("status") == "ok":
            rows = extract_reviewer_insertions(restored_path, notebook_path, project_type=project)
            if _is_empty_project_review(stats, _restored_nb, rows):
                ignored_empty_projects += 1
                row.update(_row_quality([]))
                row["status"] = "ignored_empty_project"
                row["ignored_reason"] = "empty_project_review"
                row["manual_review_required"] = False
                row["manual_review_reasons"] = []
                manifest.append(row)
                continue
            all_rows.extend(rows)
            row.update(_row_quality(rows))
        else:
            row.update(_row_quality([]))
        reasons = _manual_review_reasons(row)
        row["manual_review_required"] = bool(reasons)
        row["manual_review_reasons"] = reasons
        manifest.append(row)

    write_insertion_rows(all_rows, output, append=not overwrite)
    _write_manifest(manifest, manifest_path)
    summary = _build_summary(project, input_path, output, manifest, all_rows)
    summary["ignored_empty_projects"] = ignored_empty_projects
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text(_render_report_md(summary, manifest), encoding="utf-8")
    problem_files_path.write_text(
        "\n".join(row["reviewed_path"] for row in manifest if row.get("manual_review_required")) + "\n",
        encoding="utf-8",
    )
    return summary


def _write_manifest(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _build_summary(
    project: str,
    input_path: Path,
    output: Path,
    manifest: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    alert_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    criterion_counts: Counter[str] = Counter()
    praise_counts: Counter[str] = Counter()
    for row in rows:
        alert_counts[str(row.get("alert_color") or "unknown")] += 1
        kind_counts[str(row.get("comment_kind") or "unknown")] += 1
        if row.get("criterion_code"):
            criterion_counts[str(row.get("criterion_code"))] += 1
        if row.get("praise_code"):
            praise_counts[str(row.get("praise_code"))] += 1
    problem_rows = [row for row in manifest if row.get("manual_review_required")]
    unknown_criterion = sum(
        1
        for row in rows
        if row.get("comment_kind") != "non_criterion_praise" and not row.get("criterion_code")
    )
    unknown_alert = sum(1 for row in rows if str(row.get("alert_color") or "unknown") == "unknown")
    weak_anchors = sum(
        1
        for row in rows
        if row.get("comment_kind") != "non_criterion_praise"
        if not ((row.get("anchor_before") or {}).get("content_hash"))
        or not ((row.get("anchor_before") or {}).get("features"))
    )
    comments = [plain_text(str(row.get("comment_text") or "")).lower() for row in rows]
    duplicate_comments = sum(count - 1 for count in Counter(comments).values() if count > 1)
    quality_summary = {
        "unknown_criterion": unknown_criterion,
        "unknown_alert": unknown_alert,
        "weak_anchors": weak_anchors,
        "duplicate_comments": duplicate_comments,
    }
    return {
        "project": project,
        "input": str(input_path),
        "output": str(output),
        "notebooks_found": len(manifest),
        "processed": sum(1 for row in manifest if row.get("status") == "ok"),
        "ignored_empty_projects": sum(1 for row in manifest if row.get("status") == "ignored_empty_project"),
        "manual_review_required": len(problem_rows),
        "insertions_extracted": len(rows),
        "alert_counts": dict(alert_counts),
        "comment_kind_counts": dict(kind_counts),
        "criterion_counts": dict(criterion_counts),
        "praise_counts": dict(praise_counts),
        "quality_summary": quality_summary,
        "unknown_criterion": unknown_criterion,
        "weak_anchors": weak_anchors,
        "problem_files": [
            {
                "file": row.get("reviewed_path"),
                "reasons": row.get("manual_review_reasons", []),
            }
            for row in problem_rows
        ],
    }


def _render_report_md(summary: dict[str, Any], manifest: list[dict[str, Any]]) -> str:
    lines = [
        "# Reviewer insertion memory build report",
        "",
        f"Project: `{summary['project']}`",
        f"Input: `{summary['input']}`",
        f"Output: `{summary['output']}`",
        "",
        "## Summary",
        "",
        f"- Notebooks found: {summary['notebooks_found']}",
        f"- Successfully processed: {summary['processed']}",
        f"- Ignored empty projects: {summary.get('ignored_empty_projects', 0)}",
        f"- Manual review required: {summary['manual_review_required']}",
        f"- Reviewer comments extracted: {summary['insertions_extracted']}",
        f"- Alert counts: {json.dumps(summary['alert_counts'], ensure_ascii=False)}",
        f"- Comment kind counts: {json.dumps(summary.get('comment_kind_counts', {}), ensure_ascii=False)}",
        f"- Criterion counts: {json.dumps(summary.get('criterion_counts', {}), ensure_ascii=False)}",
        f"- Praise counts: {json.dumps(summary.get('praise_counts', {}), ensure_ascii=False)}",
        f"- Quality summary: {json.dumps(summary.get('quality_summary', {}), ensure_ascii=False)}",
        "",
    ]
    ignored_rows = [row for row in manifest if row.get("status") == "ignored_empty_project"]
    if ignored_rows:
        lines.extend(["## Ignored empty projects", ""])
        lines.extend(["| File | Reason |", "|---|---|"])
        for row in ignored_rows:
            lines.append(f"| `{row.get('reviewed_path')}` | {row.get('ignored_reason', 'empty_project_review')} |")
        lines.append("")
    lines.extend(["## Manual review required", ""])
    problem_rows = [row for row in manifest if row.get("manual_review_required")]
    if not problem_rows:
        lines.append("No files require manual review.")
    else:
        lines.extend(["| File | Reason |", "|---|---|"])
        for row in problem_rows:
            reasons = ", ".join(row.get("manual_review_reasons", []))
            lines.append(f"| `{row.get('reviewed_path')}` | {reasons} |")
    lines.append("")
    return "\n".join(lines)


def run_with_temp_workdir(**kwargs: Any) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        return build_reviewer_insertion_memory_from_archive(work_dir=Path(tmp), **kwargs)
