"""Pydantic-схема структурированного ревью (v1) и гибридного ответа v2."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


def strip_json_fence(raw: str) -> str:
    """Убирает обёртку ```json ... ``` если модель её вернула."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


class StrengthItem(BaseModel):
    text: str = Field(min_length=1)
    evidence_quote: str | None = None


class IssueItem(BaseModel):
    text: str = Field(min_length=1)
    severity: str
    evidence_quote: str | None = None

    @field_validator("severity")
    @classmethod
    def severity_ok(cls, v: str) -> str:
        allowed = {"low", "medium", "high"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v


class RecommendationItem(BaseModel):
    text: str = Field(min_length=1)
    actionable: bool


class ReviewOutput(BaseModel):
    """JSON-ответ ассистента проверки ДЗ (v1, обратная совместимость)."""

    strengths: list[StrengthItem] = Field(default_factory=list)
    issues: list[IssueItem] = Field(default_factory=list)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    score_justification: str = Field(min_length=1)
    overall_score: float
    rubric_scores: dict[str, int | float | str] | None = None

    def model_dump_json_compact(self) -> str:
        return self.model_dump_json(exclude_none=True)


# --- v2: гибридный ответ (студент + ревьюер + факторы) ---

FACTOR_IDS = frozenset({"submission", "revision_history", "student_profile"})


class FactorAnalysisItem(BaseModel):
    factor_id: str
    how_used: str = Field(min_length=1)
    impact_on_score: str | None = None

    @field_validator("factor_id")
    @classmethod
    def factor_id_ok(cls, v: str) -> str:
        if v not in FACTOR_IDS:
            raise ValueError(f"factor_id must be one of {sorted(FACTOR_IDS)}")
        return v


class StudentFeedback(BaseModel):
    """Развёрнутый ответ для студента."""

    summary: str = Field(min_length=1)
    strengths: list[StrengthItem] = Field(default_factory=list)
    issues: list[IssueItem] = Field(default_factory=list)
    recommendations: list[RecommendationItem] = Field(default_factory=list)


class ReviewerReport(BaseModel):
    """Внутренний разбор для ревьюера."""

    summary: str = Field(min_length=1)
    risk_assessment: str = Field(min_length=1)
    score_justification: str = Field(min_length=1)
    rubric_scores: dict[str, int | float | str] | None = None


class ReviewOutputV2(BaseModel):
    """Один JSON: студент + ревьюер + учёт факторов."""

    student_feedback: StudentFeedback
    reviewer_report: ReviewerReport
    factor_analysis: list[FactorAnalysisItem] = Field(min_length=1)
    overall_score: float


def parse_review_json(raw: str) -> ReviewOutput:
    data = json.loads(strip_json_fence(raw))
    return ReviewOutput.model_validate(data)


def try_parse_review_json(raw: str) -> tuple[ReviewOutput | None, str | None]:
    try:
        return parse_review_json(raw), None
    except (json.JSONDecodeError, ValueError) as e:
        return None, str(e)


def parse_review_json_v2(raw: str) -> ReviewOutputV2:
    data = json.loads(strip_json_fence(raw))
    return ReviewOutputV2.model_validate(data)


def try_parse_review_json_v2(raw: str) -> tuple[ReviewOutputV2 | None, str | None]:
    try:
        return parse_review_json_v2(raw), None
    except (json.JSONDecodeError, ValueError) as e:
        return None, str(e)


def parse_review_json_auto(raw: str) -> tuple[ReviewOutput | ReviewOutputV2, str]:
    """Пробует v2, затем v1. Возвращает (объект, 'v2'|'v1')."""
    text = strip_json_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(str(e)) from e
    if isinstance(data, dict) and "student_feedback" in data and "reviewer_report" in data:
        return ReviewOutputV2.model_validate(data), "v2"
    return ReviewOutput.model_validate(data), "v1"


class RawHomeworkRecord(BaseModel):
    """Одна строка сырых данных до очистки и разбиения."""

    id: str
    student_id: str
    assignment_id: str
    submission_text: str
    review_text: str
    overall_score: float
    task_type: str | None = None
    language: str = "ru"
    reviewer_id: str | None = None
    assignment_prompt: str | None = None
    rubric_text: str | None = None
    rubric_scores: dict[str, int | float | str] | None = None
    revision_history: str | None = None
    student_profile: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedRecord(BaseModel):
    """Запись после санитизации (готова к split и SFT)."""

    id: str
    student_id: str
    assignment_id: str
    submission_text: str
    review_text: str
    overall_score: float
    task_type: str | None = None
    language: str = "ru"
    reviewer_id: str | None = None
    assignment_prompt: str | None = None
    rubric_text: str | None = None
    rubric_scores: dict[str, int | float | str] | None = None
    revision_history: str | None = None
    student_profile: str | None = None
    split: str | None = None  # train | val | test | hard
    extra: dict[str, Any] = Field(default_factory=dict)
