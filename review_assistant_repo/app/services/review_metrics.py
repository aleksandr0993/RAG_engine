from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class ReviewMetricsSnapshot:
    submitted: int = 0
    completed_ok: int = 0
    completed_fail: int = 0
    total_duration_ms: float = 0.0
    last_duration_ms: float = 0.0
    low_confidence_findings_total: int = 0
    last_error: str | None = None
    updated_at_epoch: float = 0.0
    duration_samples_ms: list[float] = field(default_factory=list)


class ReviewMetrics:
    """Thread-safe review pipeline counters (sync + async)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._submitted = 0
        self._completed_ok = 0
        self._completed_fail = 0
        self._total_duration_ms = 0.0
        self._last_duration_ms = 0.0
        self._low_conf = 0
        self._last_error: str | None = None
        self._updated_at = 0.0
        self._durations: list[float] = []

    def record_start(self) -> None:
        with self._lock:
            self._submitted += 1
            self._updated_at = time.time()

    def record_finish(
        self,
        ok: bool,
        duration_ms: float,
        *,
        low_confidence_findings: int = 0,
        error: str | None = None,
    ) -> None:
        with self._lock:
            if ok:
                self._completed_ok += 1
            else:
                self._completed_fail += 1
            self._total_duration_ms += duration_ms
            self._last_duration_ms = duration_ms
            self._low_conf += max(0, low_confidence_findings)
            if error:
                self._last_error = error[:500]
            self._updated_at = time.time()
            self._durations.append(duration_ms)
            if len(self._durations) > 2000:
                self._durations = self._durations[-2000:]

    def snapshot(self) -> ReviewMetricsSnapshot:
        with self._lock:
            d = list(self._durations)
            return ReviewMetricsSnapshot(
                submitted=self._submitted,
                completed_ok=self._completed_ok,
                completed_fail=self._completed_fail,
                total_duration_ms=round(self._total_duration_ms, 2),
                last_duration_ms=round(self._last_duration_ms, 2),
                low_confidence_findings_total=self._low_conf,
                last_error=self._last_error,
                updated_at_epoch=self._updated_at,
                duration_samples_ms=d[-100:],
            )

    def percentile_ms(self, p: float) -> float | None:
        """p in [0,100]."""
        with self._lock:
            if not self._durations:
                return None
            s = sorted(self._durations)
            k = (len(s) - 1) * (p / 100.0)
            f = int(k)
            c = min(f + 1, len(s) - 1)
            return round(s[f] + (s[c] - s[f]) * (k - f), 2)


review_metrics = ReviewMetrics()
