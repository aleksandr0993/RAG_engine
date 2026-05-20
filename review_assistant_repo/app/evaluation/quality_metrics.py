from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.llm.service import LLMService, get_llm_service

_SUPPORT_ORDER = {"none": 0, "weak": 1, "medium": 2, "strong": 3}
_COMMENT_SCORE_FIELDS = ("comment_helpfulness_score", "pedagogy_score", "style_match_score", "anchor_score")
_QA_SCORE_FIELDS = ("question_answer_correctness_score", "pedagogy_score")


def _prompt(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "llm" / "prompts" / name).read_text(encoding="utf-8")


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _float01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"true", "yes", "1", "да"}:
            return True
        if norm in {"false", "no", "0", "нет"}:
            return False
    return default


def _support(value: Any) -> str:
    norm = str(value or "").strip().lower()
    return norm if norm in _SUPPORT_ORDER else "none"


def _risk_flags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:120] for item in value if str(item).strip()]


def _support_below(actual: str, minimum: str) -> bool:
    return _SUPPORT_ORDER.get(actual, 0) < _SUPPORT_ORDER.get(minimum, 2)


def normalize_quality_eval(
    parsed: dict[str, Any],
    *,
    metric_type: str,
    quality_score_threshold: float = 0.7,
    min_source_support: str = "medium",
) -> dict[str, Any]:
    evidence_support = _support(parsed.get("evidence_support") or parsed.get("source_support"))
    anchor_ok = _bool(parsed.get("anchor_ok"), default=True)
    no_direct_solution = _bool(parsed.get("no_direct_solution"), default=True)
    out: dict[str, Any] = {
        "quality_eval_status": "ok",
        "comment_helpfulness_score": _float01(parsed.get("comment_helpfulness_score")),
        "pedagogy_score": _float01(parsed.get("pedagogy_score")),
        "no_direct_solution": no_direct_solution,
        "question_answer_correctness_score": _float01(parsed.get("question_answer_correctness_score")),
        "style_match_score": _float01(parsed.get("style_match_score")),
        "anchor_ok": anchor_ok,
        "anchor_score": _float01(parsed.get("anchor_score"), default=1.0 if anchor_ok else 0.0),
        "evidence_support": evidence_support,
        "risk_flags": _risk_flags(parsed.get("risk_flags")),
        "reason": str(parsed.get("reason") or parsed.get("rationale") or "")[:1000],
    }
    if metric_type == "comment":
        out["question_answer_correctness_score"] = None
    if metric_type == "student_qa":
        out["comment_helpfulness_score"] = None
        out["style_match_score"] = None
        out["anchor_score"] = None
    score_fields = _QA_SCORE_FIELDS if metric_type == "student_qa" else _COMMENT_SCORE_FIELDS
    low_scores = [field for field in score_fields if float(out.get(field) or 0.0) < quality_score_threshold]
    needs_human_review = (
        _bool(parsed.get("needs_human_review"), default=False)
        or bool(low_scores)
        or not no_direct_solution
        or not anchor_ok
        or _support_below(evidence_support, min_source_support)
    )
    if not no_direct_solution and "direct_solution" not in out["risk_flags"]:
        out["risk_flags"].append("direct_solution")
    if _support_below(evidence_support, min_source_support) and "weak_or_missing_evidence" not in out["risk_flags"]:
        out["risk_flags"].append("weak_or_missing_evidence")
    if low_scores:
        out["risk_flags"].extend([f"low_{field}" for field in low_scores if f"low_{field}" not in out["risk_flags"]])
    out["needs_human_review"] = needs_human_review
    return out


def unavailable_quality_eval(reason: str) -> dict[str, Any]:
    return {
        "quality_eval_status": reason,
        "needs_human_review": True,
        "risk_flags": [reason],
        "reason": reason,
    }


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
                "text": str(item.get("normalized_text") or item.get("raw_text") or "")[:1800],
            }
            for item in ordered[max(0, current_pos - 1) : current_pos + 2]
        ],
    }


def evaluate_comment_quality(
    row: dict[str, Any],
    *,
    artifacts: list[dict[str, Any]],
    criteria_by_code: dict[str, dict[str, Any]],
    matched_gold: dict[str, Any] | None = None,
    project_memory: dict[str, Any] | None = None,
    llm_service: LLMService | None = None,
    model: str | None = None,
    quality_score_threshold: float = 0.7,
    min_source_support: str = "medium",
) -> dict[str, Any]:
    llm = llm_service or get_llm_service()
    if not llm.is_available:
        return unavailable_quality_eval("llm_unavailable")
    context = {
        "candidate": {
            "criterion_code": row.get("criterion_code"),
            "comment_kind": row.get("comment_kind"),
            "status": row.get("status"),
            "alert_color": row.get("alert_color"),
            "comment_text": row.get("comment_text"),
            "evidence": row.get("evidence") or [],
            "anchor_position_idx": row.get("anchor_position_idx"),
        },
        "criterion": criteria_by_code.get(str(row.get("criterion_code") or "")) or {},
        "anchor_context": _anchor_context(artifacts, row.get("anchor_position_idx")),
        "matched_gold": matched_gold or {},
        "project_memory": project_memory or {},
        "metadata": row.get("metadata") or {},
    }
    prompt = _prompt("comment_quality_judge.txt").replace("{context}", json.dumps(context, ensure_ascii=False)[:14000])
    result = llm.chat([{"role": "user", "content": prompt}], temperature=0.1, model=model, max_tokens=900)
    if not result.ok:
        return unavailable_quality_eval(result.error or "llm_call_failed")
    parsed = extract_json_object(result.text)
    if not parsed:
        return unavailable_quality_eval("unparseable_response")
    return normalize_quality_eval(
        parsed,
        metric_type="comment",
        quality_score_threshold=quality_score_threshold,
        min_source_support=min_source_support,
    )


def _candidate_selected_for_quality(row: dict[str, Any], *, decision_threshold: float) -> bool:
    meta = row.get("metadata") or {}
    return bool(
        row.get("auc_label") == 1
        or float(row.get("keep_score") or 0.0) >= decision_threshold
        or meta.get("llm_judge_keep") is True
        or meta.get("llm_generator_used") is True
    )


def evaluate_comment_rows_quality(
    rows: list[dict[str, Any]],
    *,
    artifacts: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    gold: list[dict[str, Any]] | None = None,
    project_memory: dict[str, Any] | None = None,
    llm_service: LLMService | None = None,
    model: str | None = None,
    max_items: int = 100,
    decision_threshold: float = 0.5,
    quality_score_threshold: float = 0.7,
    min_source_support: str = "medium",
) -> list[dict[str, Any]]:
    criteria_by_code = {str(item.get("code") or ""): item for item in criteria}
    gold_rows = gold or []
    out: list[dict[str, Any]] = []
    evaluated = 0
    for row in rows:
        updated = dict(row)
        if _candidate_selected_for_quality(updated, decision_threshold=decision_threshold) and evaluated < max_items:
            matched_gold = None
            if updated.get("matched_gold_index") is not None:
                try:
                    matched_gold = gold_rows[int(updated["matched_gold_index"])]
                except (IndexError, TypeError, ValueError):
                    matched_gold = None
            updated["quality_eval"] = evaluate_comment_quality(
                updated,
                artifacts=artifacts,
                criteria_by_code=criteria_by_code,
                matched_gold=matched_gold,
                project_memory=project_memory,
                llm_service=llm_service,
                model=model,
                quality_score_threshold=quality_score_threshold,
                min_source_support=min_source_support,
            )
            evaluated += 1
        out.append(updated)
    return out


def evaluate_student_qa_quality(
    row: dict[str, Any],
    *,
    llm_service: LLMService | None = None,
    model: str | None = None,
    quality_score_threshold: float = 0.7,
    min_source_support: str = "medium",
) -> dict[str, Any]:
    llm = llm_service or get_llm_service()
    if not llm.is_available:
        return unavailable_quality_eval("llm_unavailable")
    context = {
        "question": row.get("question"),
        "answer": row.get("answer"),
        "sources": row.get("sources") or [],
        "intent": row.get("intent"),
        "confidence": row.get("confidence"),
        "needs_teacher": row.get("needs_teacher"),
        "context_window": row.get("context_window") or [],
        "topic_tags": row.get("topic_tags") or [],
    }
    prompt = _prompt("student_qa_quality_judge.txt").replace("{context}", json.dumps(context, ensure_ascii=False)[:14000])
    result = llm.chat([{"role": "user", "content": prompt}], temperature=0.1, model=model, max_tokens=900)
    if not result.ok:
        return unavailable_quality_eval(result.error or "llm_call_failed")
    parsed = extract_json_object(result.text)
    if not parsed:
        return unavailable_quality_eval("unparseable_response")
    return normalize_quality_eval(
        parsed,
        metric_type="student_qa",
        quality_score_threshold=quality_score_threshold,
        min_source_support=min_source_support,
    )


def evaluate_student_qa_rows_quality(
    rows: list[dict[str, Any]],
    *,
    llm_service: LLMService | None = None,
    model: str | None = None,
    max_items: int = 100,
    quality_score_threshold: float = 0.7,
    min_source_support: str = "medium",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        updated = dict(row)
        if idx < max_items:
            updated["quality_eval"] = evaluate_student_qa_quality(
                updated,
                llm_service=llm_service,
                model=model,
                quality_score_threshold=quality_score_threshold,
                min_source_support=min_source_support,
            )
        out.append(updated)
    return out


def aggregate_quality_evals(rows: list[dict[str, Any]], *, include_breakdowns: bool = True) -> dict[str, Any]:
    evals = [row.get("quality_eval") for row in rows if isinstance(row.get("quality_eval"), dict)]
    ok = [ev for ev in evals if ev.get("quality_eval_status") == "ok"]

    def avg(field: str) -> float | None:
        vals = [float(ev[field]) for ev in ok if ev.get(field) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    def rate(pred) -> float | None:
        if not ok:
            return None
        return round(sum(1 for ev in ok if pred(ev)) / len(ok), 4)

    summary: dict[str, Any] = {
        "quality_total": len(rows),
        "quality_evaluated": len(evals),
        "quality_ok": len(ok),
        "quality_status_counts": dict(Counter(str(ev.get("quality_eval_status") or "missing") for ev in evals)),
        "average_scores": {
            "comment_helpfulness_score": avg("comment_helpfulness_score"),
            "pedagogy_score": avg("pedagogy_score"),
            "question_answer_correctness_score": avg("question_answer_correctness_score"),
            "style_match_score": avg("style_match_score"),
            "anchor_score": avg("anchor_score"),
        },
        "violation_rates": {
            "needs_human_review_rate": rate(lambda ev: bool(ev.get("needs_human_review"))),
            "direct_solution_rate": rate(lambda ev: ev.get("no_direct_solution") is False),
            "bad_anchor_rate": rate(lambda ev: ev.get("anchor_ok") is False),
            "weak_or_missing_evidence_rate": rate(lambda ev: ev.get("evidence_support") in {"weak", "none"}),
        },
        "evidence_support_counts": dict(Counter(str(ev.get("evidence_support") or "missing") for ev in ok)),
    }
    if include_breakdowns:
        for name, key_fn in {
            "by_project": lambda row: row.get("project") or "unknown",
            "by_criterion_code": lambda row: row.get("criterion_code") or "unknown",
            "by_comment_kind": lambda row: row.get("comment_kind") or "unknown",
            "by_source_stage": lambda row: (row.get("metadata") or {}).get("source_stage") or "unknown",
        }.items():
            buckets: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                if isinstance(row.get("quality_eval"), dict):
                    buckets.setdefault(str(key_fn(row)), []).append(row)
            summary[name] = {bucket: aggregate_quality_evals(items, include_breakdowns=False) for bucket, items in sorted(buckets.items())}
    return summary


def render_quality_summary_markdown(summary: dict[str, Any]) -> list[str]:
    avg = summary.get("average_scores") or {}
    rates = summary.get("violation_rates") or {}
    return [
        "## Quality Metrics",
        "",
        f"- Quality evaluated: {summary.get('quality_evaluated')} / {summary.get('quality_total')}",
        f"- Quality statuses: {json.dumps(summary.get('quality_status_counts') or {}, ensure_ascii=False)}",
        f"- Helpfulness / pedagogy / QA correctness: {avg.get('comment_helpfulness_score')} / "
        f"{avg.get('pedagogy_score')} / {avg.get('question_answer_correctness_score')}",
        f"- Style match / anchor score: {avg.get('style_match_score')} / {avg.get('anchor_score')}",
        f"- Needs human review / direct solution / bad anchor / weak evidence: "
        f"{rates.get('needs_human_review_rate')} / {rates.get('direct_solution_rate')} / "
        f"{rates.get('bad_anchor_rate')} / {rates.get('weak_or_missing_evidence_rate')}",
        f"- Evidence support: {json.dumps(summary.get('evidence_support_counts') or {}, ensure_ascii=False)}",
        "",
    ]
