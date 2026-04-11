from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models import IterationIssueResolution, Project, ProjectLineage
from app.services.iteration_chain import walk_iteration_ids_root_first
from app.services.iteration_time import hours_between_utc, review_turnaround_hours


def _counter_to_rates(counter: Counter) -> dict[str, Any]:
    total = int(sum(counter.values()))
    fixed = int(counter.get("fixed", 0))
    partial = int(counter.get("partially_fixed", 0))
    open_n = int(counter.get("not_fixed", 0))
    unv = int(counter.get("cannot_verify", 0))
    return {
        "total": total,
        "fixed": fixed,
        "partially_fixed": partial,
        "not_fixed": open_n,
        "cannot_verify": unv,
        "fixed_rate": round(fixed / total, 4) if total else None,
        "partially_fixed_rate": round(partial / total, 4) if total else None,
        "not_fixed_rate": round(open_n / total, 4) if total else None,
        "cannot_verify_rate": round(unv / total, 4) if total else None,
    }


def _aggregate_resolution_rows(rows: list[IterationIssueResolution]) -> dict[str, Any]:
    status_c = Counter(r.resolution_status for r in rows)
    by_crit: dict[str, Counter] = defaultdict(Counter)
    multi = 0
    for r in rows:
        code = str((r.detail_json or {}).get("criterion_code") or "unknown")
        by_crit[code][r.resolution_status] += 1
        match = (r.detail_json or {}).get("match") or {}
        if match.get("method") == "multi_disambiguated":
            multi += 1
    total = len(rows)
    share = round(multi / total, 4) if total else None
    return {
        "status_counter": status_c,
        "by_criterion": by_crit,
        "multi_disambiguated_count": multi,
        "multi_disambiguated_share": share,
        "rates": _counter_to_rates(status_c),
        "criterion_breakdown": _criterion_breakdown(by_crit),
    }


def _criterion_breakdown(by_crit: dict[str, Counter]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for code in sorted(by_crit.keys()):
        c = by_crit[code]
        t = int(sum(c.values()))
        fx = int(c.get("fixed", 0))
        out.append(
            {
                "criterion_code": code,
                "fixed": fx,
                "partially_fixed": int(c.get("partially_fixed", 0)),
                "not_fixed": int(c.get("not_fixed", 0)),
                "cannot_verify": int(c.get("cannot_verify", 0)),
                "total": t,
                "fixed_rate": round(fx / t, 4) if t else None,
            }
        )
    return out


def _fetch_resolutions_for_child(db: Session, child_project_id: str) -> list[IterationIssueResolution]:
    return (
        db.query(IterationIssueResolution)
        .filter(IterationIssueResolution.child_project_id == child_project_id)
        .all()
    )


def build_iteration_metrics_payload(db: Session, project_id: str) -> dict[str, Any]:
    """Anchor metrics + rollup over the whole resubmit chain + per-iteration slice."""
    project = db.get(Project, project_id)
    if not project:
        return {}

    meta = project.metadata_json or {}
    raw_fix = meta.get("iteration_fix_summary")
    fix_summary: dict[str, Any] = raw_fix if isinstance(raw_fix, dict) else {}
    policy_version = fix_summary.get("iteration_fix_policy_version")

    chain = walk_iteration_ids_root_first(db, project_id)
    anchor_rows = _fetch_resolutions_for_child(db, project_id)
    anchor_agg = _aggregate_resolution_rows(anchor_rows)

    chain_all: list[IterationIssueResolution] = []
    by_iteration: list[dict[str, Any]] = []

    chain_submission_span_hours: float | None = None
    if len(chain) >= 2:
        root_p = db.get(Project, chain[0])
        leaf_p = db.get(Project, chain[-1])
        if root_p and leaf_p:
            chain_submission_span_hours = hours_between_utc(leaf_p.created_at, root_p.created_at)

    for pid in chain:
        rows = _fetch_resolutions_for_child(db, pid)
        if not rows:
            continue
        chain_all.extend(rows)
        lineage = db.get(ProjectLineage, pid)
        it_no = lineage.iteration_no if lineage else 1
        parent_pid = lineage.parent_project_id if lineage else None
        step_agg = _aggregate_resolution_rows(rows)
        child_proj = db.get(Project, pid)
        parent_proj = db.get(Project, parent_pid) if parent_pid else None
        hours_since_prior = None
        if child_proj and parent_proj:
            hours_since_prior = hours_between_utc(child_proj.created_at, parent_proj.created_at)
        by_iteration.append(
            {
                "project_id": pid,
                "iteration_no": it_no,
                "parent_project_id": parent_pid,
                "hours_since_prior_iteration": hours_since_prior,
                "review_turnaround_hours": review_turnaround_hours(child_proj) if child_proj else None,
                "rates": step_agg["rates"],
                "multi_disambiguated_count": step_agg["multi_disambiguated_count"],
                "multi_disambiguated_share": step_agg["multi_disambiguated_share"],
                "criterion_breakdown": step_agg["criterion_breakdown"],
            }
        )

    rollup_agg = _aggregate_resolution_rows(chain_all)

    return {
        "anchor_project_id": project_id,
        "chain_length": len(chain),
        "chain_submission_span_hours": chain_submission_span_hours,
        "iteration_fix_policy_version": policy_version,
        "metadata_summary_counts": fix_summary.get("counts"),
        "metadata_summary_status": fix_summary.get("status"),
        "anchor": {
            "rates": anchor_agg["rates"],
            "multi_disambiguated_count": anchor_agg["multi_disambiguated_count"],
            "multi_disambiguated_share": anchor_agg["multi_disambiguated_share"],
            "criterion_breakdown": anchor_agg["criterion_breakdown"],
        },
        "chain_rollup": {
            "rates": rollup_agg["rates"],
            "multi_disambiguated_count": rollup_agg["multi_disambiguated_count"],
            "multi_disambiguated_share": rollup_agg["multi_disambiguated_share"],
            "criterion_breakdown": rollup_agg["criterion_breakdown"],
            "total_resolution_records": len(chain_all),
        },
        "by_iteration": by_iteration,
    }


def build_recent_iteration_metrics_payload(db: Session, limit: int = 20) -> dict[str, Any]:
    """Latest child projects that have iteration resolution rows (dashboard list)."""
    limit = max(1, min(int(limit), 200))

    subq = (
        db.query(
            IterationIssueResolution.child_project_id.label("pid"),
            func.max(IterationIssueResolution.created_at).label("last_at"),
        )
        .group_by(IterationIssueResolution.child_project_id)
        .order_by(desc(func.max(IterationIssueResolution.created_at)))
        .limit(limit)
        .all()
    )
    if not subq:
        return {"items": []}

    pids = [row.pid for row in subq]
    last_at_map = {row.pid: row.last_at for row in subq}

    rows = (
        db.query(IterationIssueResolution).filter(IterationIssueResolution.child_project_id.in_(pids)).all()
    )
    by_child: dict[str, list[IterationIssueResolution]] = defaultdict(list)
    for r in rows:
        by_child[r.child_project_id].append(r)

    items: list[dict[str, Any]] = []
    for pid in pids:
        agg = _aggregate_resolution_rows(by_child.get(pid, []))
        la = last_at_map.get(pid)
        items.append(
            {
                "project_id": pid,
                "last_resolution_at": la.isoformat() if la else None,
                "total_issues_addressed": agg["rates"]["total"],
                "rates": agg["rates"],
                "multi_disambiguated_count": agg["multi_disambiguated_count"],
                "multi_disambiguated_share": agg["multi_disambiguated_share"],
            }
        )

    return {"items": items}


ABS_RESOLUTION_SCAN_CAP = 500_000


def build_global_criterion_rollup_payload(
    db: Session,
    *,
    max_rows: int = 20_000,
    limit_criteria: int = 50,
    full_scan: bool = False,
) -> dict[str, Any]:
    """
    Aggregate iteration resolution rows (newest first) by criterion_code.
    When full_scan is True, scans up to ABS_RESOLUTION_SCAN_CAP rows (ignores max_rows cap below that).
    """
    limit_criteria = max(1, min(int(limit_criteria), 500))
    if full_scan:
        eff_limit = ABS_RESOLUTION_SCAN_CAP
    else:
        eff_limit = max(1, min(int(max_rows), ABS_RESOLUTION_SCAN_CAP))

    q = db.query(IterationIssueResolution).order_by(desc(IterationIssueResolution.created_at))
    rows = q.limit(eff_limit).all()
    status_c: Counter[str] = Counter()
    by_crit: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        status_c[r.resolution_status] += 1
        code = str((r.detail_json or {}).get("criterion_code") or "unknown")
        by_crit[code][r.resolution_status] += 1

    breakdown = _criterion_breakdown(by_crit)
    breakdown.sort(key=lambda x: -int(x["total"]))
    return {
        "sampled_resolution_rows": len(rows),
        "max_rows_cap": eff_limit,
        "full_scan": bool(full_scan),
        "overall_rates": _counter_to_rates(status_c),
        "by_criterion": breakdown[:limit_criteria],
    }
