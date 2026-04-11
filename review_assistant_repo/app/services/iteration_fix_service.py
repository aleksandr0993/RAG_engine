from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import IterationIssueResolution, ProjectLineage, ReviewFindingSnapshot
from app.services.iteration_metadata_quality import (
    ITERATION_FIX_POLICY_VERSION,
    normalize_iteration_issue_resolution_detail,
)
from app.services.review_snapshot import get_latest_snapshot_batch, list_open_issues_from_batch


def group_merged_results_by_code(merged_results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """All merged rows per criterion (order preserved; duplicates rare but supported)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for m in merged_results:
        code = str(m.get("criterion_code") or "")
        if code:
            out.setdefault(code, []).append(m)
    return out


def _evidence_plain(ev: list[Any]) -> str:
    parts: list[str] = []
    for item in ev or []:
        if isinstance(item, dict):
            ex = item.get("excerpt") or item.get("text") or item.get("normalized_text") or ""
            parts.append(str(ex))
        else:
            parts.append(str(item))
    return " ".join(parts).lower()


def _evidence_tokens(ev: list[Any]) -> set[str]:
    text = _evidence_plain(ev)
    return {w for w in re.split(r"[^\w]+", text, flags=re.UNICODE) if len(w) > 2}


def evidence_overlap_score(ev_a: list[Any], ev_b: list[Any]) -> float:
    """Jaccard on word tokens (length > 2); used only to break ties between candidates."""
    ta = _evidence_tokens(ev_a)
    tb = _evidence_tokens(ev_b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return float(inter) / float(union) if union else 0.0


def _anchor_distance(parent_anchor: int | None, merged: dict[str, Any]) -> int:
    """Lower is better; missing child anchor penalized when parent has anchor."""
    c = merged.get("anchor_position_idx")
    if c is not None:
        c = int(c)
    if parent_anchor is not None:
        pa = int(parent_anchor)
        if c is None:
            return 1_000_000
        return abs(pa - c)
    return 0


def match_merged_to_snapshot(
    snap: ReviewFindingSnapshot,
    merged_by_code: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """
    Pick the current merged row that best corresponds to this parent snapshot.
    Disambiguation: anchor cell index first, then evidence token overlap.
    """
    code = snap.criterion_code
    cands = merged_by_code.get(code, [])
    if not cands:
        return None, {"method": "none", "candidates": 0, "criterion_code": code}

    pa = snap.anchor_position_idx
    if len(cands) == 1:
        cur = cands[0]
        meta: dict[str, Any] = {
            "method": "single",
            "candidates": 1,
            "criterion_code": code,
            "parent_anchor_position_idx": pa,
            "current_anchor_position_idx": cur.get("anchor_position_idx"),
        }
        if pa is not None and cur.get("anchor_position_idx") is not None:
            meta["anchor_delta"] = abs(int(pa) - int(cur["anchor_position_idx"]))
        return cur, meta

    # Multiple rows with same criterion_code: rank by anchor distance, then evidence overlap.
    scored: list[tuple[int, float, int, dict[str, Any]]] = []
    for i, c in enumerate(cands):
        dist = _anchor_distance(pa, c)
        ov = evidence_overlap_score(snap.evidence_json, c.get("evidence") or [])
        scored.append((dist, -ov, i, c))
    scored.sort()
    best = scored[0][3]
    meta = {
        "method": "multi_disambiguated",
        "candidates": len(cands),
        "criterion_code": code,
        "tie_break": "anchor_distance_then_evidence_overlap",
        "parent_anchor_position_idx": pa,
        "current_anchor_position_idx": best.get("anchor_position_idx"),
    }
    if pa is not None and best.get("anchor_position_idx") is not None:
        meta["anchor_delta"] = abs(int(pa) - int(best["anchor_position_idx"]))
    meta["evidence_overlap_with_parent"] = round(
        evidence_overlap_score(snap.evidence_json, best.get("evidence") or []), 4
    )
    return best, meta


def _runtime_confirms_fixes(exec_meta: dict[str, Any] | None) -> bool:
    """
    True if a passing criterion can be treated as runtime-confirmed, or execution
    was intentionally disabled. Import failures block runtime confirmation.
    """
    if not exec_meta:
        return True
    if exec_meta.get("notebook_execution_disabled"):
        return True
    if exec_meta.get("notebook_execution_import_unavailable"):
        return False
    if exec_meta.get("notebook_execution_skipped"):
        return True
    return bool(exec_meta.get("notebook_execution_ok"))


def compute_iteration_fixes(
    db: Session,
    child_project_id: str,
    parent_project_id: str,
    merged_results: list[dict[str, Any]],
    notebook_exec_meta: dict[str, Any] | None,
) -> tuple[list[IterationIssueResolution], dict[str, Any]]:
    """
    Compare parent's latest review snapshot open issues with current merged results.
    Persists IterationIssueResolution rows (caller should delete prior rows for child first).
    """
    db.query(IterationIssueResolution).filter(
        IterationIssueResolution.child_project_id == child_project_id
    ).delete(synchronize_session=False)

    parent_batch = get_latest_snapshot_batch(db, parent_project_id)
    if parent_batch is None:
        summary = {
            "has_parent_link": True,
            "parent_project_id": parent_project_id,
            "status": "no_parent_review_snapshot",
            "message": "У родительского проекта ещё нет завершённого ревью (снимка критериев).",
            "items": [],
        }
        return [], summary

    issues = list_open_issues_from_batch(parent_batch)
    if not issues:
        summary = {
            "has_parent_link": True,
            "parent_project_id": parent_project_id,
            "parent_batch_id": parent_batch.id,
            "status": "nothing_to_verify",
            "message": "В прошлой итерации не осталось замечаний со статусом отличным от pass.",
            "items": [],
        }
        return [], summary

    merged_by_code = group_merged_results_by_code(merged_results)
    runtime_ok = _runtime_confirms_fixes(notebook_exec_meta)
    resolutions: list[IterationIssueResolution] = []
    item_payloads: list[dict[str, Any]] = []

    for snap in issues:
        cur, match_meta = match_merged_to_snapshot(snap, merged_by_code)
        detail: dict[str, Any] = {
            "criterion_code": snap.criterion_code,
            "parent_status": snap.status,
            "parent_severity": snap.severity,
            "parent_comment_excerpt": (snap.generated_comment or "")[:240],
            "parent_anchor_position_idx": snap.anchor_position_idx,
            "match": match_meta,
        }

        if cur is None:
            status = "cannot_verify"
            detail["reason"] = "criterion_missing_in_current_review"
        else:
            detail["current_status"] = cur.get("status")
            detail["current_anchor_position_idx"] = cur.get("anchor_position_idx")
            cur_st = str(cur.get("status") or "")
            if cur_st == "pass":
                if runtime_ok:
                    status = "fixed"
                else:
                    status = "cannot_verify"
                    detail["reason"] = "notebook_execution_failed_or_incomplete"
            elif cur_st == "warn" and snap.status == "fail":
                status = "partially_fixed"
            else:
                status = "not_fixed"

        detail["resolution_status"] = status
        detail = normalize_iteration_issue_resolution_detail(detail)
        item_payloads.append(detail)

        resolutions.append(
            IterationIssueResolution(
                id=str(uuid.uuid4()),
                child_project_id=child_project_id,
                parent_batch_id=parent_batch.id,
                parent_snapshot_id=snap.id,
                resolution_status=str(detail["resolution_status"]),
                detail_json=detail,
            )
        )

    for row in resolutions:
        db.add(row)

    fixed_n = sum(1 for i in item_payloads if i["resolution_status"] == "fixed")
    partial_n = sum(1 for i in item_payloads if i["resolution_status"] == "partially_fixed")
    open_n = sum(1 for i in item_payloads if i["resolution_status"] == "not_fixed")
    unverified_n = sum(1 for i in item_payloads if i["resolution_status"] == "cannot_verify")

    summary = {
        "has_parent_link": True,
        "parent_project_id": parent_project_id,
        "parent_batch_id": parent_batch.id,
        "iteration_fix_policy_version": ITERATION_FIX_POLICY_VERSION,
        "status": "evaluated",
        "counts": {
            "total_previous_issues": len(item_payloads),
            "fixed": fixed_n,
            "partially_fixed": partial_n,
            "not_fixed": open_n,
            "cannot_verify": unverified_n,
        },
        "notebook_runtime": notebook_exec_meta or {},
        "items": item_payloads,
    }
    return resolutions, summary


def get_parent_project_id_for_child(db: Session, child_project_id: str) -> str | None:
    row = db.get(ProjectLineage, child_project_id)
    if row is None:
        return None
    return row.parent_project_id
