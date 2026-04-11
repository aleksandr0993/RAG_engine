from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _json_default():
    return {}


def _json_list_default():
    return []


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    style_profile_code: Mapped[str] = mapped_column(String(64), nullable=False)
    criteria_map_code: Mapped[str] = mapped_column(String(64), nullable=False)
    final_verdict: Mapped[str | None] = mapped_column(String(32))
    review_markdown: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=_json_default, nullable=False)

    files: Mapped[list[ProjectFile]] = relationship(back_populates="project", cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="project", cascade="all, delete-orphan")
    criterion_results: Mapped[list[CriterionResult]] = relationship(back_populates="project", cascade="all, delete-orphan")
    assignments: Mapped[list[ProjectAssignment]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    review_jobs: Mapped[list[ReviewJob]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    lineage: Mapped[ProjectLineage | None] = relationship(
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="ProjectLineage.project_id",
    )


class ProjectLineage(Base):
    """Links a project to the previous submission iteration (resubmit chain)."""

    __tablename__ = "project_lineage"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    parent_project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    iteration_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    project: Mapped[Project] = relationship(
        back_populates="lineage",
        foreign_keys=[project_id],
    )


class ReviewFindingSnapshotBatch(Base):
    """One batch per completed review run (append-only audit trail)."""

    __tablename__ = "review_finding_snapshot_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    findings: Mapped[list[ReviewFindingSnapshot]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class ReviewFindingSnapshot(Base):
    """Frozen criterion outcomes after a review (used to compare the next iteration)."""

    __tablename__ = "review_finding_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("review_finding_snapshot_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    criterion_code: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    anchor_position_idx: Mapped[int | None] = mapped_column(Integer)
    generated_comment: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[list] = mapped_column(JSON, default=_json_list_default, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=_json_default, nullable=False)

    batch: Mapped[ReviewFindingSnapshotBatch] = relationship(back_populates="findings")


class IterationIssueResolution(Base):
    """How a child iteration addressed findings from the parent's last review batch."""

    __tablename__ = "iteration_issue_resolutions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    child_project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    parent_batch_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("review_finding_snapshot_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("review_finding_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSON, default=_json_default, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ReviewJob(Base):
    """Async/sync review execution record (queued → running → terminal state)."""

    __tablename__ = "review_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[dict] = mapped_column(JSON, default=_json_default, nullable=False)

    project: Mapped[Project] = relationship(back_populates="review_jobs")


class ProjectFile(Base):
    __tablename__ = "project_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    page_no: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=_json_default, nullable=False)

    project: Mapped[Project] = relationship(back_populates="files")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    position_idx: Mapped[int | None] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(String(128))
    raw_text: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=_json_default, nullable=False)

    project: Mapped[Project] = relationship(back_populates="artifacts")


class CriterionResult(Base):
    __tablename__ = "criterion_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    criterion_code: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    anchor_artifact_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("artifacts.id", ondelete="SET NULL"))
    evidence_json: Mapped[list] = mapped_column(JSON, default=_json_list_default, nullable=False)
    generated_comment: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=_json_default, nullable=False)

    project: Mapped[Project] = relationship(back_populates="criterion_results")


class ProjectAssignment(Base):
    """Reviewer load-balancing: which reviewer owns (or is queued for) a project."""

    __tablename__ = "project_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=_json_default, nullable=False)

    project: Mapped[Project] = relationship(back_populates="assignments")


class RLTrainJob(Base):
    """Persistent SB3 training job (async BackgroundTasks or sync audit trail)."""

    __tablename__ = "rl_train_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    artefact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    env_id: Mapped[str] = mapped_column(String(128), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(16), nullable=False)
    total_timesteps: Mapped[int] = mapped_column(Integer, nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, default=_json_default, nullable=False)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by_sub: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    artefact_lock: Mapped[RLTrainArtefactLock | None] = relationship(
        back_populates="job",
        uselist=False,
    )


class RLTrainArtefactLock(Base):
    """
    At most one active train per artefact_name (DB-enforced PK).
    Released when the job reaches a terminal state.
    """

    __tablename__ = "rl_train_artefact_locks"

    artefact_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("rl_train_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    job: Mapped[RLTrainJob] = relationship(back_populates="artefact_lock")
