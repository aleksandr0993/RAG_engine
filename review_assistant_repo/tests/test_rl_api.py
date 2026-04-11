def test_rl_health_disabled_by_default(client):
    resp = client.get("/api/v1/rl/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["status"] == "disabled"
    assert "gymnasium_available" in data
    assert "stable_baselines3_available" in data
    assert "rl_train_async_executor" in data


def test_rl_episode_requires_enable(client):
    resp = client.post("/api/v1/rl/episodes/run", json={"environment": "toy_bandit", "policy": "random"})
    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()


def test_rl_episode_toy_bandit_random_enabled(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'rl.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    monkeypatch.setenv("ENABLE_RL_ENGINE", "true")

    from fastapi.testclient import TestClient

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/rl/episodes/run",
            json={
                "environment": "toy_bandit",
                "policy": "random",
                "max_steps": 5,
                "seed": 7,
                "toy_bandit_arms": [0.1, 0.4, 0.9],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["environment"] == "toy_bandit"
        assert body["policy"] == "random"
        assert body["metadata"]["executed_steps"] >= 1
        assert len(body["steps"]) >= 1
