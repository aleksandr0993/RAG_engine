from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.config import get_settings
from app.models import CriterionResult


def build_criteria_execution_summary_from_merged(merged_results: list[dict[str, Any]]) -> dict:
    by_status = Counter(m.get("status") for m in merged_results)
    by_severity = Counter(m.get("severity") for m in merged_results)
    by_stage: dict[str, int] = defaultdict(int)
    by_stage_status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    low_confidence = 0
    manual_review = 0
    min_c = get_settings().finding_min_confidence_for_required_fail
    for m in merged_results:
        meta = m.get("metadata") or {}
        stage = meta.get("source_stage") or "unspecified"
        by_stage[stage] += 1
        st = str(m.get("status") or "unknown")
        by_stage_status[stage][st] += 1
        conf = m.get("confidence")
        if conf is not None and conf < min_c:
            low_confidence += 1
        if meta.get("manual_review_suggested") or meta.get("policy_low_confidence_downgrade"):
            manual_review += 1
    return {
        "total": len(merged_results),
        "by_status": dict(by_status),
        "by_severity": dict(by_severity),
        "by_source_stage": dict(by_stage),
        "by_source_stage_status": {k: dict(v) for k, v in by_stage_status.items()},
        "low_confidence_findings_approx": low_confidence,
        "manual_review_flagged_findings_approx": manual_review,
    }


def build_criteria_execution_summary(rows: list[CriterionResult]) -> dict:
    """Roll up criterion results by status, severity, and source_stage (from metadata_json)."""
    by_status = Counter(r.status for r in rows)
    by_severity = Counter(r.severity for r in rows)
    by_stage: dict[str, int] = defaultdict(int)
    for r in rows:
        stage = (r.metadata_json or {}).get("source_stage") or "unspecified"
        by_stage[stage] += 1
    return {
        "total": len(rows),
        "by_status": dict(by_status),
        "by_severity": dict(by_severity),
        "by_source_stage": dict(by_stage),
    }
