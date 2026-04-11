"""Persistent RL training jobs (SQLAlchemy) + artefact locks; background worker uses its own DB session."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session_local
from app.models import RLTrainArtefactLock, RLTrainJob
from app.rl.paths import resolve_rl_artefact_under_root
from app.rl.sb3_io import train_sb3
from app.rl.schemas import RLTrainRequest, RLTrainResponse

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("accepted", "running")


class RLTrainConcurrentLimitError(Exception):
    """Too many jobs in accepted/running state."""


@dataclass
class RLTrainJobState:
    job_id: str
    status: str
    artefact_name: str
    env_id: str
    algorithm: str
    total_timesteps: int
    created_at_iso: str
    started_at_iso: str | None = None
    finished_at_iso: str | None = None
    error: str | None = None
    result: RLTrainResponse | None = None
    request_snapshot: dict[str, Any] | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def row_to_state(row: RLTrainJob) -> RLTrainJobState:
    result = None
    if row.result_json:
        result = RLTrainResponse.model_validate(row.result_json)
    return RLTrainJobState(
        job_id=row.id,
        status=row.status,
        artefact_name=row.artefact_name,
        env_id=row.env_id,
        algorithm=row.algorithm,
        total_timesteps=row.total_timesteps,
        created_at_iso=_iso(row.created_at) or "",
        started_at_iso=_iso(row.started_at),
        finished_at_iso=_iso(row.finished_at),
        error=row.error_message,
        result=result,
        request_snapshot=row.request_json,
    )


def count_active_train_jobs(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(RLTrainJob).where(RLTrainJob.status.in_(_ACTIVE_STATUSES))
        )
        or 0
    )


def is_training_artefact_busy_db(db: Session, artefact_name: str) -> bool:
    return db.get(RLTrainArtefactLock, artefact_name) is not None


def get_train_job_db(db: Session, job_id: str) -> RLTrainJobState | None:
    row = db.get(RLTrainJob, job_id)
    if row is None:
        return None
    return row_to_state(row)


def validate_train_request_against_settings(request: RLTrainRequest, settings: Settings) -> None:
    if request.total_timesteps > settings.rl_train_max_timesteps:
        raise ValueError(
            f"total_timesteps exceeds RL_TRAIN_MAX_TIMESTEPS ({settings.rl_train_max_timesteps})"
        )


def register_train_job_db(
    db: Session,
    request: RLTrainRequest,
    *,
    settings: Settings,
    created_by_sub: str | None,
) -> str | None:
    """
    Insert queued job + artefact lock. Returns None if the artefact is already locked (409).
    Raises RLTrainConcurrentLimitError if global concurrent cap is reached.
    """
    if count_active_train_jobs(db) >= settings.rl_train_max_concurrent:
        raise RLTrainConcurrentLimitError(
            f"Too many concurrent RL train jobs (max {settings.rl_train_max_concurrent})"
        )

    job_id = uuid.uuid4().hex
    now = _utcnow()
    job = RLTrainJob(
        id=job_id,
        status="accepted",
        artefact_name=request.artefact_name,
        env_id=request.env_id,
        algorithm=request.algorithm,
        total_timesteps=request.total_timesteps,
        request_json=request.model_dump(),
        created_by_sub=created_by_sub,
        created_at=now,
        updated_at=now,
    )
    lock = RLTrainArtefactLock(artefact_name=request.artefact_name, job_id=job_id)
    db.add(job)
    db.add(lock)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return job_id


def _release_lock(db: Session, job_id: str) -> None:
    db.query(RLTrainArtefactLock).filter(RLTrainArtefactLock.job_id == job_id).delete()
    db.commit()


def claim_next_accepted_train_job(db: Session) -> str | None:
    """
    Atomically pick the oldest ``accepted`` job and set status to ``running``.
    Returns job id or None. Safe for multiple worker processes (losers get rowcount 0).
    """
    try:
        jid = db.scalar(
            select(RLTrainJob.id)
            .where(RLTrainJob.status == "accepted")
            .order_by(RLTrainJob.created_at.asc())
            .limit(1)
        )
        if jid is None:
            db.rollback()
            return None
        now = _utcnow()
        res = db.execute(
            update(RLTrainJob)
            .where(RLTrainJob.id == jid, RLTrainJob.status == "accepted")
            .values(status="running", started_at=now, updated_at=now)
        )
        rc = getattr(res, "rowcount", None)
        if rc != 1:
            db.rollback()
            return None
        db.commit()
        return str(jid)
    except Exception:
        db.rollback()
        raise


def execute_rl_train_work(job_id: str) -> None:
    """
    Run SB3 training for a job that is already ``running`` (API or external worker).
    Updates DB to completed/failed and releases the artefact lock.
    """
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        row = db.get(RLTrainJob, job_id)
        if row is None:
            logger.warning("RL train job missing: %s", job_id)
            return
        if row.status != "running":
            logger.warning(
                "RL train job %s expected status running, got %s — skipping execute",
                job_id,
                row.status,
            )
            return

        settings = get_settings()
        Path(settings.rl_models_root).mkdir(parents=True, exist_ok=True)
        out_path = resolve_rl_artefact_under_root(
            settings,
            row.artefact_name,
            require_exists=False,
        )
        req = RLTrainRequest.model_validate(row.request_json)
        meta = train_sb3(
            env_id=req.env_id,
            algorithm=req.algorithm,
            total_timesteps=req.total_timesteps,
            save_path=out_path,
            seed=req.seed,
            gymnasium_kwargs=req.gymnasium_kwargs,
        )
        result = RLTrainResponse(
            saved_path=meta["saved_path"],
            env_id=meta["env_id"],
            algorithm=meta["algorithm"],
            total_timesteps=meta["total_timesteps"],
        )
        row2 = db.get(RLTrainJob, job_id)
        if row2:
            fin = _utcnow()
            row2.status = "completed"
            row2.result_json = result.model_dump()
            row2.finished_at = fin
            row2.updated_at = fin
            row2.error_message = None
            db.commit()
        _release_lock(db, job_id)
        logger.info("RL train job completed: %s -> %s", job_id, result.saved_path)
    except Exception as exc:
        logger.exception("RL train job failed: %s", job_id)
        try:
            db.rollback()
            row3 = db.get(RLTrainJob, job_id)
            if row3:
                fin = _utcnow()
                row3.status = "failed"
                row3.error_message = f"{type(exc).__name__}: {exc}"
                row3.finished_at = fin
                row3.updated_at = fin
                db.commit()
            _release_lock(db, job_id)
        except Exception:
            logger.exception("RL train job cleanup failed: %s", job_id)
            db.rollback()
    finally:
        db.close()


def run_rl_train_background(job_id: str) -> None:
    """Mark ``accepted`` → ``running`` in API process, then run training (BackgroundTasks)."""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        row = db.get(RLTrainJob, job_id)
        if row is None:
            logger.warning("RL train job missing: %s", job_id)
            return
        if row.status != "accepted":
            logger.warning(
                "RL train job %s not accepted (status=%s); not starting in API worker",
                job_id,
                row.status,
            )
            return
        now = _utcnow()
        row.status = "running"
        row.started_at = now
        row.updated_at = now
        db.commit()
    except Exception:
        logger.exception("RL train job could not transition to running: %s", job_id)
        db.rollback()
        return
    finally:
        db.close()
    execute_rl_train_work(job_id)


def run_rl_train_sync_db(
    db: Session,
    request: RLTrainRequest,
    *,
    settings: Settings,
    created_by_sub: str | None,
) -> RLTrainResponse:
    """
    Synchronous training with DB audit row + artefact lock for the duration.
    """
    validate_train_request_against_settings(request, settings)
    if is_training_artefact_busy_db(db, request.artefact_name):
        raise ValueError("artefact_busy")
    if count_active_train_jobs(db) >= settings.rl_train_max_concurrent:
        raise RLTrainConcurrentLimitError(
            f"Too many concurrent RL train jobs (max {settings.rl_train_max_concurrent})"
        )

    job_id = uuid.uuid4().hex
    now = _utcnow()
    job = RLTrainJob(
        id=job_id,
        status="running",
        artefact_name=request.artefact_name,
        env_id=request.env_id,
        algorithm=request.algorithm,
        total_timesteps=request.total_timesteps,
        request_json=request.model_dump(),
        created_by_sub=created_by_sub,
        created_at=now,
        updated_at=now,
        started_at=now,
    )
    lock = RLTrainArtefactLock(artefact_name=request.artefact_name, job_id=job_id)
    db.add(job)
    db.add(lock)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValueError("artefact_busy") from None

    try:
        Path(settings.rl_models_root).mkdir(parents=True, exist_ok=True)
        out_path = resolve_rl_artefact_under_root(
            settings,
            request.artefact_name,
            require_exists=False,
        )
        meta = train_sb3(
            env_id=request.env_id,
            algorithm=request.algorithm,
            total_timesteps=request.total_timesteps,
            save_path=out_path,
            seed=request.seed,
            gymnasium_kwargs=request.gymnasium_kwargs,
        )
        result = RLTrainResponse(
            saved_path=meta["saved_path"],
            env_id=meta["env_id"],
            algorithm=meta["algorithm"],
            total_timesteps=meta["total_timesteps"],
        )
        row = db.get(RLTrainJob, job_id)
        if row:
            fin = _utcnow()
            row.status = "completed"
            row.result_json = result.model_dump()
            row.finished_at = fin
            row.updated_at = fin
            row.error_message = None
            db.commit()
        _release_lock(db, job_id)
        return result
    except Exception as exc:
        try:
            db.rollback()
            row = db.get(RLTrainJob, job_id)
            if row:
                fin = _utcnow()
                row.status = "failed"
                row.error_message = f"{type(exc).__name__}: {exc}"
                row.finished_at = fin
                row.updated_at = fin
                db.commit()
            _release_lock(db, job_id)
        except Exception:
            db.rollback()
        raise
