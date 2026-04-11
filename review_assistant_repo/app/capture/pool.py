from __future__ import annotations

import atexit
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import ParamSpec, TypeVar

from app.config import get_settings

P = ParamSpec("P")
R = TypeVar("R")

_logger = logging.getLogger("app.capture.pool")

_executor: ThreadPoolExecutor | None = None
_executor_workers: int | None = None
_lock = threading.Lock()


def _shutdown_capture_executor() -> None:
    global _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=False)
            _executor = None


atexit.register(_shutdown_capture_executor)


def get_capture_executor() -> ThreadPoolExecutor | None:
    """
    Lazy singleton ThreadPoolExecutor for Playwright capture.
    Returns None when pool is disabled (workers <= 0).
    """
    global _executor, _executor_workers
    settings = get_settings()
    workers = max(0, int(settings.capture_pool_workers))
    if workers == 0:
        return None
    with _lock:
        if _executor is None or _executor_workers != workers:
            if _executor is not None:
                _executor.shutdown(wait=False, cancel_futures=False)
                _logger.info("Recreated capture executor workers=%s", workers)
            _executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ra-capture-")
            _executor_workers = workers
        return _executor


def run_capture_task(fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """
    Run capture callable either in the pool (bounded concurrency) or inline.
    Respects capture_pool_timeout_sec.
    """
    settings = get_settings()
    if not settings.capture_use_pool:
        return fn(*args, **kwargs)
    ex = get_capture_executor()
    if ex is None:
        return fn(*args, **kwargs)
    fut = ex.submit(fn, *args, **kwargs)
    try:
        return fut.result(timeout=float(settings.capture_pool_timeout_sec))
    except FuturesTimeout:
        from app.capture.metrics import capture_metrics

        _logger.error("Capture pool task timed out after %ss", settings.capture_pool_timeout_sec)
        capture_metrics.record_pool_timeout()
        fut.cancel()
        raise TimeoutError(f"capture_pool_timeout_{settings.capture_pool_timeout_sec}s") from None
