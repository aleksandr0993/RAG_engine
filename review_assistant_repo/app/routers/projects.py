from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import tempfile
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.auth.deps import require_user_for_debug_routes, require_user_for_writes
from app.capture.metrics import capture_metrics
from app.config import get_settings
from app.db import get_db
from app.models import CriterionResult, Project, ProjectFile, ReviewJob
from app.schemas import (
    ArtifactDTO,
    AsyncReviewAccepted,
    CriterionResultDTO,
    GlobalCriterionRollupResponse,
    IterationChainResponse,
    IterationInsightsResponse,
    IterationMetricsResponse,
    ProjectFileDTO,
    ProjectResponse,
    RecentIterationMetricsResponse,
    RegionDTO,
    ReviewJobDTO,
    ReviewResponse,
    ReviewResultDTO,
    UploadResponse,
    VisualPreviewDTO,
    VisualSummaryDTO,
)
from app.services.capture_summary import build_capture_summary
from app.services.criteria_summary import build_criteria_execution_summary
from app.services.explorer import ProjectExplorerService
from app.services.iteration_chain import (
    build_iteration_chain_payload,
    build_iteration_insights_payload,
)
from app.services.iteration_metadata_quality import (
    run_metadata_backfill,
    run_metadata_quality_audit,
)
from app.services.iteration_metrics import (
    build_global_criterion_rollup_payload,
    build_iteration_metrics_payload,
    build_recent_iteration_metrics_payload,
)
from app.services.parser_summary import build_parser_summary
from app.services.review_metrics import review_metrics
from app.services.review_service import ReviewPipelineError, ReviewService
from app.services.review_tasks import run_review_background
from app.utils.practicum_input import normalize_practicum_input_channel

router = APIRouter(tags=["projects"])
logger = logging.getLogger(__name__)

_LIST_PROJECT_SOURCE_TYPES = frozenset({"ipynb", "sql", "pdf", "html", "datalens"})
_LIST_PROJECT_STATUSES = frozenset({"uploaded", "processing", "done", "failed"})

_JSON_CHANNEL_SCAN_CAP = 12_000


def _apply_keyset_after_cursor_desc(q, c_ts: datetime, c_id: str):
    """Строки после курсора при ORDER BY created_at DESC, id DESC."""
    return q.filter(
        or_(
            Project.created_at < c_ts,
            and_(Project.created_at == c_ts, Project.id < c_id),
        )
    )


def _encode_project_list_cursor(row: Project) -> str:
    ts = row.created_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    payload = json.dumps({"t": ts.isoformat(), "i": row.id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_project_list_cursor(raw: str) -> tuple[datetime, str]:
    s = raw.strip()
    if not s:
        raise ValueError("empty cursor")
    pad = "=" * (-len(s) % 4)
    try:
        blob = base64.urlsafe_b64decode(s + pad)
        data = json.loads(blob.decode())
        ts_s = data["t"]
        pid = data["i"]
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error, ValueError) as exc:
        raise ValueError("invalid cursor") from exc
    if not isinstance(ts_s, str) or not isinstance(pid, str):
        raise ValueError("invalid cursor shape")
    ct = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
    if ct.tzinfo is None:
        ct = ct.replace(tzinfo=UTC)
    return ct, pid


def _project_list_cursor_supported_db(db: Session, practicum_input_channel: str | None) -> bool:
    if practicum_input_channel is None:
        return True
    return db.get_bind().dialect.name in ("sqlite", "postgresql")


def _apply_project_column_filters(
    q,
    *,
    source_type: str | None,
    status: str | None,
):
    if source_type is not None:
        q = q.filter(Project.source_type == source_type)
    if status is not None:
        q = q.filter(Project.status == status)
    return q


def _fetch_projects_filtered(
    db: Session,
    *,
    practicum_input_channel: str | None,
    source_type: str | None,
    status: str | None,
    offset: int,
    limit: int,
    cursor: tuple[datetime, str] | None = None,
) -> list[Project]:
    """SQLite / PostgreSQL: JSON filter в БД; иные диалекты — скан с потолком (keyset только без JSON-канала)."""
    eff_offset = 0 if cursor is not None else offset
    q = _apply_project_column_filters(db.query(Project), source_type=source_type, status=status)
    if cursor is not None:
        q = _apply_keyset_after_cursor_desc(q, cursor[0], cursor[1])
    if practicum_input_channel:
        dialect_name = db.get_bind().dialect.name
        if dialect_name == "sqlite":
            q = q.filter(
                func.json_extract(Project.metadata_json, "$.practicum_input_channel") == practicum_input_channel
            )
            return q.order_by(Project.created_at.desc(), Project.id.desc()).offset(eff_offset).limit(limit).all()
        if dialect_name == "postgresql":
            q = q.filter(
                Project.metadata_json["practicum_input_channel"].as_string() == practicum_input_channel
            )
            return q.order_by(Project.created_at.desc(), Project.id.desc()).offset(eff_offset).limit(limit).all()
        assert cursor is None
        cap = min(offset + max(limit * 50, 500), _JSON_CHANNEL_SCAN_CAP)
        cand = (
            _apply_project_column_filters(db.query(Project), source_type=source_type, status=status)
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(cap)
            .all()
        )
        matched = [r for r in cand if (r.metadata_json or {}).get("practicum_input_channel") == practicum_input_channel]
        return matched[offset : offset + limit]
    return q.order_by(Project.created_at.desc(), Project.id.desc()).offset(eff_offset).limit(limit).all()


def _count_projects_filtered(
    db: Session,
    *,
    practicum_input_channel: str | None,
    source_type: str | None,
    status: str | None,
) -> tuple[int, bool]:
    """Число строк под теми же фильтрами, что у списка; (count, truncated)."""
    q = _apply_project_column_filters(db.query(Project), source_type=source_type, status=status)
    if practicum_input_channel:
        dialect_name = db.get_bind().dialect.name
        if dialect_name == "sqlite":
            q = q.filter(
                func.json_extract(Project.metadata_json, "$.practicum_input_channel") == practicum_input_channel
            )
            return q.count(), False
        if dialect_name == "postgresql":
            q = q.filter(
                Project.metadata_json["practicum_input_channel"].as_string() == practicum_input_channel
            )
            return q.count(), False
        cand = (
            _apply_project_column_filters(db.query(Project), source_type=source_type, status=status)
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(_JSON_CHANNEL_SCAN_CAP)
            .all()
        )
        n = sum(
            1
            for r in cand
            if (r.metadata_json or {}).get("practicum_input_channel") == practicum_input_channel
        )
        return n, len(cand) == _JSON_CHANNEL_SCAN_CAP
    return q.count(), False


def detect_source_type(filename: str | None, source_url: str | None) -> str:
    if source_url:
        return "datalens"
    if not filename:
        raise HTTPException(status_code=400, detail="File or source_url is required")

    suffix = Path(filename).suffix.lower()
    mapping = {
        ".ipynb": "ipynb",
        ".sql": "sql",
        ".pdf": "pdf",
        ".html": "html",
        ".htm": "html",
    }
    if suffix not in mapping:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
    return mapping[suffix]


def default_criteria_map_code(source_type: str) -> str:
    return {
        "ipynb": "notebook_practicum_v1",
        "sql": "sql_practicum_v1",
        "pdf": "dashboard_practicum_v1",
        "datalens": "datalens_practicum_v1",
        "html": "html_practicum_v1",
    }[source_type]


@router.post("/projects/upload", response_model=UploadResponse)
async def upload_project(
    file: UploadFile | None = File(default=None),
    source_url: str | None = Form(default=None),
    style_profile_code: str | None = Form(default=None),
    criteria_map_code: str | None = Form(default=None),
    review_training_project: str | None = Form(
        default=None,
        description="Slug matching JSONL source_project for project-training retrieval (optional)",
    ),
    practicum_input_channel: str | None = Form(
        default=None,
        description=(
            "Яндекс Практикум: пусто/auto — канал по расширению (.ipynb → jupyter); "
            "jupyter — явно ноутбук; revisor — из Ревизора (скачанный файл и т.д.)"
        ),
    ),
    previous_project_id: str | None = Form(
        default=None,
        description="UUID прошлой итерации сдачи (для проверки исправлений замечаний)",
    ),
    db: Session = Depends(get_db),
    _auth: Annotated[dict | None, Depends(require_user_for_writes)] = None,
):
    settings = get_settings()
    source_type = detect_source_type(file.filename if file else None, source_url)
    try:
        normalize_practicum_input_channel(practicum_input_channel, source_type=source_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tmp_file_path = None
    original_filename = file.filename if file else None
    if file:
        suffix = Path(file.filename or "unnamed").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            written = 0
            chunk_size = 65536
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    Path(tmp.name).unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="File exceeds maximum upload size")
                tmp.write(chunk)
            tmp_file_path = tmp.name

    service = ReviewService(db)
    try:
        project = service.upload_project(
            source_type=source_type,
            style_profile_code=style_profile_code or settings.default_style_profile,
            criteria_map_code=criteria_map_code or default_criteria_map_code(source_type),
            original_filename=original_filename,
            source_url=source_url,
            uploaded_file_path=tmp_file_path,
            review_training_project=review_training_project,
            practicum_input_channel=practicum_input_channel,
            previous_project_id=previous_project_id.strip() if previous_project_id else None,
        )
    except ValueError as exc:
        if tmp_file_path:
            Path(tmp_file_path).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if tmp_file_path:
        Path(tmp_file_path).unlink(missing_ok=True)

    return UploadResponse(project_id=project.id, status=project.status)


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(
        default=0,
        ge=0,
        le=100_000,
        description="Смещение для пагинации (после сортировки по created_at desc)",
    ),
    practicum_input_channel: str | None = Query(
        default=None,
        description="Фильтр по metadata_json.practicum_input_channel (jupyter, revisor, html, sql, …)",
    ),
    source_type: str | None = Query(
        default=None,
        description="Фильтр по projects.source_type (ipynb, sql, pdf, html, datalens)",
    ),
    status: str | None = Query(
        default=None,
        description="Фильтр по projects.status (uploaded, processing, done, failed)",
    ),
    cursor: str | None = Query(
        default=None,
        description="Keyset: значение из заголовка X-Next-Cursor предыдущего ответа (не сочетать с offset≠0)",
    ),
    include_total: bool = Query(
        default=True,
        description="Если false — без COUNT и без заголовков X-Total-Count* (дешевле при скролле/keyset)",
    ),
    db: Session = Depends(get_db),
):
    if source_type is not None and source_type not in _LIST_PROJECT_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source_type: {source_type!r}; expected one of {sorted(_LIST_PROJECT_SOURCE_TYPES)}",
        )
    if status is not None and status not in _LIST_PROJECT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {status!r}; expected one of {sorted(_LIST_PROJECT_STATUSES)}",
        )
    cur: tuple[datetime, str] | None = None
    if cursor is not None and cursor.strip():
        if offset != 0:
            raise HTTPException(
                status_code=400,
                detail="Do not pass both cursor and a non-zero offset; use cursor from X-Next-Cursor only.",
            )
        if not _project_list_cursor_supported_db(db, practicum_input_channel):
            raise HTTPException(
                status_code=422,
                detail=(
                    "cursor pagination is not supported for practicum_input_channel filter on this database "
                    "dialect; use offset/limit or SQLite/PostgreSQL."
                ),
            )
        try:
            cur = _decode_project_list_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid cursor") from exc

    if include_total:
        total, total_truncated = _count_projects_filtered(
            db,
            practicum_input_channel=practicum_input_channel,
            source_type=source_type,
            status=status,
        )
        response.headers["X-Total-Count"] = str(total)
        if total_truncated:
            response.headers["X-Total-Count-Truncated"] = "true"

    fetch_limit = limit + 1
    rows = _fetch_projects_filtered(
        db,
        practicum_input_channel=practicum_input_channel,
        source_type=source_type,
        status=status,
        offset=offset,
        limit=fetch_limit,
        cursor=cur,
    )
    if len(rows) > limit:
        response.headers["X-Next-Cursor"] = _encode_project_list_cursor(rows[limit - 1])
        rows = rows[:limit]

    return [
        ProjectResponse(
            id=row.id,
            source_type=row.source_type,
            original_filename=row.original_filename,
            source_url=row.source_url,
            status=row.status,
            style_profile_code=row.style_profile_code,
            criteria_map_code=row.criteria_map_code,
            final_verdict=row.final_verdict,
            review_markdown=row.review_markdown,
            metadata_json=row.metadata_json,
        )
        for row in rows
    ]


@router.get("/projects/iteration_metrics/recent", response_model=RecentIterationMetricsResponse)
def get_recent_iteration_metrics(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Projects with iteration-fix resolution rows, ordered by last activity (dashboard)."""
    payload = build_recent_iteration_metrics_payload(db, limit=limit)
    return RecentIterationMetricsResponse(**payload)


@router.get("/projects/iteration_metrics/by_criterion", response_model=GlobalCriterionRollupResponse)
def get_global_iteration_criterion_rollup(
    max_rows: int = Query(
        default=20_000,
        ge=100,
        le=100_000,
        description="Max resolution rows scanned (newest first); ignored when full_scan=true",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Top N criteria by row count",
    ),
    full_scan: bool = Query(
        default=False,
        description="Scan up to 500k newest rows (full table if smaller)",
    ),
    db: Session = Depends(get_db),
):
    """Global sampled rollup of iteration_issue_resolutions by criterion_code (admin dashboard)."""
    payload = build_global_criterion_rollup_payload(
        db, max_rows=max_rows, limit_criteria=limit, full_scan=full_scan
    )
    return GlobalCriterionRollupResponse(**payload)


@router.get("/debug/practicum_stats")
def debug_practicum_stats(
    limit: int = Query(default=500, ge=1, le=5000),
    source_type: str | None = Query(default=None, description="Учитывать только проекты с данным source_type"),
    status: str | None = Query(default=None, description="Учитывать только проекты с данным status"),
    practicum_input_channel: str | None = Query(
        default=None,
        description="Как у GET /projects: только проекты с metadata_json.practicum_input_channel",
    ),
    db: Session = Depends(get_db),
    _debug_auth: Annotated[dict | None, Depends(require_user_for_debug_routes)] = None,
):
    """Сводка по последним проектам: канал Практикума и уверенность Revisor-HTML (для отчётности)."""
    if source_type is not None and source_type not in _LIST_PROJECT_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source_type: {source_type!r}; expected one of {sorted(_LIST_PROJECT_SOURCE_TYPES)}",
        )
    if status is not None and status not in _LIST_PROJECT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {status!r}; expected one of {sorted(_LIST_PROJECT_STATUSES)}",
        )
    if practicum_input_channel:
        rows = _fetch_projects_filtered(
            db,
            practicum_input_channel=practicum_input_channel,
            source_type=source_type,
            status=status,
            offset=0,
            limit=limit,
        )
    else:
        sq = _apply_project_column_filters(db.query(Project), source_type=source_type, status=status)
        rows = sq.order_by(Project.created_at.desc(), Project.id.desc()).limit(limit).all()
    by_channel: Counter[str] = Counter()
    by_conf: Counter[str] = Counter()
    by_st: Counter[str] = Counter()
    by_proj_status: Counter[str] = Counter()
    by_verdict: Counter[str] = Counter()
    detected_yes = 0
    for row in rows:
        m = row.metadata_json or {}
        by_channel[str(m.get("practicum_input_channel") or "unset")] += 1
        by_conf[str(m.get("practicum_revisor_detection_confidence") or "n/a")] += 1
        by_st[row.source_type] += 1
        by_proj_status[row.status] += 1
        by_verdict[str(row.final_verdict or "unset")] += 1
        if m.get("practicum_revisor_html_detected"):
            detected_yes += 1
    return {
        "sample_size": len(rows),
        "filters": {
            "source_type": source_type,
            "status": status,
            "practicum_input_channel": practicum_input_channel,
        },
        "by_practicum_input_channel": dict(sorted(by_channel.items())),
        "by_revisor_html_confidence": dict(sorted(by_conf.items())),
        "by_source_type": dict(sorted(by_st.items())),
        "by_project_status": dict(sorted(by_proj_status.items())),
        "by_final_verdict": dict(sorted(by_verdict.items())),
        "practicum_revisor_html_detected_count": detected_yes,
    }


@router.get("/debug/metadata_quality_audit")
def debug_metadata_quality_audit(
    sample_limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    _debug_auth: Annotated[dict | None, Depends(require_user_for_debug_routes)] = None,
):
    """Sample recent projects and count iteration_fix_summary metadata issues (read-only)."""
    return run_metadata_quality_audit(db, sample_limit=sample_limit)


@router.post("/debug/metadata_backfill")
def debug_metadata_backfill(
    project_limit: int = Query(default=500, ge=1, le=5000),
    resolution_limit: int = Query(default=5000, ge=1, le=50_000),
    db: Session = Depends(get_db),
    _debug_auth: Annotated[dict | None, Depends(require_user_for_debug_routes)] = None,
):
    """
    Normalize iteration_fix_summary / notebook_execution on recent projects and detail_json on
    recent iteration_issue_resolutions; commits once. Increments process counters on /metrics.
    """
    return run_metadata_backfill(db, project_limit=project_limit, resolution_limit=resolution_limit)


@router.post("/projects/{project_id}/review", response_model=ReviewResponse)
def run_review(project_id: str, db: Session = Depends(get_db)):
    existing = db.get(Project, project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")
    if existing.status == "processing":
        raise HTTPException(
            status_code=409,
            detail="Review already in progress (try GET /projects/{id} or POST .../review/async when idle).",
        )
    active_job = (
        db.query(ReviewJob)
        .filter(ReviewJob.project_id == project_id, ReviewJob.status.in_(["queued", "running"]))
        .first()
    )
    if active_job:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A review job is already active for this project",
                "job_id": active_job.id,
            },
        )
    service = ReviewService(db)
    try:
        project = service.run_review(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewPipelineError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ReviewResponse(project_id=project.id, status=project.status, final_verdict=project.final_verdict)


@router.post(
    "/projects/{project_id}/review/async",
    response_model=AsyncReviewAccepted,
    status_code=202,
)
def run_review_async(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Queue review in a background worker. Returns immediately with 202.
    The project row is marked ``processing`` before the worker starts to avoid duplicate jobs.
    """
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == "processing":
        raise HTTPException(status_code=409, detail="Review already in progress")
    active = (
        db.query(ReviewJob)
        .filter(ReviewJob.project_id == project_id, ReviewJob.status.in_(["queued", "running"]))
        .first()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail={"message": "Review job already active", "job_id": active.id},
        )

    job_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    job = ReviewJob(
        id=job_id,
        project_id=project_id,
        status="queued",
        created_at=now,
        updated_at=now,
        detail_json={},
    )
    db.add(job)
    project.status = "processing"
    db.commit()

    background_tasks.add_task(run_review_background, project_id, job_id)
    return AsyncReviewAccepted(
        project_id=project.id,
        job_id=job_id,
        message=(
            "Review started in background. Poll GET /api/v1/projects/{id}/review/jobs/{job_id}, "
            "GET /api/v1/projects/{id}, or WebSocket /api/v1/ws/projects/{id}/status."
        ),
    )


@router.get("/projects/{project_id}/review/jobs/{job_id}", response_model=ReviewJobDTO)
def get_review_job(project_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.get(ReviewJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Review job not found")
    status = cast(Literal["queued", "running", "done", "failed", "timeout"], job.status)
    return ReviewJobDTO(
        id=job.id,
        project_id=job.project_id,
        status=status,
        error_message=job.error_message,
        detail_json=job.detail_json or {},
    )


@router.websocket("/ws/projects/{project_id}/status")
async def project_status_websocket(websocket: WebSocket, project_id: str):
    """Push current ``projects.status`` periodically until the client disconnects."""
    await websocket.accept()
    from app.db import get_session_local

    try:
        while True:
            def _read() -> str | None:
                SessionLocal = get_session_local()
                session = SessionLocal()
                try:
                    row = session.get(Project, project_id)
                    return row.status if row else None
                finally:
                    session.close()

            status = await asyncio.to_thread(_read)
            await websocket.send_json({"project_id": project_id, "status": status})
            await asyncio.sleep(1.5)
    except WebSocketDisconnect:
        logger.debug("WS status client disconnected for %s", project_id)
    except Exception:
        logger.exception("WebSocket status error for %s", project_id)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(
        id=project.id,
        source_type=project.source_type,
        original_filename=project.original_filename,
        source_url=project.source_url,
        status=project.status,
        style_profile_code=project.style_profile_code,
        criteria_map_code=project.criteria_map_code,
        final_verdict=project.final_verdict,
        review_markdown=project.review_markdown,
        metadata_json=project.metadata_json,
    )


@router.get("/projects/{project_id}/iteration_chain", response_model=IterationChainResponse)
def get_iteration_chain(project_id: str, db: Session = Depends(get_db)):
    """Chain of resubmissions from root iteration to this project (ordered root → leaf)."""
    payload = build_iteration_chain_payload(db, project_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Project not found")
    return IterationChainResponse(**payload)


@router.get("/projects/{project_id}/iteration_insights", response_model=IterationInsightsResponse)
def get_iteration_insights(project_id: str, db: Session = Depends(get_db)):
    """Histograms over stored iteration resolutions and latest iteration_fix_summary metadata."""
    payload = build_iteration_insights_payload(db, project_id)
    if not payload.get("project_id"):
        raise HTTPException(status_code=404, detail="Project not found")
    return IterationInsightsResponse(**payload)


@router.get("/projects/{project_id}/iteration_metrics", response_model=IterationMetricsResponse)
def get_iteration_metrics(project_id: str, db: Session = Depends(get_db)):
    """Rates and criterion breakdown for the anchor project and full resubmit chain."""
    payload = build_iteration_metrics_payload(db, project_id)
    if not payload.get("anchor_project_id"):
        raise HTTPException(status_code=404, detail="Project not found")
    return IterationMetricsResponse(**payload)


@router.get("/projects/{project_id}/findings", response_model=list[CriterionResultDTO])
def get_findings(
    project_id: str,
    severity: str | None = Query(default=None),
    criterion_code: str | None = Query(default=None),
    source_stage: str | None = Query(default=None),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = db.query(CriterionResult).filter(CriterionResult.project_id == project.id).all()
    out: list[CriterionResultDTO] = []
    for row in rows:
        if severity and row.severity != severity:
            continue
        if criterion_code and row.criterion_code != criterion_code:
            continue
        if source_stage:
            st = (row.metadata_json or {}).get("source_stage")
            if st != source_stage:
                continue
        if category and (row.metadata_json or {}).get("category") != category:
            continue
        meta = row.metadata_json or {}
        out.append(
            CriterionResultDTO(
                criterion_code=row.criterion_code,
                severity=row.severity,
                status=cast(Literal["pass", "warn", "fail", "unknown"], row.status),
                confidence=row.confidence,
                anchor_artifact_id=row.anchor_artifact_id,
                evidence_json=row.evidence_json,
                generated_comment=row.generated_comment,
                metadata_json=meta,
                category=meta.get("category"),
            )
        )
    return out


@router.get("/projects/{project_id}/review_result", response_model=ReviewResultDTO)
def get_review_result(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = db.query(CriterionResult).filter(CriterionResult.project_id == project.id).all()
    findings = []
    for row in rows:
        meta = row.metadata_json or {}
        findings.append(
            CriterionResultDTO(
                criterion_code=row.criterion_code,
                severity=row.severity,
                status=cast(Literal["pass", "warn", "fail", "unknown"], row.status),
                confidence=row.confidence,
                anchor_artifact_id=row.anchor_artifact_id,
                evidence_json=row.evidence_json,
                generated_comment=row.generated_comment,
                metadata_json=meta,
                category=meta.get("category"),
            )
        )
    meta = project.metadata_json or {}
    return ReviewResultDTO(
        project_id=project.id,
        final_verdict=project.final_verdict,
        review_markdown=project.review_markdown,
        findings=findings,
        iteration_fix_summary=meta.get("iteration_fix_summary"),
    )


@router.get("/projects/{project_id}/files", response_model=list[ProjectFileDTO])
def list_project_files(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = db.query(ProjectFile).filter(ProjectFile.project_id == project.id).all()
    return [
        ProjectFileDTO(
            id=row.id,
            kind=row.kind,
            filename=Path(row.storage_path).name,
            mime_type=row.mime_type,
            page_no=row.page_no,
            metadata_json=row.metadata_json,
        )
        for row in rows
    ]


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactDTO])
def list_project_artifacts(
    project_id: str,
    artifact_type: str | None = Query(default=None),
    region_kind: str | None = Query(default=None),
    page_no: int | None = Query(default=None),
    tag: str | None = Query(default=None),
    section_name: str | None = Query(default=None),
    source_type: str | None = Query(default=None, description="image|text — metadata.source_type"),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    explorer = ProjectExplorerService(db)
    try:
        return explorer.list_artifacts(
            project_id,
            artifact_type=artifact_type,
            region_kind=region_kind,
            page_no=page_no,
            tag=tag,
            section_name=section_name,
            source_type=source_type,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/artifacts/{artifact_id}", response_model=ArtifactDTO)
def get_project_artifact(project_id: str, artifact_id: str, db: Session = Depends(get_db)):
    explorer = ProjectExplorerService(db)
    try:
        return explorer.get_artifact(project_id, artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/regions", response_model=list[RegionDTO])
def list_project_regions(
    project_id: str,
    region_kind: str | None = Query(default=None),
    page_no: int | None = Query(default=None),
    source_type: str | None = Query(default=None, description="image or text"),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    if source_type is not None and source_type not in ("", "image", "text"):
        raise HTTPException(status_code=400, detail="source_type must be image or text")
    explorer = ProjectExplorerService(db)
    try:
        return explorer.list_regions(project_id, region_kind=region_kind, page_no=page_no, source_type=source_type, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/visual_summary", response_model=VisualSummaryDTO)
def get_visual_summary(project_id: str, db: Session = Depends(get_db)):
    explorer = ProjectExplorerService(db)
    try:
        return explorer.build_visual_summary(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/visual_preview", response_model=VisualPreviewDTO)
def get_visual_preview(
    project_id: str,
    page_no: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    explorer = ProjectExplorerService(db)
    try:
        return explorer.build_visual_preview(project_id, page_no=page_no)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/debug/capture_summary")
def debug_capture_summary(
    project_id: str,
    db: Session = Depends(get_db),
    _debug_auth: Annotated[dict | None, Depends(require_user_for_debug_routes)] = None,
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    meta = project.metadata_json or {}
    return build_capture_summary(meta)


@router.get("/projects/{project_id}/debug/parser_summary")
def debug_parser_summary(
    project_id: str,
    db: Session = Depends(get_db),
    _debug_auth: Annotated[dict | None, Depends(require_user_for_debug_routes)] = None,
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    meta = project.metadata_json or {}
    return meta.get("parser_summary") or build_parser_summary(meta, project.source_type)


@router.get("/debug/capture_metrics")
def debug_global_capture_metrics(
    _debug_auth: Annotated[dict | None, Depends(require_user_for_debug_routes)] = None,
):
    """Process-wide capture pool metrics (not tied to a single project)."""
    snap = capture_metrics.snapshot()
    return {
        "submitted": snap.submitted,
        "completed_ok": snap.completed_ok,
        "completed_fail": snap.completed_fail,
        "total_duration_ms": snap.total_duration_ms,
        "last_duration_ms": snap.last_duration_ms,
        "pool_timeouts": snap.pool_timeouts,
        "last_error": snap.last_error,
        "updated_at_epoch": snap.updated_at_epoch,
    }


@router.get("/debug/review_metrics")
def debug_global_review_metrics(
    _debug_auth: Annotated[dict | None, Depends(require_user_for_debug_routes)] = None,
):
    """Process-wide review pipeline counters (sync + async)."""
    snap = review_metrics.snapshot()
    return {
        "submitted": snap.submitted,
        "completed_ok": snap.completed_ok,
        "completed_fail": snap.completed_fail,
        "total_duration_ms": snap.total_duration_ms,
        "last_duration_ms": snap.last_duration_ms,
        "low_confidence_findings_total": snap.low_confidence_findings_total,
        "last_error": snap.last_error,
        "updated_at_epoch": snap.updated_at_epoch,
        "latency_p50_ms": review_metrics.percentile_ms(50.0),
        "latency_p95_ms": review_metrics.percentile_ms(95.0),
    }


@router.get("/projects/{project_id}/debug/criteria_summary")
def debug_criteria_summary(
    project_id: str,
    db: Session = Depends(get_db),
    _debug_auth: Annotated[dict | None, Depends(require_user_for_debug_routes)] = None,
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    meta = project.metadata_json or {}
    if meta.get("criteria_execution_summary"):
        return meta["criteria_execution_summary"]
    rows = db.query(CriterionResult).filter(CriterionResult.project_id == project.id).all()
    return build_criteria_execution_summary(rows)


@router.get("/projects/{project_id}/debug/review_timeline")
def debug_review_timeline(
    project_id: str,
    db: Session = Depends(get_db),
    _debug_auth: Annotated[dict | None, Depends(require_user_for_debug_routes)] = None,
):
    """Pipeline stage durations and source-stage breakdown from last completed review metadata."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    meta = project.metadata_json or {}
    return {
        "review_pipeline_timeline": meta.get("review_pipeline_timeline") or [],
        "criteria_execution_summary": meta.get("criteria_execution_summary") or {},
        "quality_summary": meta.get("quality_summary") or {},
    }


@router.get("/projects/{project_id}/files/{file_id}")
def download_project_file(project_id: str, file_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    row = db.get(ProjectFile, file_id)
    if not row or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="Project file not found")
    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found on disk")
    return FileResponse(path, filename=path.name)


@router.get("/projects/{project_id}/export/reviewed_notebook")
def download_reviewed_notebook(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    reviewed_file = next((f for f in project.files if f.kind == "reviewed"), None)
    if not reviewed_file:
        raise HTTPException(status_code=404, detail="Reviewed notebook not found")

    return FileResponse(reviewed_file.storage_path, media_type="application/x-ipynb+json", filename="reviewed.ipynb")
