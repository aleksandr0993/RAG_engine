"""Project lineage, review finding snapshots, iteration issue resolutions.

Revision ID: c3d4e5f6a7b1
Revises: b2c3d4e5f6a0
Create Date: 2026-04-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b1"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = insp.get_table_names()

    if "project_lineage" not in names:
        op.create_table(
            "project_lineage",
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("parent_project_id", sa.String(length=36), nullable=True),
            sa.Column("iteration_no", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["parent_project_id"], ["projects.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("project_id"),
        )
        op.create_index(
            "ix_project_lineage_parent_project_id",
            "project_lineage",
            ["parent_project_id"],
            unique=False,
        )

    if "review_finding_snapshot_batches" not in names:
        op.create_table(
            "review_finding_snapshot_batches",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_review_snapshot_batches_project_created",
            "review_finding_snapshot_batches",
            ["project_id", "created_at"],
            unique=False,
        )

    if "review_finding_snapshots" not in names:
        op.create_table(
            "review_finding_snapshots",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("batch_id", sa.String(length=36), nullable=False),
            sa.Column("criterion_code", sa.String(length=128), nullable=False),
            sa.Column("severity", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("anchor_position_idx", sa.Integer(), nullable=True),
            sa.Column("generated_comment", sa.Text(), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(
                ["batch_id"],
                ["review_finding_snapshot_batches.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_review_finding_snapshots_batch_id",
            "review_finding_snapshots",
            ["batch_id"],
            unique=False,
        )

    if "iteration_issue_resolutions" not in names:
        op.create_table(
            "iteration_issue_resolutions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("child_project_id", sa.String(length=36), nullable=False),
            sa.Column("parent_batch_id", sa.String(length=36), nullable=False),
            sa.Column("parent_snapshot_id", sa.String(length=36), nullable=False),
            sa.Column("resolution_status", sa.String(length=32), nullable=False),
            sa.Column("detail_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["child_project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["parent_batch_id"],
                ["review_finding_snapshot_batches.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["parent_snapshot_id"],
                ["review_finding_snapshots.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_iteration_issue_resolutions_child_project_id",
            "iteration_issue_resolutions",
            ["child_project_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = insp.get_table_names()

    if "iteration_issue_resolutions" in names:
        op.drop_index("ix_iteration_issue_resolutions_child_project_id", table_name="iteration_issue_resolutions")
        op.drop_table("iteration_issue_resolutions")

    if "review_finding_snapshots" in names:
        op.drop_index("ix_review_finding_snapshots_batch_id", table_name="review_finding_snapshots")
        op.drop_table("review_finding_snapshots")

    if "review_finding_snapshot_batches" in names:
        op.drop_index("ix_review_snapshot_batches_project_created", table_name="review_finding_snapshot_batches")
        op.drop_table("review_finding_snapshot_batches")

    if "project_lineage" in names:
        op.drop_index("ix_project_lineage_parent_project_id", table_name="project_lineage")
        op.drop_table("project_lineage")
