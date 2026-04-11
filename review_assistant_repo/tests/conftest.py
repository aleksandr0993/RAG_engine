import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    # Static review only in tests (avoids kernel / CI flakes); execution can be enabled per-test.
    monkeypatch.setenv("ENABLE_NOTEBOOK_EXECUTION", "false")

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def client_small_upload(tmp_path, monkeypatch):
    """App with a very small MAX_UPLOAD_BYTES for 413 tests."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test2.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "20")

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
