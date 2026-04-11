from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register mappers
from app.db import Base
from app.models import RLTrainJob
from app.rl.schemas import RLTrainRequest
from app.rl.train_jobs import (
    RLTrainConcurrentLimitError,
    claim_next_accepted_train_job,
    register_train_job_db,
)


def test_register_train_job_blocks_same_artefact_until_done(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rlj.sqlite'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        settings = type(
            "S",
            (),
            {
                "rl_train_max_concurrent": 10,
                "rl_train_max_timesteps": 1_000_000,
                "rl_models_root": str(tmp_path / "models"),
            },
        )()
        name = "unit_dup_artefact_xyz"
        req = RLTrainRequest(artefact_name=name, total_timesteps=100)
        j1 = register_train_job_db(db, req, settings=settings, created_by_sub=None)
        assert j1
        j2 = register_train_job_db(db, req, settings=settings, created_by_sub=None)
        assert j2 is None
    finally:
        db.close()


def test_concurrent_limit_register(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rlj2.sqlite'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        settings = type(
            "S",
            (),
            {
                "rl_train_max_concurrent": 1,
                "rl_train_max_timesteps": 1_000_000,
                "rl_models_root": str(tmp_path / "m"),
            },
        )()
        r1 = RLTrainRequest(artefact_name="a1.zip", total_timesteps=100)
        r2 = RLTrainRequest(artefact_name="a2.zip", total_timesteps=100)
        assert register_train_job_db(db, r1, settings=settings, created_by_sub=None)
        with pytest.raises(RLTrainConcurrentLimitError):
            register_train_job_db(db, r2, settings=settings, created_by_sub=None)
    finally:
        db.close()


def test_claim_next_accepted_marks_running(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'claim.sqlite'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        settings = type(
            "S",
            (),
            {
                "rl_train_max_concurrent": 5,
                "rl_train_max_timesteps": 1_000_000,
                "rl_models_root": str(tmp_path / "m"),
            },
        )()
        req = RLTrainRequest(artefact_name="claim_test", total_timesteps=100)
        jid = register_train_job_db(db, req, settings=settings, created_by_sub=None)
        assert jid
        db2 = sessionmaker(bind=engine)()
        try:
            claimed = claim_next_accepted_train_job(db2)
            assert claimed == jid
            row = db2.get(RLTrainJob, jid)
            assert row is not None
            assert row.status == "running"
        finally:
            db2.close()
    finally:
        db.close()


def test_claim_returns_none_when_no_accepted(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.sqlite'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        assert claim_next_accepted_train_job(db) is None
    finally:
        db.close()
