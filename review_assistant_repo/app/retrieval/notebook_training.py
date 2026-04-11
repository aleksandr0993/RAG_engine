"""
Build training / retrieval rows from master-review Jupyter notebooks.

Uses text markers (see app.parsers.notebook) to separate reviewer, middle reviewer, and student.
Output is not ground truth — only material for RAG or external fine-tuning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import nbformat

from app.parsers.notebook import (
    NotebookParser,
    infer_notebook_comment_role,
    is_review_role_cell,
)


def _prior_work_context(nb: Any, cell_idx: int) -> str:
    """Nearest substantive cell before `cell_idx`: explicit student comment or substantive code/markdown."""
    for j in range(cell_idx - 1, -1, -1):
        cell = nb.cells[j]
        try:
            src = cell.source
        except AttributeError:
            src = cell.get("source", "")
        if not isinstance(src, str):
            src = "".join(src) if isinstance(src, list) else str(src)
        role = infer_notebook_comment_role(src)
        if is_review_role_cell(role):
            continue
        if role == "student":
            return src.strip()[:4000]
        ct = cell.get("cell_type", "")
        if role == "unknown" and ct in ("code", "markdown") and len(src.strip()) >= 40:
            return src.strip()[:4000]
    return ""


def extract_rows_from_ipynb(
    ipynb_path: Path | str,
    *,
    source_project: str,
    source_notebook: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Parse one .ipynb and return (runtime_corpus_rows, finetune_rows).

    runtime_corpus_rows: suitable for PROJECT_REVIEW_TRAINING JSONL (student rows omitted).
    finetune_rows: all roles including student for external fine-tuning / analysis.
    """
    path = Path(ipynb_path)
    nb_name = source_notebook or path.name
    parser = NotebookParser()
    artifacts, _nbdict = parser.parse(str(path))
    nb = nbformat.read(str(path), as_version=4)

    runtime: list[dict[str, Any]] = []
    finetune: list[dict[str, Any]] = []

    for idx, cell in enumerate(nb.cells):
        try:
            source = cell.source
        except AttributeError:
            source = cell.get("source", "")
        if not isinstance(source, str):
            source = "".join(source) if isinstance(source, list) else str(source)
        role = infer_notebook_comment_role(source)
        if role == "unknown":
            continue

        art = artifacts[idx] if idx < len(artifacts) else None
        section = (art.section_name if art else None) or ""
        student_ctx = _prior_work_context(nb, idx)
        eid = f"{source_project}_{path.stem}_{idx}"

        text = source.strip()
        try:
            meta = cell.metadata
        except AttributeError:
            meta = (cell.get("metadata") if isinstance(cell, dict) else None) or {}
        if not isinstance(meta, dict):
            meta = {}
        crit = str(meta.get("criterion_code") or "")
        base = {
            "example_id": eid,
            "criterion_code": crit,
            "section_name": section,
            "text": text,
            "author_role": role,
            "source_project": source_project,
            "source_notebook": nb_name,
            "student_context": student_ctx,
            "tags": ["master_review", role],
        }

        finetune.append(
            {
                "task": "review_dialogue",
                "example_id": eid,
                "author_role": role,
                "student_context": student_ctx,
                "section_name": section,
                "criterion_code": base["criterion_code"],
                "review_text": text,
                "source_project": source_project,
                "source_notebook": nb_name,
            }
        )

        if role != "student":
            runtime.append(dict(base))

    return runtime, finetune


def merge_write_jsonl(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
