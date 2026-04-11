from __future__ import annotations

from datetime import datetime

from app.models import Project


def hours_between_utc(later: datetime | None, earlier: datetime | None) -> float | None:
    """Hours from earlier to later (positive if later is after earlier)."""
    if later is None or earlier is None:
        return None
    try:
        return round((later - earlier).total_seconds() / 3600.0, 4)
    except (TypeError, ValueError):
        return None


def review_turnaround_hours(project: Project) -> float | None:
    """
    Wall time from project creation to last row update when review finished (status done).
    Proxy for 'how long until this submission was reviewed'.
    """
    if project.status != "done":
        return None
    return hours_between_utc(project.updated_at, project.created_at)
