from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine, pool

from alembic import context

# Repo root on sys.path (alembic.ini prepend_sys_path = . when cwd is repo root)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import models as _models  # noqa: E402, F401 — register tables
from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402

config = context.config
logger = logging.getLogger("alembic.env")
target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = get_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    connectable = create_engine(url, poolclass=pool.NullPool, future=True, connect_args=connect_args)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
