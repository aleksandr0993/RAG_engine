from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.models import ReviewFindingSnapshot, ReviewFindingSnapshotBatch


def persist_review_snapshot(
    db: Session,
    project_id: str,
    merged_results: list[dict[str, Any]],
) -> str:
    """
    Store a full snapshot of criterion outcomes for this review run.
    Returns the new batch id.
    """
    batch_id = str(uuid.uuid4())
    batch = ReviewFindingSnapshotBatch(
        id=batch_id,
        project_id=project_id,
    )
    db.add(batch)
    db.flush()

    for m in merged_results:
        anchor = m.get("anchor_position_idx")
        anchor_idx = int(anchor) if anchor is not None else None
        row = ReviewFindingSnapshot(
            id=str(uuid.uuid4()),
            batch_id=batch_id,
            criterion_code=str(m["criterion_code"]),
            severity=str(m.get("severity") or "info"),
            status=str(m.get("status") or "unknown"),
            confidence=m.get("confidence"),
            anchor_position_idx=anchor_idx,
            generated_comment=m.get("generated_comment"),
            evidence_json=list(m.get("evidence") or []),
            metadata_json=dict(m.get("metadata") or {}),
        )
        db.add(row)

    return batch_id


def get_latest_snapshot_batch(db: Session, project_id: str) -> ReviewFindingSnapshotBatch | None:
    return (
        db.query(ReviewFindingSnapshotBatch)
        .options(joinedload(ReviewFindingSnapshotBatch.findings))
        .filter(ReviewFindingSnapshotBatch.project_id == project_id)
        .order_by(desc(ReviewFindingSnapshotBatch.created_at))
        .first()
    )


def list_open_issues_from_batch(batch: ReviewFindingSnapshotBatch) -> list[ReviewFindingSnapshot]:
    """Findings that were not passing in the parent's review."""
    return [f for f in batch.findings if f.status != "pass"]
