"""Lightweight in-process counters (Prometheus text exposition on /metrics)."""

from __future__ import annotations

import threading

_llm_circuit_open_total = 0
_metadata_backfill_projects_total = 0
_metadata_backfill_resolutions_total = 0
_lock = threading.Lock()


def inc_llm_circuit_open() -> None:
    global _llm_circuit_open_total
    with _lock:
        _llm_circuit_open_total += 1


def llm_circuit_open_total() -> int:
    with _lock:
        return _llm_circuit_open_total


def inc_metadata_backfill_projects(n: int) -> None:
    global _metadata_backfill_projects_total
    if n <= 0:
        return
    with _lock:
        _metadata_backfill_projects_total += int(n)


def inc_metadata_backfill_resolutions(n: int) -> None:
    global _metadata_backfill_resolutions_total
    if n <= 0:
        return
    with _lock:
        _metadata_backfill_resolutions_total += int(n)


def metadata_backfill_projects_total() -> int:
    with _lock:
        return _metadata_backfill_projects_total


def metadata_backfill_resolutions_total() -> int:
    with _lock:
        return _metadata_backfill_resolutions_total
