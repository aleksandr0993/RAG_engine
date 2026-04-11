from unittest.mock import patch

import pytest

from app.capture.datalens import DataLensCaptureService


def test_capture_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv("ENABLE_BROWSER_CAPTURE", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    svc = DataLensCaptureService()
    out = svc.capture("https://datalens.yandex/x", capture_dir="/tmp/ignored")
    assert out.get("capture_skipped") is True
    assert out.get("capture_status") == "disabled"
    assert out.get("number_of_screenshots") == 0


def test_capture_failure_does_not_raise(monkeypatch, tmp_path):
    pytest.importorskip("playwright")
    monkeypatch.setenv("ENABLE_BROWSER_CAPTURE", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    def boom(*args, **kwargs):
        raise RuntimeError("no browser")

    with patch("playwright.sync_api.sync_playwright", side_effect=boom):
        svc = DataLensCaptureService()
        out = svc.capture("https://datalens.yandex/x", capture_dir=str(tmp_path))
    assert "capture_failed" in (out.get("capture_status") or "") or out.get("capture_errors")
