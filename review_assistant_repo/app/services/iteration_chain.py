from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.models import IterationIssueResolution, Project, ProjectLineage
from app.services.iteration_time import review_turnaround_hours


def walk_iteration_ids_root_first(db: Session, project_id: str, max_depth: int = 64) -> list[str]:
    """
    Return project ids from root iteration to the given project (inclusive).
    """
    backward: list[str] = []
    cur: str | None = project_id
    seen: set[str] = set()

    while cur and cur not in seen:
        if len(backward) >= max_depth:
            break
        seen.add(cur)
        backward.append(cur)
        row = db.get(ProjectLineage, cur)
        cur = row.parent_project_id if row else None

    backward.reverse()
    return backward


def build_iteration_chain_payload(db: Session, project_id: str) -> dict[str, Any]:
    """Structured chain for API (root → current)."""
    project = db.get(Project, project_id)
    if not project:
        return {}

    ordered_ids = walk_iteration_ids_root_first(db, project_id)
    nodes: list[dict[str, Any]] = []

    for pid in ordered_ids:
        p = db.get(Project, pid)
        if not p:
            continue
        lin = db.get(ProjectLineage, pid)
        meta = p.metadata_json or {}
        summary = meta.get("iteration_fix_summary")
        nodes.append(
            {
                "project_id": p.id,
                "parent_project_id": lin.parent_project_id if lin else None,
                "iteration_no": lin.iteration_no if lin else 1,
                "status": p.status,
                "final_verdict": p.final_verdict,
                "source_type": p.source_type,
                "original_filename": p.original_filename,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                "review_turnaround_hours": review_turnaround_hours(p),
                "has_iteration_fix_summary": bool(
                    isinstance(summary, dict) and summary.get("status") not in (None, "no_parent_link")
                ),
                "iteration_fix_status": summary.get("status") if isinstance(summary, dict) else None,
            }
        )

    return {
        "anchor_project_id": project_id,
        "depth": max(0, len(nodes) - 1),
        "nodes": nodes,
    }


def build_iteration_insights_payload(db: Session, project_id: str) -> dict[str, Any]:
    """Aggregate metrics from DB resolutions and latest metadata snapshot."""
    project = db.get(Project, project_id)
    if not project:
        return {}

    meta = project.metadata_json or {}
    raw_fix = meta.get("iteration_fix_summary")
    fix_summary: dict[str, Any] = raw_fix if isinstance(raw_fix, dict) else {}

    rows = (
        db.query(IterationIssueResolution)
        .filter(IterationIssueResolution.child_project_id == project_id)
        .all()
    )

    status_hist = Counter(r.resolution_status for r in rows)
    method_hist: Counter[str] = Counter()
    multi_n = 0
    for r in rows:
        match = (r.detail_json or {}).get("match") or {}
        method = str(match.get("method") or "unknown")
        method_hist[method] += 1
        if method == "multi_disambiguated":
            multi_n += 1

    return {
        "project_id": project_id,
        "iteration_fix_policy_version": fix_summary.get("iteration_fix_policy_version"),
        "summary_counts": fix_summary.get("counts"),
        "summary_status": fix_summary.get("status"),
        "notebook_runtime": meta.get("notebook_execution"),
        "stored_resolutions": len(rows),
        "resolution_status_histogram": dict(status_hist),
        "match_method_histogram": dict(method_hist),
        "multi_disambiguated_issues": multi_n,
    }
