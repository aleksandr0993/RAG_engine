"""Метрики: MAE по оценке, rubric, actionable, валидность JSON; расширения для v2."""

from __future__ import annotations

from dataclasses import dataclass, field

from homework_reviewer_llm.schema import (
    FACTOR_IDS,
    ReviewOutput,
    ReviewOutputV2,
    try_parse_review_json,
    try_parse_review_json_v2,
)


@dataclass
class AggregateMetrics:
    n: int = 0
    json_valid: int = 0
    score_mae_sum: float = 0.0
    score_n: int = 0
    rubric_mae_sum: float = 0.0
    rubric_n: int = 0
    rubric_exact_sum: float = 0.0
    rubric_exact_denom: int = 0
    actionable_true: int = 0
    actionable_total: int = 0

    def update(self, gold: ReviewOutput, pred: ReviewOutput | None, pred_parsed: bool) -> None:
        self.n += 1
        if pred_parsed and pred is not None:
            self.json_valid += 1
            self.score_n += 1
            self.score_mae_sum += abs(pred.overall_score - gold.overall_score)

            g_r = gold.rubric_scores or {}
            p_r = pred.rubric_scores or {}
            common = set(g_r) & set(p_r)
            for k in common:
                gv, pv = g_r[k], p_r[k]
                if isinstance(gv, (int, float)) and isinstance(pv, (int, float)):
                    self.rubric_n += 1
                    self.rubric_mae_sum += abs(float(pv) - float(gv))
                else:
                    self.rubric_exact_denom += 1
                    if str(gv).strip() == str(pv).strip():
                        self.rubric_exact_sum += 1

            for rec in pred.recommendations:
                self.actionable_total += 1
                if rec.actionable:
                    self.actionable_true += 1

    def summary(self) -> dict:
        return {
            "format": "v1",
            "n": self.n,
            "json_valid_rate": self.json_valid / self.n if self.n else 0.0,
            "score_mae": self.score_mae_sum / self.score_n if self.score_n else None,
            "rubric_mae": self.rubric_mae_sum / self.rubric_n if self.rubric_n else None,
            "rubric_exact_match_rate": (
                self.rubric_exact_sum / self.rubric_exact_denom if self.rubric_exact_denom else None
            ),
            "actionable_rate": (
                self.actionable_true / self.actionable_total if self.actionable_total else None
            ),
        }


@dataclass
class AggregateMetricsV2:
    n: int = 0
    json_valid: int = 0
    score_mae_sum: float = 0.0
    score_n: int = 0
    rubric_mae_sum: float = 0.0
    rubric_n: int = 0
    rubric_exact_sum: float = 0.0
    rubric_exact_denom: int = 0
    actionable_true: int = 0
    actionable_total: int = 0
    factor_full_cover: int = 0
    dual_audience_ok: int = 0

    def update(self, gold: ReviewOutputV2, pred: ReviewOutputV2 | None, pred_parsed: bool) -> None:
        self.n += 1
        if not pred_parsed or pred is None:
            return
        self.json_valid += 1
        self.score_n += 1
        self.score_mae_sum += abs(pred.overall_score - gold.overall_score)

        g_r = gold.reviewer_report.rubric_scores or {}
        p_r = pred.reviewer_report.rubric_scores or {}
        common = set(g_r) & set(p_r)
        for k in common:
            gv, pv = g_r[k], p_r[k]
            if isinstance(gv, (int, float)) and isinstance(pv, (int, float)):
                self.rubric_n += 1
                self.rubric_mae_sum += abs(float(pv) - float(gv))
            else:
                self.rubric_exact_denom += 1
                if str(gv).strip() == str(pv).strip():
                    self.rubric_exact_sum += 1

        for rec in pred.student_feedback.recommendations:
            self.actionable_total += 1
            if rec.actionable:
                self.actionable_true += 1

        pred_factors = {f.factor_id for f in pred.factor_analysis}
        if FACTOR_IDS.issubset(pred_factors):
            self.factor_full_cover += 1

        if (
            len(pred.student_feedback.summary.strip()) >= 5
            and len(pred.reviewer_report.summary.strip()) >= 5
        ):
            self.dual_audience_ok += 1

    def summary(self) -> dict:
        return {
            "format": "v2",
            "n": self.n,
            "json_valid_rate": self.json_valid / self.n if self.n else 0.0,
            "score_mae": self.score_mae_sum / self.score_n if self.score_n else None,
            "rubric_mae": self.rubric_mae_sum / self.rubric_n if self.rubric_n else None,
            "rubric_exact_match_rate": (
                self.rubric_exact_sum / self.rubric_exact_denom if self.rubric_exact_denom else None
            ),
            "actionable_rate": (
                self.actionable_true / self.actionable_total if self.actionable_total else None
            ),
            "factor_coverage_rate": self.factor_full_cover / self.json_valid if self.json_valid else 0.0,
            "dual_audience_completeness": (
                self.dual_audience_ok / self.json_valid if self.json_valid else 0.0
            ),
        }


def evaluate_pairs(
    gold_outputs: list[ReviewOutput],
    pred_raws: list[str],
) -> AggregateMetrics:
    if len(gold_outputs) != len(pred_raws):
        raise ValueError("gold_outputs and pred_raws must have same length")
    m = AggregateMetrics()
    for gold, raw in zip(gold_outputs, pred_raws, strict=True):
        pred, _err = try_parse_review_json(raw)
        m.update(gold, pred, pred is not None)
    return m


def evaluate_pairs_v2(
    gold_outputs: list[ReviewOutputV2],
    pred_raws: list[str],
) -> AggregateMetricsV2:
    if len(gold_outputs) != len(pred_raws):
        raise ValueError("gold_outputs and pred_raws must have same length")
    m = AggregateMetricsV2()
    for gold, raw in zip(gold_outputs, pred_raws, strict=True):
        pred, _err = try_parse_review_json_v2(raw)
        m.update(gold, pred, pred is not None)
    return m
