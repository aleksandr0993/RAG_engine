from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import require_user_for_rl_writes
from app.config import get_settings
from app.db import get_db
from app.models import RLTrainJob
from app.rl.engine import RLExperimentEngine
from app.rl.schemas import (
    EpisodeRunRequest,
    EpisodeRunResponse,
    RLEngineHealthResponse,
    RLTrainAsyncAccepted,
    RLTrainJobStatusResponse,
    RLTrainRequest,
    RLTrainResponse,
)
from app.rl.train_jobs import (
    RLTrainConcurrentLimitError,
    RLTrainJobState,
    register_train_job_db,
    row_to_state,
    run_rl_train_background,
    run_rl_train_sync_db,
    validate_train_request_against_settings,
)

router = APIRouter(tags=["rl"])


def _optional_rl_stack() -> tuple[bool, bool]:
    g = importlib.util.find_spec("gymnasium") is not None
    s = importlib.util.find_spec("stable_baselines3") is not None
    return g, s


def _normalized_rl_train_async_executor(settings) -> str:
    raw = (getattr(settings, "rl_train_async_executor", None) or "background_tasks").strip().lower()
    if raw in ("background_tasks", "external_worker"):
        return raw
    return "background_tasks"


def _require_rl_train_stack(settings) -> None:
    if not settings.enable_rl_engine:
        raise HTTPException(
            status_code=503,
            detail="RL engine is disabled. Set ENABLE_RL_ENGINE=true.",
        )
    _, sb3_ok = _optional_rl_stack()
    if not sb3_ok:
        raise HTTPException(
            status_code=503,
            detail="stable-baselines3 is not installed. Install: pip install -e '.[rl,rl_sb3]'",
        )


def _job_to_response(st: RLTrainJobState) -> RLTrainJobStatusResponse:
    return RLTrainJobStatusResponse(
        job_id=st.job_id,
        status=st.status,  # type: ignore[arg-type]
        artefact_name=st.artefact_name,
        env_id=st.env_id,
        algorithm=st.algorithm,
        total_timesteps=st.total_timesteps,
        created_at=st.created_at_iso,
        started_at=st.started_at_iso,
        finished_at=st.finished_at_iso,
        result=st.result,
        error=st.error,
    )


def _rl_created_by(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    sub = user.get("sub")
    return str(sub) if sub is not None else None


@router.get("/rl/health", response_model=RLEngineHealthResponse)
def rl_health() -> RLEngineHealthResponse:
    settings = get_settings()
    enabled = bool(settings.enable_rl_engine)
    gymnasium_available, stable_baselines3_available = _optional_rl_stack()
    return RLEngineHealthResponse(
        status="ok" if enabled else "disabled",
        enabled=enabled,
        available_policies=["random", "openai", "sb3"],
        available_environments=["toy_bandit", "open_source_http", "gymnasium_discrete"],
        gymnasium_available=gymnasium_available,
        stable_baselines3_available=stable_baselines3_available,
        rl_train_async_executor=_normalized_rl_train_async_executor(settings),
    )


@router.post("/rl/episodes/run", response_model=EpisodeRunResponse)
def run_rl_episode(request: EpisodeRunRequest) -> EpisodeRunResponse:
    engine = RLExperimentEngine()
    try:
        return engine.run_episode(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/rl/train", response_model=RLTrainResponse)
def rl_train(
    request: RLTrainRequest,
    db: Session = Depends(get_db),
    user: Annotated[dict | None, Depends(require_user_for_rl_writes)] = None,
) -> RLTrainResponse:
    settings = get_settings()
    _require_rl_train_stack(settings)
    try:
        validate_train_request_against_settings(request, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    Path(settings.rl_models_root).mkdir(parents=True, exist_ok=True)
    try:
        return run_rl_train_sync_db(
            db,
            request,
            settings=settings,
            created_by_sub=_rl_created_by(user),
        )
    except ValueError as exc:
        if str(exc) == "artefact_busy":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Training already in progress for this artefact_name "
                    "(another job holds the lock). Wait or choose another name."
                ),
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RLTrainConcurrentLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"RL train failed: {exc}") from exc


@router.post(
    "/rl/train/async",
    response_model=RLTrainAsyncAccepted,
    status_code=202,
)
def rl_train_async(
    request: RLTrainRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: Annotated[dict | None, Depends(require_user_for_rl_writes)] = None,
) -> RLTrainAsyncAccepted:
    settings = get_settings()
    _require_rl_train_stack(settings)
    try:
        validate_train_request_against_settings(request, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    Path(settings.rl_models_root).mkdir(parents=True, exist_ok=True)
    try:
        job_id = register_train_job_db(
            db,
            request,
            settings=settings,
            created_by_sub=_rl_created_by(user),
        )
    except RLTrainConcurrentLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if job_id is None:
        raise HTTPException(
            status_code=409,
            detail="Training already in progress for this artefact_name. Wait or pick another name.",
        )
    executor = _normalized_rl_train_async_executor(settings)
    if executor == "external_worker":
        msg = (
            "Training queued for external worker. Poll GET /api/v1/rl/train/jobs/{job_id}. "
            "Run scripts/run_rl_train_worker.py with the same DATABASE_URL and RL extras installed."
        )
    else:
        msg = (
            "Training queued in API process (BackgroundTasks). "
            "Poll GET /api/v1/rl/train/jobs/{job_id} for status."
        )
        background_tasks.add_task(run_rl_train_background, job_id)
    return RLTrainAsyncAccepted(job_id=job_id, message=msg)


@router.get("/rl/train/jobs/{job_id}", response_model=RLTrainJobStatusResponse)
def rl_train_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    user: Annotated[dict | None, Depends(require_user_for_rl_writes)] = None,
) -> RLTrainJobStatusResponse:
    settings = get_settings()
    if not settings.enable_rl_engine:
        raise HTTPException(
            status_code=503,
            detail="RL engine is disabled. Set ENABLE_RL_ENGINE=true.",
        )
    row = db.get(RLTrainJob, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Train job not found")
    if settings.require_auth_for_rl_writes and user is not None:
        owner = row.created_by_sub
        if owner and owner != str(user.get("sub") or ""):
            raise HTTPException(status_code=403, detail="Not allowed to view this train job")
    return _job_to_response(row_to_state(row))
