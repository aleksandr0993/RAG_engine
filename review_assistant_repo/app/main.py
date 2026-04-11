import logging
from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from alembic import command
from app.config import get_settings
from app.db import Base, get_engine, init_db
from app.routers.assignments import router as assignments_router
from app.routers.changelog import router as changelog_router
from app.routers.config import router as config_router
from app.routers.health import router as health_router
from app.routers.projects import router as projects_router
from app.routers.rl import router as rl_router
from app.routers.student_assistant import router as student_assistant_router

log = logging.getLogger(__name__)

_PAGINATION_EXPOSE_HEADERS = (
    "X-Total-Count",
    "X-Total-Count-Truncated",
    "X-Next-Cursor",
)


def _cors_origins(settings) -> list[str]:
    return [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]


def _apply_schema(settings) -> None:
    """Prefer Alembic migrations; fall back to create_all for local/dev resilience."""
    import app.models  # noqa: F401 — ensure metadata is complete

    engine = get_engine()
    if not settings.use_alembic_migrations:
        Base.metadata.create_all(bind=engine)
        return
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    if not alembic_ini.is_file():
        log.warning("alembic.ini missing, using create_all")
        Base.metadata.create_all(bind=engine)
        return
    try:
        cfg = Config(str(alembic_ini))
        command.upgrade(cfg, "head")
    except Exception as exc:
        log.warning("Alembic upgrade failed (%s); falling back to create_all", exc)
        Base.metadata.create_all(bind=engine)


def create_app() -> FastAPI:
    logging.getLogger("app.capture").setLevel(logging.INFO)

    settings = get_settings()
    Path(settings.files_root).mkdir(parents=True, exist_ok=True)
    Path(settings.exports_root).mkdir(parents=True, exist_ok=True)
    if settings.enable_rl_engine:
        Path(settings.rl_models_root).mkdir(parents=True, exist_ok=True)

    init_db(settings.database_url)
    _apply_schema(settings)

    app = FastAPI(title="Review Assistant Practicum", version="0.9.10")
    cors_origins = _cors_origins(settings)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=list(_PAGINATION_EXPOSE_HEADERS),
        )
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(changelog_router, prefix="/api/v1")
    app.include_router(config_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(assignments_router, prefix="/api/v1")
    app.include_router(rl_router, prefix="/api/v1")
    app.include_router(student_assistant_router, prefix="/api/v1")
    return app


app = create_app()
