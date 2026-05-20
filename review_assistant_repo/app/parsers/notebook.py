from __future__ import annotations

import re
from typing import Any, Literal

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
_REVIEW_ALERT_PAT = re.compile(
    r'class\s*=\s*["\'][^"\']*alert(?:\s+alert-block)?\s+[^"\']*alert-(?:success|info|danger|warning)',
    re.IGNORECASE,
)
_REVIEW_ALERT_LABEL_PAT = re.compile(
    r"<b>\s*(?:успех|совет|ошибка|замечание|рекомендац(?:ия|ии)|комментарий ревьюера|nb|важно)\s*:?",
    re.IGNORECASE,
)
_REVIEWER_INTRO_PAT = re.compile(
    r"сегодня я проверю твой проект|комментарии будут.+alert|пожалуйста,\s*не удаляй комментарии ревьюера",
    re.IGNORECASE | re.DOTALL,
)
_CUSTOM_REVIEW_BOX_PAT = re.compile(
    r"<!--\s*[✅⚠️⛔❌🚩\s]+-->|border\s*:\s*2px\s+solid\s+black|итоги\s+ревью",
    re.IGNORECASE,
)
_CUSTOM_REVIEW_LABEL_PAT = re.compile(
    r"#{2,6}\s*(?:✅|⚠️?|⛔|❌|🚩)|"
    r"(?:^|\s|>)\s*(?:✅|⚠️?|⛔|❌|🚩)\s+"
    r"(?:правильно|отлич|молодец|хорош|лучше|важно|согласен|предупреждение|данные|категоризац)",
    re.IGNORECASE | re.MULTILINE,
)
_PRACTICUM_INSTRUCTION_PAT = re.compile(
    r"\b(?:сделайте|отметьте|проведите|посчитайте|изучите|напишите|обработайте|разделите|выделите|проверьте|используйте|не забудьте)\b",
    re.IGNORECASE,
)
_PRACTICUM_HINT_FONT_PAT = re.compile(r"<font\b[^>]*color=['\"]#?777778['\"][^>]*>.*?</font>", re.IGNORECASE | re.DOTALL)
_STUDENT_WORK_PAT = re.compile(
    r"\b(?:цель проекта|в датасете|промежуточный вывод|общий вывод|в ходе проекта|были обнаружены|были исправлены)\b",
    re.IGNORECASE,
)
_QUESTION_PAT = re.compile(r"\?|(?:как|почему|зачем|что делать|можно ли|нужно ли|ошибк|не понимаю|подскаж)", re.IGNORECASE)
_TOPIC_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("metrics", re.compile(r"roc|auc|f1|precision|recall|accuracy|метрик", re.IGNORECASE)),
    ("sql", re.compile(r"\bsql\b|select|join|group by|having|window", re.IGNORECASE)),
    ("pandas", re.compile(r"pandas|dataframe|groupby|fillna|merge|pivot|astype", re.IGNORECASE)),
    ("visualization", re.compile(r"plot|plt|seaborn|matplotlib|график|визуал", re.IGNORECASE)),
    ("hypothesis", re.compile(r"гипотез|p-value|ttest|статист", re.IGNORECASE)),
    ("project_requirements", re.compile(r"критери|проект|зач[её]т|ревью|требован", re.IGNORECASE)),
]


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
    if _REVIEWER_INTRO_PAT.search(source):
        return "reviewer"
    if _REVIEW_ALERT_PAT.search(source) and _REVIEW_ALERT_LABEL_PAT.search(source):
        return "reviewer"
    if _CUSTOM_REVIEW_BOX_PAT.search(source) and _CUSTOM_REVIEW_LABEL_PAT.search(source):
        return "reviewer"
    return "unknown"


def is_review_role_cell(role: CommentRole) -> bool:
    return role in ("reviewer", "middle_reviewer")


def is_practicum_instruction_cell(source: str) -> bool:
    if not source or not _PRACTICUM_INSTRUCTION_PAT.search(source):
        return False
    if _STUDENT_WORK_PAT.search(source):
        return False
    stripped = source.strip()
    return stripped.startswith(("-", "---", "#")) or "\n-" in stripped


def strip_practicum_hints(source: str) -> str:
    return _PRACTICUM_HINT_FONT_PAT.sub("", source).strip()


def extract_student_question_text(source: str) -> str:
    text = (source or "").replace(STUDENT_MARKER, "", 1).strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def infer_student_question_intent(text: str) -> str:
    t = (text or "").lower()
    if any(x in t for x in ["дедлайн", "срок", "когда сда", "админ"]):
        return "deadline/admin"
    if any(x in t for x in ["ошибка", "traceback", "не запуска", "не работает", "keyerror", "valueerror"]):
        return "debug"
    if any(x in t for x in ["критери", "зачет", "зачёт", "ревью", "достаточно"]):
        return "rubric_confusion"
    if any(x in t for x in ["шаг", "этап", "дальше", "следующ"]):
        return "project_step"
    if any(x in t for x in ["установ", "верси", "библиотек", "импорт"]):
        return "tooling"
    if _QUESTION_PAT.search(t):
        return "concept"
    return "needs_teacher"


def infer_student_question_topic_tags(text: str) -> list[str]:
    tags = [name for name, pat in _TOPIC_PATTERNS if pat.search(text or "")]
    return tags or ["general"]


class NotebookParser:
    def parse(self, notebook_path: str, *, strip_review_comments: bool = False) -> tuple[list[ParsedArtifact], dict]:
        notebook = nbformat.read(notebook_path, as_version=4)
        if strip_review_comments:
            notebook = self.clean_notebook(notebook)
        return self.parse_notebook(notebook)

    def parse_notebook(self, notebook: Any) -> tuple[list[ParsedArtifact], dict]:
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

            normalized = strip_practicum_hints(source) if cell_type == "markdown" else source.strip()
            if outputs_text:
                normalized = f"{normalized}\n\n[OUTPUT]\n{outputs_text}"

            section_name = self._infer_section(source)
            has_plot = bool(_PLOT_PAT.search(source)) or bool(_PLOT_PAT.search(outputs_text))
            interp_hint = bool(cell_type == "markdown" and len(source.strip()) > 80)
            role = infer_notebook_comment_role(source)
            is_instruction = cell_type == "markdown" and is_practicum_instruction_cell(source)
            student_question = extract_student_question_text(source) if role == "student" else ""
            is_student_question = bool(role == "student" and student_question and _QUESTION_PAT.search(student_question))
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
                        "is_student_question": is_student_question,
                        "student_question": student_question if is_student_question else "",
                        "question_cell_idx": idx if is_student_question else None,
                        "student_question_intent": infer_student_question_intent(student_question) if is_student_question else "",
                        "topic_tags": infer_student_question_topic_tags(student_question) if is_student_question else [],
                        "is_practicum_instruction": is_instruction,
                    },
                )
            )

        for i, artifact in enumerate(artifacts):
            if not artifact.metadata.get("is_student_question"):
                continue
            ctx: list[dict[str, Any]] = []
            for neighbor in artifacts[max(0, i - 3) : min(len(artifacts), i + 4)]:
                if neighbor is artifact:
                    continue
                if neighbor.metadata.get("is_reviewer_comment") or neighbor.metadata.get("is_middle_reviewer_comment"):
                    continue
                ctx.append(
                    {
                        "position_idx": neighbor.position_idx,
                        "artifact_type": neighbor.artifact_type,
                        "section_name": neighbor.section_name,
                        "text": (neighbor.normalized_text or neighbor.raw_text or "")[:900],
                    }
                )
            artifact.metadata["question_context_window"] = ctx

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
