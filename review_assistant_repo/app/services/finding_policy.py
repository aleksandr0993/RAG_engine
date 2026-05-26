from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.analyzers.rule_matching import find_rule_match

# Strict reporting stages (hybrid without LLM is still "semantic" at criterion level).
SOURCE_STAGES: frozenset[str] = frozenset({"rule", "semantic", "visual", "llm"})


def normalize_source_stage(
    raw: str | None,
    detection_mode: str | None = None,
) -> Literal["rule", "semantic", "visual", "llm", "unspecified"]:
    """
    Coerce analyzer metadata to a known stage for aggregation and filters.
    """
    if raw in SOURCE_STAGES:
        return raw  # type: ignore[return-value]
    if raw in (None, "", "unspecified"):
        if detection_mode == "rule":
            return "rule"
        if detection_mode == "visual":
            return "visual"
        if detection_mode == "hybrid":
            return "semantic"
        return "unspecified"
    return "unspecified"


def coerce_source_stage_metadata(
    metadata: dict[str, Any],
    detection_mode: str | None,
) -> dict[str, Any]:
    """Set ``source_stage`` to a valid enum value; stash unknown raw in ``source_stage_raw``."""
    meta = dict(metadata)
    raw = meta.get("source_stage")
    normalized = normalize_source_stage(raw if isinstance(raw, str) else None, detection_mode)
    if normalized == "unspecified" and raw and str(raw) not in SOURCE_STAGES:
        meta.setdefault("source_stage_raw", str(raw))
        meta["source_stage"] = "semantic"
    elif normalized != "unspecified":
        meta["source_stage"] = normalized
    else:
        meta["source_stage"] = "semantic"
    return meta


@dataclass
class PolicyOutcome:
    status: str
    confidence: float | None
    metadata: dict[str, Any]


@dataclass
class EvidenceGateOutcome:
    status: str
    confidence: float | None
    metadata: dict[str, Any]
    evidence: list[dict[str, Any]]
    anchor_position_idx: int | None


def apply_low_confidence_and_quality_policy(
    *,
    status: str,
    severity: str,
    confidence: float | None,
    metadata: dict[str, Any],
    criterion_code: str,
    min_confidence_for_required_fail: float,
    enabled: bool = True,
) -> PolicyOutcome:
    """
    Downgrade required ``fail`` when confidence is below threshold (avoid false revise).
    Flags manual review for required unknown and for downgrades.
    """
    meta = dict(metadata)
    if not enabled:
        return PolicyOutcome(status=status, confidence=confidence, metadata=meta)

    new_status = status
    new_conf = confidence

    if severity == "required" and status == "fail":
        if confidence is not None and confidence < min_confidence_for_required_fail:
            new_status = "warn"
            meta["policy_low_confidence_downgrade"] = True
            meta["policy_min_confidence_threshold"] = min_confidence_for_required_fail
            meta["manual_review_suggested"] = True
            mr = list(meta.get("manual_review_reasons") or [])
            mr.append(f"{criterion_code}:required_fail_below_confidence({confidence})")
            meta["manual_review_reasons"] = mr

    if severity == "required" and status == "unknown":
        meta["manual_review_suggested"] = True
        mr = list(meta.get("manual_review_reasons") or [])
        mr.append(f"{criterion_code}:required_unknown")
        meta["manual_review_reasons"] = mr

    return PolicyOutcome(status=new_status, confidence=new_conf, metadata=meta)


def apply_required_fail_evidence_gate(
    *,
    status: str,
    severity: str,
    confidence: float | None,
    metadata: dict[str, Any],
    criterion: dict[str, Any],
    artifacts: list[dict[str, Any]],
    evidence: list[dict[str, Any]] | None,
    anchor_position_idx: int | None,
    enabled: bool = True,
) -> EvidenceGateOutcome:
    """
    Prevent required fail from producing a red finding when no concrete evidence was found.
    Rule criteria get one whole-notebook verification pass before downgrade.
    """
    meta = dict(metadata)
    current_evidence = list(evidence or [])
    criterion_code = str(criterion.get("code") or meta.get("criterion_code") or "unknown")
    if not enabled or severity != "required" or status != "fail" or current_evidence:
        return EvidenceGateOutcome(
            status=status,
            confidence=confidence,
            metadata=meta,
            evidence=current_evidence,
            anchor_position_idx=anchor_position_idx,
        )

    meta["policy_required_fail_without_evidence"] = True
    meta["manual_review_suggested"] = True
    reasons = list(meta.get("manual_review_reasons") or [])
    reason = f"{criterion_code}:required_fail_without_evidence"
    if reason not in reasons:
        reasons.append(reason)
    meta["manual_review_reasons"] = reasons

    if criterion.get("detection_mode", "rule") == "rule":
        match = find_rule_match(artifacts, criterion)
        if match is not None:
            meta["policy_whole_notebook_verification"] = "pass_found"
            return EvidenceGateOutcome(
                status="pass",
                confidence=max(confidence or 0.0, 0.98),
                metadata=meta,
                evidence=list(match.get("evidence") or []),
                anchor_position_idx=match.get("anchor_position_idx"),
            )

    meta["policy_whole_notebook_verification"] = "no_evidence_downgraded"
    return EvidenceGateOutcome(
        status="warn",
        confidence=confidence,
        metadata=meta,
        evidence=current_evidence,
        anchor_position_idx=anchor_position_idx,
    )


def build_manual_review_summary(merged_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate project-level manual review hints from per-criterion metadata."""
    reasons: list[str] = []
    for row in merged_results:
        meta = row.get("metadata") or {}
        for r in meta.get("manual_review_reasons") or []:
            if r and r not in reasons:
                reasons.append(r)
    suggested = any((row.get("metadata") or {}).get("manual_review_suggested") for row in merged_results)
    needed = bool(reasons) or suggested
    return {
        "manual_review_needed": needed,
        "manual_review_reasons": reasons[:50],
        "low_confidence_downgrade_count": sum(
            1 for row in merged_results if (row.get("metadata") or {}).get("policy_low_confidence_downgrade")
        ),
        "required_unknown_count": sum(
            1
            for row in merged_results
            if row.get("severity") == "required" and row.get("status") == "unknown"
        ),
    }
