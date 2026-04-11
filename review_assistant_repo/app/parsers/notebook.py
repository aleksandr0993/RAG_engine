from __future__ import annotations

import re
from typing import Literal

import nbformat

from app.parsers.base import ParsedArtifact
from app.services.section_builder import assign_sections_linear

REVIEWER_MARKER = "Комментарий ревьюера"
MIDDLE_REVIEWER_MARKER = "Комментарий мидл-ревьюера"
MIDDLE_REVIEWER_MARKER_ALT = "Комментарий мидл ревьюера"
STUDENT_MARKER = "Комментарий студента"

CommentRole = Literal["reviewer", "middle_reviewer", "student", "unknown"]

_PLOT_PAT = re.compile(
    r"\.plot\(|plt\.|matplotlib|seaborn|sns\.|hist\(|bar\(|scatter\(|boxplot|heatmap",
    re.IGNORECASE,
)


def infer_notebook_comment_role(source: str) -> CommentRole:
    """
    Detect role of a notebook cell from Russian text markers (master-review workflow).
    Order: senior reviewer, middle reviewer, then student.
    """
    if REVIEWER_MARKER in source:
        return "reviewer"
    if MIDDLE_REVIEWER_MARKER in source or MIDDLE_REVIEWER_MARKER_ALT in source:
        return "middle_reviewer"
    if STUDENT_MARKER in source:
        return "student"
    return "unknown"


def is_review_role_cell(role: CommentRole) -> bool:
    return role in ("reviewer", "middle_reviewer")


class NotebookParser:
    def parse(self, notebook_path: str) -> tuple[list[ParsedArtifact], dict]:
        notebook = nbformat.read(notebook_path, as_version=4)
        artifacts: list[ParsedArtifact] = []

        for idx, cell in enumerate(notebook.cells):
            cell_type = cell.get("cell_type", "")
            source = cell.get("source", "")
            outputs_text = ""

            if cell_type == "code":
                output_fragments = []
                for output in cell.get("outputs", []):
                    text = output.get("text")
                    if isinstance(text, list):
                        output_fragments.append("".join(text))
                    elif isinstance(text, str):
                        output_fragments.append(text)

                    data = output.get("data", {})
                    text_plain = data.get("text/plain")
                    if isinstance(text_plain, list):
                        output_fragments.append("".join(text_plain))
                    elif isinstance(text_plain, str):
                        output_fragments.append(text_plain)

                outputs_text = "\n".join(output_fragments).strip()

            normalized = source.strip()
            if outputs_text:
                normalized = f"{normalized}\n\n[OUTPUT]\n{outputs_text}"

            section_name = self._infer_section(source)
            has_plot = bool(_PLOT_PAT.search(source)) or bool(_PLOT_PAT.search(outputs_text))
            interp_hint = bool(cell_type == "markdown" and len(source.strip()) > 80)
            role = infer_notebook_comment_role(source)
            artifacts.append(
                ParsedArtifact(
                    artifact_type=f"{cell_type}_cell",
                    position_idx=idx,
                    raw_text=source,
                    normalized_text=normalized,
                    section_name=section_name,
                    metadata={
                        "has_outputs": bool(outputs_text),
                        "has_plot_code": has_plot,
                        "markdown_interpretation_hint": interp_hint,
                        "comment_role": role,
                        "is_reviewer_comment": role == "reviewer",
                        "is_middle_reviewer_comment": role == "middle_reviewer",
                        "is_student_comment": role == "student",
                    },
                )
            )

        assign_sections_linear(artifacts)
        return artifacts, notebook

    def clean_notebook(self, notebook: dict) -> dict:
        filtered = []
        for cell in notebook["cells"]:
            try:
                source = cell.source
            except AttributeError:
                source = cell.get("source", "")
            if not isinstance(source, str):
                source = "".join(source) if isinstance(source, list) else str(source)
            role = infer_notebook_comment_role(source)
            if is_review_role_cell(role):
                continue
            if role == "student" and "<div" in source:
                continue
            filtered.append(cell)
        notebook["cells"] = filtered
        return notebook

    def _infer_section(self, source: str) -> str | None:
        src = source.lower()
        if "введение" in src or "цель проекта" in src:
            return "intro"
        if "eda" in src or "исследователь" in src:
            return "eda"
        if "вывод" in src or "итог" in src:
            return "conclusion"
        if "гипотез" in src:
            return "hypothesis"
        return None
