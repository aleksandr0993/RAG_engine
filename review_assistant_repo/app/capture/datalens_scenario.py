from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from app.capture.datalens_selectors import (
    NAV_LINK_SELECTORS,
    SHELL_READY_SELECTORS,
    TAB_STRIP_SELECTORS,
    first_visible_locator,
)

_logger = logging.getLogger("app.capture.datalens_scenario")


def _slug(s: str, max_len: int = 40) -> str:
    x = re.sub(r"[^\w\-]+", "_", s.strip().lower(), flags=re.UNICODE)
    return (x[:max_len] or "tab").strip("_") or "tab"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sleep_ms(ms: int) -> None:
    if ms > 0:
        time.sleep(ms / 1000.0)


def run_datalens_capture_scenario(
    page,
    source_url: str,
    capture_dir: Path,
    *,
    navigation_timeout_ms: int,
    settle_after_load_ms: int,
    tab_settle_ms: int,
    max_tab_screenshots: int,
    goto_max_retries: int = 3,
    tab_click_max_retries: int = 2,
    step_retry_base_ms: int = 400,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """
    Execute ordered capture steps with per-step timings and screenshots.

    Returns (screenshot_paths, step_log, errors).
    """
    errors: list[str] = []
    step_log: list[dict[str, Any]] = []
    screenshot_paths: list[str] = []
    order = 0

    def step_begin(step_id: str, detail: str = "") -> int:
        nonlocal order
        order += 1
        t0 = _now_ms()
        step_log.append(
            {
                "step_id": step_id,
                "order": order,
                "started_at_epoch_ms": t0,
                "duration_ms": None,
                "screenshot_path": None,
                "selector_used": None,
                "detail": detail,
                "error": None,
            }
        )
        _logger.info("capture step start %s #%s %s", step_id, order, detail)
        return t0

    def step_end(idx: int, t0: int, **extra: Any) -> None:
        dur = _now_ms() - t0
        entry = step_log[idx]
        entry["duration_ms"] = dur
        for k, v in extra.items():
            if v is not None:
                entry[k] = v
        _logger.info("capture step end %s duration_ms=%s", entry["step_id"], dur)

    # --- Step: navigate (retry with backoff)
    si = len(step_log)
    t0 = step_begin("navigate", source_url[:120])
    nav_ok = False
    last_nav_exc: Exception | None = None
    attempts = max(1, int(goto_max_retries))
    for attempt in range(1, attempts + 1):
        try:
            try:
                page.goto(source_url, wait_until="networkidle", timeout=navigation_timeout_ms)
            except Exception as exc:
                errors.append(f"goto_networkidle_try{attempt}:{type(exc).__name__}")
                page.goto(source_url, wait_until="domcontentloaded", timeout=navigation_timeout_ms)
            _sleep_ms(settle_after_load_ms)
            nav_ok = True
            break
        except Exception as exc:
            last_nav_exc = exc
            errors.append(f"goto_try{attempt}:{type(exc).__name__}")
            if attempt >= attempts:
                break
            backoff = min(8000, int(step_retry_base_ms) * (2 ** (attempt - 1)))
            _sleep_ms(backoff)
    if not nav_ok:
        if last_nav_exc is not None:
            step_end(si, t0, error=str(last_nav_exc))
        else:
            step_end(si, t0, error="goto_failed")
        return screenshot_paths, step_log, errors
    step_end(si, t0)

    # --- Step: wait_shell
    si = len(step_log)
    t0 = step_begin("wait_shell")
    sel_used, _ = first_visible_locator(page, SHELL_READY_SELECTORS, min_count=1)
    if sel_used:
        try:
            page.locator(sel_used).first.wait_for(state="visible", timeout=min(12_000, navigation_timeout_ms))
        except Exception as exc:
            errors.append(f"shell_wait:{type(exc).__name__}")
    else:
        errors.append("shell_no_known_selector")
    step_end(si, t0, selector_used=sel_used)

    # --- Step: title + body
    si = len(step_log)
    t0 = step_begin("extract_dom_text")
    title = ""
    body_text = ""
    try:
        title = page.title()
    except Exception as exc:
        errors.append(f"title:{type(exc).__name__}")
    try:
        body_text = page.locator("body").inner_text(timeout=8000) or ""
    except Exception as exc:
        errors.append(f"body_text:{type(exc).__name__}")
    step_end(si, t0, detail=f"title_len={len(title)} body_len={len(body_text)}")

    # --- Step: screenshot initial (legacy-compatible primary path)
    si = len(step_log)
    t0 = step_begin("screenshot_initial")
    primary = str(capture_dir / "datalens_capture_full.png")
    try:
        page.screenshot(path=primary, full_page=True)
        screenshot_paths.append(primary)
        step_end(si, t0, screenshot_path=primary)
    except Exception as exc:
        errors.append(f"shot_initial:{type(exc).__name__}")
        step_end(si, t0, error=str(exc))

    # --- Step: discover tabs
    si = len(step_log)
    t0 = step_begin("discover_tabs")
    tab_sel, tab_loc = first_visible_locator(page, TAB_STRIP_SELECTORS, min_count=1)
    labels: list[str] = []
    if tab_sel and tab_loc is not None:
        try:
            count = min(tab_loc.count(), 24)
            for i in range(count):
                try:
                    txt = (tab_loc.nth(i).inner_text(timeout=1200) or "").strip()
                    if txt and len(txt) < 100:
                        labels.append(txt)
                except Exception:
                    continue
        except Exception as exc:
            errors.append(f"tab_labels:{type(exc).__name__}")
    # Fallback: nav links as pseudo-tabs
    if len(labels) < 2:
        nav_sel, nav_loc = first_visible_locator(page, NAV_LINK_SELECTORS, min_count=2)
        if nav_sel and nav_loc is not None:
            tab_sel = nav_sel
            tab_loc = nav_loc
            try:
                for i in range(min(nav_loc.count(), 12)):
                    try:
                        txt = (nav_loc.nth(i).inner_text(timeout=800) or "").strip()
                        if txt and 1 < len(txt) < 80:
                            labels.append(txt)
                    except Exception:
                        continue
            except Exception:
                pass
    seen: set[str] = set()
    uniq_labels: list[str] = []
    for lab in labels:
        k = lab.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq_labels.append(lab)
    step_end(si, t0, selector_used=tab_sel, detail=f"tabs_found={len(uniq_labels)}")

    # --- Step: click tabs + screenshot each state
    if tab_sel and tab_loc is not None:
        n_click = min(tab_loc.count(), max(1, max_tab_screenshots))
        for i in range(n_click):
            si = len(step_log)
            label = ""
            try:
                label = (tab_loc.nth(i).inner_text(timeout=1500) or "").strip()[:80]
            except Exception:
                label = f"idx{i}"
            t0 = step_begin(f"tab_interaction_{i}", label)
            shot_path = str(capture_dir / f"step_{i + 1:02d}_tab_{_slug(label)}.png")
            try:
                click_attempts = max(1, int(tab_click_max_retries))
                click_ok = False
                last_click_exc: Exception | None = None
                for c_attempt in range(1, click_attempts + 1):
                    try:
                        tab_loc.nth(i).click(timeout=4000)
                        click_ok = True
                        break
                    except Exception as exc:
                        last_click_exc = exc
                        errors.append(f"tab_{i}_click_try{c_attempt}:{type(exc).__name__}")
                        if c_attempt >= click_attempts:
                            break
                        backoff = min(5000, int(step_retry_base_ms) * (2 ** (c_attempt - 1)))
                        _sleep_ms(backoff)
                if not click_ok:
                    raise last_click_exc or RuntimeError("tab_click_failed")
                _sleep_ms(tab_settle_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(8000, navigation_timeout_ms))
                except Exception:
                    _sleep_ms(200)
                page.screenshot(path=shot_path, full_page=True)
                screenshot_paths.append(shot_path)
                step_end(si, t0, screenshot_path=shot_path, selector_used=tab_sel)
            except Exception as exc:
                errors.append(f"tab_{i}:{type(exc).__name__}")
                step_end(si, t0, error=str(exc), selector_used=tab_sel)

    return screenshot_paths, step_log, errors
