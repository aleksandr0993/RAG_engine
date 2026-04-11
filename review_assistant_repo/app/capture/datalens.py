from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from app.capture.datalens_scenario import run_datalens_capture_scenario
from app.capture.metrics import capture_metrics
from app.capture.pool import run_capture_task
from app.config import get_settings

_logger = logging.getLogger("app.capture.datalens")

_ALLOWED_CAPTURE_SCHEMES = frozenset({"https"})
# Hosts under Yandex DataLens / Yandex Cloud DataLens (SSRF mitigation).
_ALLOWED_CAPTURE_HOST_RE = re.compile(
    r"(^|\.)datalens\.(yandex|yandexcloud)(\.|$)",
    re.IGNORECASE,
)


def _validate_capture_url(source_url: str) -> None:
    settings = get_settings()
    if not settings.datalens_url_allowlist_enabled:
        return
    parsed = urlparse(source_url)
    if parsed.scheme.lower() not in _ALLOWED_CAPTURE_SCHEMES:
        raise ValueError(f"Capture URL scheme not allowed: {parsed.scheme!r}")
    netloc = (parsed.netloc or "").lower().split("@")[-1]  # strip userinfo if any
    if not netloc or not _ALLOWED_CAPTURE_HOST_RE.search(netloc):
        raise ValueError(f"Capture URL host not in allowlist: {parsed.netloc!r}")


def _nav_labels_from_step_log(step_log: list[dict]) -> list[str]:
    labels: list[str] = []
    for entry in step_log:
        if not str(entry.get("step_id", "")).startswith("tab_interaction_"):
            continue
        d = (entry.get("detail") or "").strip()
        if d and d not in labels and len(d) < 100:
            labels.append(d)
    return labels[:20]


def _execute_playwright_capture(source_url: str, capture_dir: str) -> dict:
    """Runs inside worker thread when pool enabled. Returns capture result dict."""
    settings = get_settings()
    _validate_capture_url(source_url)
    parsed = urlparse(source_url)
    domain = parsed.netloc.lower()
    path_segments = [seg for seg in parsed.path.split("/") if seg]
    capture_errors: list[str] = []
    t_wall = time.perf_counter()

    Path(capture_dir).mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    screenshot_paths: list[str] = []
    step_log: list[dict] = []
    title = ""
    body_text = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            page.set_default_timeout(settings.browser_capture_timeout_ms)

            screenshot_paths, step_log, scen_errors = run_datalens_capture_scenario(
                page,
                source_url,
                Path(capture_dir),
                navigation_timeout_ms=settings.browser_capture_timeout_ms,
                settle_after_load_ms=settings.datalens_settle_after_load_ms,
                tab_settle_ms=settings.datalens_tab_settle_ms,
                max_tab_screenshots=settings.datalens_max_tab_screenshots,
                goto_max_retries=settings.datalens_goto_max_retries,
                tab_click_max_retries=settings.datalens_tab_click_max_retries,
                step_retry_base_ms=settings.datalens_step_retry_base_ms,
            )
            capture_errors.extend(scen_errors)

            try:
                title = page.title()
            except Exception as exc:
                capture_errors.append(f"title_final:{type(exc).__name__}")
            try:
                body_text = page.locator("body").inner_text(timeout=5000) or ""
            except Exception as exc:
                capture_errors.append(f"body_final:{type(exc).__name__}")
        finally:
            browser.close()

    wall_ms = (time.perf_counter() - t_wall) * 1000
    text_fragments = [title, body_text[:4000], domain, *path_segments]
    scrubbed = re.sub(r"\s+", " ", body_text).strip()
    discovered_tabs = _nav_labels_from_step_log(step_log)

    return {
        "source_url": source_url,
        "domain": domain,
        "path_segments": path_segments,
        "capture_available": True,
        "capture_skipped": False,
        "capture_status": "captured",
        "capture_method": "playwright",
        "screenshot_paths": screenshot_paths,
        "title": title,
        "text_fragments": text_fragments,
        "loaded_ok": bool(screenshot_paths),
        "number_of_screenshots": len(screenshot_paths),
        "discovered_tabs": discovered_tabs,
        "extracted_text_length": len(scrubbed),
        "capture_errors": capture_errors,
        "generated_files": [],
        "capture_step_log": step_log,
        "capture_wall_duration_ms": round(wall_ms, 2),
    }


class DataLensCaptureService:
    def capture(self, source_url: str, capture_dir: str | None = None) -> dict:
        settings = get_settings()
        parsed = urlparse(source_url)
        domain = parsed.netloc.lower()
        path_segments = [seg for seg in parsed.path.split("/") if seg]

        capture_errors: list[str] = []
        base_payload: dict = {
            "source_url": source_url,
            "domain": domain,
            "path_segments": path_segments,
            "capture_available": False,
            "capture_status": "skipped",
            "capture_method": "none",
            "capture_skipped": True,
            "screenshot_paths": [],
            "title": None,
            "text_fragments": [domain, *path_segments],
            "loaded_ok": False,
            "number_of_screenshots": 0,
            "discovered_tabs": [],
            "extracted_text_length": 0,
            "capture_errors": capture_errors,
            "generated_files": [],
            "capture_step_log": [],
            "capture_wall_duration_ms": 0.0,
        }

        if not settings.enable_browser_capture:
            base_payload["capture_status"] = "disabled"
            return base_payload

        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception as exc:
            capture_errors.append(f"playwright_import:{type(exc).__name__}")
            payload = dict(base_payload)
            payload["capture_status"] = "playwright_not_installed"
            payload["capture_method"] = "stubbed"
            payload["capture_errors"] = capture_errors
            return payload

        if not capture_dir:
            capture_errors.append("capture_dir_missing")
            payload = dict(base_payload)
            payload["capture_status"] = "capture_dir_missing"
            payload["capture_method"] = "stubbed"
            payload["capture_errors"] = capture_errors
            return payload

        capture_metrics.record_submit()
        t0 = time.perf_counter()
        err_note: str | None = None
        try:
            _logger.info("capture start url=%s pool=%s", source_url[:80], settings.capture_use_pool)
            result = run_capture_task(_execute_playwright_capture, source_url, capture_dir)
            dur = (time.perf_counter() - t0) * 1000
            capture_metrics.record_finish(True, dur)
            _logger.info("capture ok screenshots=%s duration_ms=%.1f", len(result.get("screenshot_paths") or []), dur)
            return result
        except TimeoutError as exc:
            err_note = str(exc)
            capture_errors.append(err_note)
            payload = dict(base_payload)
            payload["capture_status"] = "capture_pool_timeout"
            payload["capture_method"] = "playwright"
            payload["capture_errors"] = capture_errors
            dur = (time.perf_counter() - t0) * 1000
            capture_metrics.record_finish(False, dur, err_note)
            _logger.error("capture pool timeout after %sms", dur)
            return payload
        except Exception as exc:
            err_note = f"{type(exc).__name__}:{exc}"
            capture_errors.append(err_note)
            payload = dict(base_payload)
            payload["capture_status"] = f"capture_failed:{type(exc).__name__}"
            payload["capture_method"] = "playwright"
            payload["capture_errors"] = capture_errors
            dur = (time.perf_counter() - t0) * 1000
            capture_metrics.record_finish(False, dur, err_note)
            _logger.exception("capture failed")
            return payload
