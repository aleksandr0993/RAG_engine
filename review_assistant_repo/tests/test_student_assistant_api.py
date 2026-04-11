from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client_course_kb(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    kb = tmp_path / "course_kb"
    kb.mkdir(parents=True)
    (kb / "faq.md").write_text(
        "Дедлайн сдачи SQL-проекта: каждый четверг до 18:00.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'assistant.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    monkeypatch.setenv("STUDENT_COURSE_KB_DIR", str(kb))
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as tc:
        yield tc


def test_assistant_chat_project_and_course_kb(client_course_kb: TestClient):
    sample_path = Path("examples/sample_query.sql")
    with sample_path.open("rb") as f:
        up = client_course_kb.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query.sql", f, "application/sql")},
        )
    assert up.status_code == 200
    project_id = up.json()["project_id"]

    ar = client_course_kb.post(f"/api/v1/projects/{project_id}/review/async")
    assert ar.status_code == 202

    r1 = client_course_kb.post(
        f"/api/v1/projects/{project_id}/assistant/chat",
        json={"message": "Какой дедлайн у SQL-проекта?"},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    assert "четверг" in body1["answer"].lower() or "18" in body1["answer"]
    kinds = {s["source_kind"] for s in body1["sources"]}
    assert "course_base" in kinds

    r2 = client_course_kb.post(
        f"/api/v1/projects/{project_id}/assistant/chat",
        json={"message": "Где в запросе считается ctr?"},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    joined = body2["answer"].lower()
    assert "ctr" in joined or any("ctr" in s["excerpt"].lower() for s in body2["sources"])
    assert any(s["source_kind"] == "project_doc" for s in body2["sources"])


def test_assistant_unknown_project(client_course_kb: TestClient):
    bad = client_course_kb.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/assistant/chat",
        json={"message": "test"},
    )
    assert bad.status_code == 404


def test_assistant_disabled_returns_404(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'off.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    monkeypatch.setenv("STUDENT_ASSISTANT_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        sample_path = Path("examples/sample_query.sql")
        with sample_path.open("rb") as f:
            up = client.post(
                "/api/v1/projects/upload",
                files={"file": ("sample_query.sql", f, "application/sql")},
            )
        pid = up.json()["project_id"]
        r = client.post(
            f"/api/v1/projects/{pid}/assistant/chat",
            json={"message": "hi"},
        )
        assert r.status_code == 404
