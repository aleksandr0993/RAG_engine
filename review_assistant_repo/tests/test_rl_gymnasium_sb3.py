from __future__ import annotations

import pytest


@pytest.fixture()
def rl_enabled_client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'rlsb3.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    monkeypatch.setenv("ENABLE_RL_ENGINE", "true")
    monkeypatch.setenv("RL_MODELS_ROOT", str(data_dir / "rl_models"))

    from fastapi.testclient import TestClient

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


def test_rl_health_reports_stack_flags(client):
    data = client.get("/api/v1/rl/health").json()
    assert "gymnasium_available" in data
    assert "stable_baselines3_available" in data


def test_gymnasium_random_episode(rl_enabled_client):
    pytest.importorskip("gymnasium")
    resp = rl_enabled_client.post(
        "/api/v1/rl/episodes/run",
        json={
            "environment": "gymnasium_discrete",
            "gymnasium_env_id": "CartPole-v1",
            "policy": "random",
            "max_steps": 20,
            "seed": 0,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["environment"] == "gymnasium_discrete"
    assert len(body["steps"]) >= 1


def test_train_then_sb3_episode(rl_enabled_client):
    pytest.importorskip("gymnasium")
    pytest.importorskip("stable_baselines3")

    tr = rl_enabled_client.post(
        "/api/v1/rl/train",
        json={
            "env_id": "CartPole-v1",
            "algorithm": "ppo",
            "total_timesteps": 512,
            "seed": 1,
            "artefact_name": "test_cartpole_ppo",
        },
    )
    assert tr.status_code == 200, tr.text
    saved = tr.json()["saved_path"]

    ep = rl_enabled_client.post(
        "/api/v1/rl/episodes/run",
        json={
            "environment": "gymnasium_discrete",
            "gymnasium_env_id": "CartPole-v1",
            "policy": "sb3",
            "sb3_model_path": "test_cartpole_ppo.zip",
            "max_steps": 30,
            "seed": 2,
        },
    )
    assert ep.status_code == 200, ep.text
    assert ep.json()["policy"] == "sb3"
    assert saved  # path returned for debugging


def test_train_async_then_poll_completes(rl_enabled_client):
    import time

    pytest.importorskip("gymnasium")
    pytest.importorskip("stable_baselines3")

    acc = rl_enabled_client.post(
        "/api/v1/rl/train/async",
        json={
            "env_id": "CartPole-v1",
            "algorithm": "ppo",
            "total_timesteps": 384,
            "seed": 3,
            "artefact_name": "test_cartpole_async",
        },
    )
    assert acc.status_code == 202, acc.text
    job_id = acc.json()["job_id"]
    body = {}
    for _ in range(60):
        st = rl_enabled_client.get(f"/api/v1/rl/train/jobs/{job_id}")
        assert st.status_code == 200
        body = st.json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert body["status"] == "completed", body
    assert body.get("result") is not None
    assert body["result"]["saved_path"]
