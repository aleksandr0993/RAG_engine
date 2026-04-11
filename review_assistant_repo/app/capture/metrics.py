from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class CaptureMetricsSnapshot:
    submitted: int = 0
    completed_ok: int = 0
    completed_fail: int = 0
    total_duration_ms: float = 0.0
    last_duration_ms: float = 0.0
    pool_timeouts: int = 0
    last_error: str | None = None
    updated_at_epoch: float = 0.0


class CaptureMetrics:
    """Thread-safe counters for DataLens / browser capture runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._submitted = 0
        self._completed_ok = 0
        self._completed_fail = 0
        self._total_duration_ms = 0.0
        self._last_duration_ms = 0.0
        self._pool_timeouts = 0
        self._last_error: str | None = None
        self._updated_at = 0.0

    def record_submit(self) -> None:
        with self._lock:
            self._submitted += 1
            self._updated_at = time.time()

    def record_finish(self, ok: bool, duration_ms: float, error: str | None = None) -> None:
        with self._lock:
            if ok:
                self._completed_ok += 1
            else:
                self._completed_fail += 1
            self._total_duration_ms += duration_ms
            self._last_duration_ms = duration_ms
            if error:
                self._last_error = error[:500]
            self._updated_at = time.time()

    def record_pool_timeout(self) -> None:
        with self._lock:
            self._pool_timeouts += 1
            self._last_error = "pool_timeout"
            self._updated_at = time.time()

    def snapshot(self) -> CaptureMetricsSnapshot:
        with self._lock:
            return CaptureMetricsSnapshot(
                submitted=self._submitted,
                completed_ok=self._completed_ok,
                completed_fail=self._completed_fail,
                total_duration_ms=round(self._total_duration_ms, 2),
                last_duration_ms=round(self._last_duration_ms, 2),
                pool_timeouts=self._pool_timeouts,
                last_error=self._last_error,
                updated_at_epoch=self._updated_at,
            )


capture_metrics = CaptureMetrics()
