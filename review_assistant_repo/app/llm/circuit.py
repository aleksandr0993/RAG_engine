"""Thread-safe LLM circuit breaker (shared across LLMClient instances)."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

_lock = threading.Lock()
_failures_consecutive = 0
_open_until_monotonic = 0.0


def is_circuit_open(settings: Settings) -> bool:
    """Return True if calls should be short-circuited until cooldown elapses."""
    global _open_until_monotonic
    with _lock:
        now = time.monotonic()
        if now < _open_until_monotonic:
            return True
        # Cooldown elapsed: allow trial calls again
        if _open_until_monotonic > 0 and now >= _open_until_monotonic:
            _open_until_monotonic = 0.0
        return False


def record_success() -> None:
    global _failures_consecutive, _open_until_monotonic
    with _lock:
        _failures_consecutive = 0
        _open_until_monotonic = 0.0


def record_failure(settings: Settings) -> None:
    """Increment failure streak; open circuit after threshold."""
    global _failures_consecutive, _open_until_monotonic
    with _lock:
        _failures_consecutive += 1
        thr = max(1, int(getattr(settings, "llm_circuit_failure_threshold", 5)))
        cool = float(getattr(settings, "llm_circuit_cooldown_sec", 60.0))
        if _failures_consecutive >= thr:
            _open_until_monotonic = time.monotonic() + max(1.0, cool)
            _failures_consecutive = 0
            try:
                from app.metrics import inc_llm_circuit_open

                inc_llm_circuit_open()
            except Exception:
                pass
