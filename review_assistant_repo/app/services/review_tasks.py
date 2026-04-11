"""Background execution of the review pipeline (separate DB session per task)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.db import get_session_local
from app.models import Project, ReviewJob
from app.services.review_service import ReviewPipelineError, ReviewService

logger = logging.getLogger(__name__)


def _touch_job(db, job_id: str, **fields: object) -> None:
    job = db.get(ReviewJob, job_id)
    if job is None:
        return
    for k, v in fields.items():
        setattr(job, k, v)
    job.updated_at = datetime.now(UTC)
    db.commit()


def run_review_background(project_id: str, job_id: str) -> None:
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        job_row = db.get(ReviewJob, job_id)
        if job_row is None:
            logger.error("Review job not found %s", job_id)
            return
        _touch_job(db, job_id, status="running", error_message=None)

        ReviewService(db).run_review(project_id)

        proj = db.get(Project, project_id)
        _touch_job(
            db,
            job_id,
            status="done",
            detail_json={
                "final_verdict": proj.final_verdict if proj else None,
                "project_status": proj.status if proj else None,
            },
            error_message=None,
        )
    except ValueError:
        logger.warning("Background review: project not found %s", project_id)
        _touch_job(
            db,
            job_id,
            status="failed",
            error_message="project_not_found",
            detail_json={"project_id": project_id},
        )
    except ReviewPipelineError as exc:
        logger.warning("Background review failed for %s: %s", project_id, exc)
        _touch_job(
            db,
            job_id,
            status="failed",
            error_message=str(exc)[:2000],
            detail_json={"project_id": project_id},
        )
    except Exception:
        logger.exception("Unexpected error in background review for %s", project_id)
        _touch_job(
            db,
            job_id,
            status="failed",
            error_message="unexpected_error",
            detail_json={"project_id": project_id},
        )
    finally:
        db.close()
