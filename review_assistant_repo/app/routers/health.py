from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.metrics import (
    llm_circuit_open_total,
    metadata_backfill_projects_total,
    metadata_backfill_resolutions_total,
)
from app.models import IterationIssueResolution, Project
from app.services.iteration_metadata_quality import run_metadata_quality_audit

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness: process is up."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    """
    Readiness: database reachable; optional LLM API key presence when ``enable_llm`` is true.
    """
    settings = get_settings()
    db.execute(text("SELECT 1"))
    llm_ok: bool | None = None
    if settings.enable_llm:
        llm_ok = bool(settings.llm_api_key and str(settings.llm_api_key).strip())
    return {
        "status": "ready",
        "database": "ok",
        "llm_configured": llm_ok,
    }


def _prom_label_value(value: str) -> str:
    """Escape double quotes in label values for Prometheus text format."""
    return (value or "unknown").replace("\\", "\\\\").replace('"', '\\"')


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics(db: Session = Depends(get_db)):
    """
    Prometheus / OpenMetrics-style exposition with HELP and TYPE for each metric family.
    """
    lines: list[str] = []

    lines.append("# HELP review_assistant_projects Number of projects grouped by status.")
    lines.append("# TYPE review_assistant_projects gauge")
    rows = db.query(Project.status, func.count(Project.id)).group_by(Project.status).all()
    for status, cnt in rows:
        safe = _prom_label_value(status or "unknown")
        lines.append(f'review_assistant_projects{{status="{safe}"}} {int(cnt)}')

    lines.append(
        "# HELP review_assistant_iteration_issue_resolution_rows_total "
        "Total rows in iteration_issue_resolutions."
    )
    lines.append("# TYPE review_assistant_iteration_issue_resolution_rows_total gauge")
    res_total = db.query(func.count(IterationIssueResolution.id)).scalar() or 0
    lines.append(f"review_assistant_iteration_issue_resolution_rows_total {int(res_total)}")

    lines.append(
        "# HELP review_assistant_iteration_issue_resolutions "
        "Iteration issue resolution rows grouped by resolution_status."
    )
    lines.append("# TYPE review_assistant_iteration_issue_resolutions gauge")
    res_by = (
        db.query(IterationIssueResolution.resolution_status, func.count(IterationIssueResolution.id))
        .group_by(IterationIssueResolution.resolution_status)
        .all()
    )
    for st, cnt in res_by:
        safe = _prom_label_value(st or "unknown")
        lines.append(f'review_assistant_iteration_issue_resolutions{{status="{safe}"}} {int(cnt)}')

    lines.append(
        "# HELP review_assistant_llm_circuit_open_total "
        "Times the LLM client circuit breaker entered open state (process lifetime)."
    )
    lines.append("# TYPE review_assistant_llm_circuit_open_total counter")
    lines.append(f"review_assistant_llm_circuit_open_total {llm_circuit_open_total()}")

    audit = run_metadata_quality_audit(db, sample_limit=200)
    lines.append(
        "# HELP review_assistant_metadata_quality_audit_projects_sample_size "
        "Projects scanned in the latest metadata quality audit (sample_limit=200, newest by updated_at)."
    )
    lines.append("# TYPE review_assistant_metadata_quality_audit_projects_sample_size gauge")
    lines.append(
        f"review_assistant_metadata_quality_audit_projects_sample_size {int(audit['projects_sample_size'])}"
    )
    lines.append(
        "# HELP review_assistant_metadata_quality_iteration_fix_summary_invalid_type "
        "In the audit sample: iteration_fix_summary present but not a dict."
    )
    lines.append("# TYPE review_assistant_metadata_quality_iteration_fix_summary_invalid_type gauge")
    lines.append(
        "review_assistant_metadata_quality_iteration_fix_summary_invalid_type "
        f"{int(audit['iteration_fix_summary_invalid_type'])}"
    )
    lines.append(
        "# HELP review_assistant_metadata_quality_evaluated_missing_policy_version "
        "In the audit sample: status=evaluated but iteration_fix_policy_version missing."
    )
    lines.append("# TYPE review_assistant_metadata_quality_evaluated_missing_policy_version gauge")
    lines.append(
        "review_assistant_metadata_quality_evaluated_missing_policy_version "
        f"{int(audit['evaluated_missing_policy_version'])}"
    )
    lines.append(
        "# HELP review_assistant_metadata_quality_evaluated_missing_or_bad_counts "
        "In the audit sample: status=evaluated but counts missing or not a dict."
    )
    lines.append("# TYPE review_assistant_metadata_quality_evaluated_missing_or_bad_counts gauge")
    lines.append(
        "review_assistant_metadata_quality_evaluated_missing_or_bad_counts "
        f"{int(audit['evaluated_missing_or_bad_counts'])}"
    )

    lines.append(
        "# HELP review_assistant_metadata_backfill_projects_total "
        "Project metadata_json rows normalized via POST /debug/metadata_backfill (process lifetime)."
    )
    lines.append("# TYPE review_assistant_metadata_backfill_projects_total counter")
    lines.append(f"review_assistant_metadata_backfill_projects_total {metadata_backfill_projects_total()}")

    lines.append(
        "# HELP review_assistant_metadata_backfill_resolutions_total "
        "IterationIssueResolution detail_json rows normalized via POST /debug/metadata_backfill (process lifetime)."
    )
    lines.append("# TYPE review_assistant_metadata_backfill_resolutions_total counter")
    lines.append(
        f"review_assistant_metadata_backfill_resolutions_total {metadata_backfill_resolutions_total()}"
    )

    lines.append("# EOF")
    return "\n".join(lines) + "\n"
