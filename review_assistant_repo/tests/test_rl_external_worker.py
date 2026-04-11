from __future__ import annotations

import pytest


def test_async_external_worker_leaves_job_accepted(tmp_path, monkeypatch):
    pytest.importorskip("stable_baselines3")

    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ew.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    monkeypatch.setenv("ENABLE_RL_ENGINE", "true")
    monkeypatch.setenv("RL_TRAIN_ASYNC_EXECUTOR", "external_worker")
    monkeypatch.setenv("RL_MODELS_ROOT", str(data_dir / "rl_models"))

    from fastapi.testclient import TestClient

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        acc = client.post(
            "/api/v1/rl/train/async",
            json={
                "env_id": "CartPole-v1",
                "algorithm": "ppo",
                "total_timesteps": 100,
                "seed": 0,
                "artefact_name": "ext_worker_smoke",
            },
        )
        assert acc.status_code == 202, acc.text
        assert "external worker" in acc.json()["message"].lower()
        job_id = acc.json()["job_id"]
        st = client.get(f"/api/v1/rl/train/jobs/{job_id}")
        assert st.status_code == 200
        assert st.json()["status"] == "accepted"
