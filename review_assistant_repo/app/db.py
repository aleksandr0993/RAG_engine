from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


def _sqlite_enable_foreign_keys(dbapi_connection, _connection_record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def init_db(database_url: str) -> None:
    global _engine, _SessionLocal
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, future=True, echo=False, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        event.listen(_engine, "connect", _sqlite_enable_foreign_keys)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def get_engine():
    if _engine is None:
        raise RuntimeError("Database engine is not initialized")
    return _engine


def get_session_local():
    if _SessionLocal is None:
        raise RuntimeError("Session maker is not initialized")
    return _SessionLocal


def get_db() -> Generator:
    session_local = get_session_local()
    db = session_local()
    try:
        yield db
    finally:
        db.close()
