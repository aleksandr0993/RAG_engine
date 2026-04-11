from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import IterationIssueResolution, Project

ITERATION_FIX_POLICY_VERSION = "1.1"

ALLOWED_ITERATION_FIX_SUMMARY_STATUS = frozenset(
    {
        "evaluated",
        "no_parent_review_snapshot",
        "nothing_to_verify",
        "no_parent_link",
        "corrupt_metadata_normalized",
    }
)

ALLOWED_RESOLUTION_STATUS = frozenset(
    {"fixed", "partially_fixed", "not_fixed", "cannot_verify"},
)

# Keys produced by NotebookExecutionResult.to_metadata() plus deployment flags.
NOTEBOOK_EXECUTION_KEYS = frozenset(
    {
        "notebook_execution_ok",
        "notebook_execution_skipped",
        "notebook_execution_skip_reason",
        "notebook_executed_path",
        "notebook_execution_duration_ms",
        "notebook_execution_error_type",
        "notebook_execution_error_message",
        "notebook_execution_traceback",
        "notebook_execution_disabled",
        "notebook_execution_import_unavailable",
        "notebook_execution_not_applicable",
    }
)


def normalize_iteration_fix_summary(raw: Any) -> dict[str, Any]:
    """
    Coerce iteration_fix_summary to a safe dict; fill policy version when applicable.
    """
    if not isinstance(raw, dict):
        return {
            "has_parent_link": False,
            "status": "corrupt_metadata_normalized",
            "items": [],
            "iteration_fix_policy_version": ITERATION_FIX_POLICY_VERSION,
        }

    out = dict(raw)
    hpl = out.get("has_parent_link")
    if hpl is not None and not isinstance(hpl, bool):
        out["has_parent_link"] = bool(hpl)

    st = out.get("status")
    if st is not None:
        st_s = str(st)
        if st_s not in ALLOWED_ITERATION_FIX_SUMMARY_STATUS:
            out["status"] = "corrupt_metadata_normalized"
            out.setdefault("_normalized_invalid_status", st_s)
        else:
            out["status"] = st_s

    if out.get("items") is not None and not isinstance(out["items"], list):
        out["items"] = []

    counts = out.get("counts")
    if counts is not None and not isinstance(counts, dict):
        out["counts"] = {}

    out.setdefault("iteration_fix_policy_version", ITERATION_FIX_POLICY_VERSION)
    return out


def normalize_notebook_execution(raw: Any) -> dict[str, Any]:
    """Strip unknown keys; coerce booleans/numbers/strings for known notebook_execution fields."""
    if not isinstance(raw, dict):
        return {"notebook_execution_not_applicable": True}

    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in NOTEBOOK_EXECUTION_KEYS:
            continue
        if k in (
            "notebook_execution_ok",
            "notebook_execution_skipped",
            "notebook_execution_disabled",
            "notebook_execution_import_unavailable",
            "notebook_execution_not_applicable",
        ):
            out[k] = bool(v) if v is not None else False
        elif k == "notebook_execution_duration_ms":
            try:
                out[k] = round(float(v), 4) if v is not None else None
            except (TypeError, ValueError):
                out[k] = None
        else:
            out[k] = v if v is None or isinstance(v, (str, int, float, bool)) else str(v)
    return out if out else {"notebook_execution_not_applicable": True}


def normalize_iteration_issue_resolution_detail(raw: Any) -> dict[str, Any]:
    """Ensure required fields for analytics / metrics; keep extra keys."""
    if not isinstance(raw, dict):
        return {
            "criterion_code": "unknown",
            "resolution_status": "cannot_verify",
            "match": {"method": "none", "candidates": 0},
        }

    out = dict(raw)
    code = out.get("criterion_code")
    out["criterion_code"] = str(code).strip() if code is not None else "unknown"

    rs = out.get("resolution_status")
    rs_s = str(rs) if rs is not None else "cannot_verify"
    if rs_s not in ALLOWED_RESOLUTION_STATUS:
        out["_normalized_invalid_resolution_status"] = rs_s
        rs_s = "cannot_verify"
    out["resolution_status"] = rs_s

    match = out.get("match")
    if not isinstance(match, dict):
        match = {"method": "unknown", "candidates": 0}
        out["match"] = match
    else:
        m = dict(match)
        method = m.get("method")
        m["method"] = str(method) if method is not None else "unknown"
        if m.get("candidates") is not None:
            try:
                m["candidates"] = int(m["candidates"])
            except (TypeError, ValueError):
                m["candidates"] = 0
        out["match"] = m

    return out


def audit_iteration_metadata_on_projects(rows: list[Any]) -> dict[str, int]:
    """
    Inspect Project ORM rows (already loaded). Count common metadata issues.
    """
    n = len(rows)
    missing_policy = 0
    invalid_summary_type = 0
    evaluated_without_counts = 0

    for p in rows:
        meta = p.metadata_json or {}
        s = meta.get("iteration_fix_summary")
        if s is None:
            continue
        if not isinstance(s, dict):
            invalid_summary_type += 1
            continue
        if s.get("status") == "evaluated":
            if "iteration_fix_policy_version" not in s:
                missing_policy += 1
            if not isinstance(s.get("counts"), dict):
                evaluated_without_counts += 1

    return {
        "projects_sample_size": n,
        "iteration_fix_summary_invalid_type": invalid_summary_type,
        "evaluated_missing_policy_version": missing_policy,
        "evaluated_missing_or_bad_counts": evaluated_without_counts,
    }


def backfill_project_metadata_json(project: Any) -> bool:
    """
    Normalize iteration_fix_summary and notebook_execution in-place on project.metadata_json.
    Returns True if JSON changed.
    """
    meta = dict(project.metadata_json or {})
    changed = False

    if "iteration_fix_summary" in meta:
        old = meta.get("iteration_fix_summary")
        new = normalize_iteration_fix_summary(old)
        if new != old:
            meta["iteration_fix_summary"] = new
            changed = True

    if "notebook_execution" in meta:
        old_nb = meta.get("notebook_execution")
        new_nb = normalize_notebook_execution(old_nb)
        if new_nb != old_nb:
            meta["notebook_execution"] = new_nb
            changed = True

    if changed:
        project.metadata_json = meta
    return changed


def backfill_iteration_issue_resolution_row(row: Any) -> bool:
    """Normalize detail_json on an IterationIssueResolution row. Returns True if changed."""
    old = row.detail_json
    new = normalize_iteration_issue_resolution_detail(old)
    if new != old:
        row.detail_json = new
        return True
    return False


def run_metadata_quality_audit(db: Session, sample_limit: int = 200) -> dict[str, int]:
    sample_limit = max(1, min(int(sample_limit), 2000))
    rows = db.query(Project).order_by(Project.updated_at.desc()).limit(sample_limit).all()
    return audit_iteration_metadata_on_projects(rows)


def run_metadata_backfill(
    db: Session,
    *,
    project_limit: int = 500,
    resolution_limit: int = 5000,
) -> dict[str, int]:
    from app.metrics import inc_metadata_backfill_projects, inc_metadata_backfill_resolutions

    pl = max(1, min(int(project_limit), 5000))
    rl = max(1, min(int(resolution_limit), 50_000))

    rows = db.query(Project).order_by(Project.updated_at.desc()).limit(pl).all()
    changed_p = 0
    for p in rows:
        if backfill_project_metadata_json(p):
            changed_p += 1

    rrows = (
        db.query(IterationIssueResolution)
        .order_by(IterationIssueResolution.created_at.desc())
        .limit(rl)
        .all()
    )
    changed_r = 0
    for r in rrows:
        if backfill_iteration_issue_resolution_row(r):
            changed_r += 1

    db.commit()
    inc_metadata_backfill_projects(changed_p)
    inc_metadata_backfill_resolutions(changed_r)
    return {
        "projects_scanned": len(rows),
        "projects_updated": changed_p,
        "resolutions_scanned": len(rrows),
        "resolutions_updated": changed_r,
    }
