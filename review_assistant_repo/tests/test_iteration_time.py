"""iteration_time helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Project
from app.services.iteration_time import hours_between_utc, review_turnaround_hours


def test_hours_between_utc():
    a = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    b = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    assert hours_between_utc(a, b) == 2.0


def test_review_turnaround_done():
    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 11, 30, 0, tzinfo=UTC)
    p = Project(
        id="x",
        source_type="ipynb",
        style_profile_code="s",
        criteria_map_code="c",
        status="done",
        created_at=t0,
        updated_at=t1,
    )
    assert review_turnaround_hours(p) == 1.5


def test_review_turnaround_not_done():
    p = Project(
        id="y",
        source_type="ipynb",
        style_profile_code="s",
        criteria_map_code="c",
        status="uploaded",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert review_turnaround_hours(p) is None
