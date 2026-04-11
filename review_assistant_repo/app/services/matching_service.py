"""Load-balanced assignment of projects to reviewers."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import ProjectAssignment


class MatchingService:
    def active_queue_depth(self, db: Session, reviewer_id: str) -> int:
        return (
            db.query(ProjectAssignment)
            .filter(
                ProjectAssignment.reviewer_id == reviewer_id,
                ProjectAssignment.status == "active",
            )
            .count()
        )

    def suggest_reviewer(
        self,
        db: Session,
        reviewer_ids: list[str],
        *,
        criteria_map_code: str | None = None,
        expertise_by_reviewer: dict[str, list[str]] | None = None,
    ) -> str | None:
        """
        Pick the reviewer with the smallest active assignment queue.
        If ``expertise_by_reviewer`` maps reviewer_id -> list of criteria_map codes matching
        ``criteria_map_code``, those reviewers get priority (still tie-broken by queue depth).
        """
        ids = [r.strip() for r in reviewer_ids if r and str(r).strip()]
        if not ids:
            return None
        expertise_by_reviewer = expertise_by_reviewer or {}
        want = (criteria_map_code or "").strip()

        def sort_key(rid: str) -> tuple[int, int, str]:
            match = 0
            if want:
                codes = {c.strip() for c in expertise_by_reviewer.get(rid, []) if c}
                if want in codes:
                    match = 0
                else:
                    match = 1
            return (match, self.active_queue_depth(db, rid), rid)

        return min(ids, key=sort_key)

    def assign(
        self,
        db: Session,
        *,
        project_id: str,
        reviewer_id: str,
        priority: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectAssignment:
        row = ProjectAssignment(
            id=str(uuid.uuid4()),
            project_id=project_id,
            reviewer_id=reviewer_id.strip(),
            priority=int(priority),
            status="active",
            metadata_json=dict(metadata or {}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def list_for_project(self, db: Session, project_id: str) -> list[ProjectAssignment]:
        return (
            db.query(ProjectAssignment)
            .filter(ProjectAssignment.project_id == project_id)
            .order_by(ProjectAssignment.assigned_at.desc())
            .all()
        )
