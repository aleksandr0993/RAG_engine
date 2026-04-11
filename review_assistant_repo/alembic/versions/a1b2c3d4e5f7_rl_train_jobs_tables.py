"""RL train jobs + artefact locks (durable training state).

Revision ID: a1b2c3d4e5f7
Revises: 8f1a0b2c3d4e
Create Date: 2026-04-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | Sequence[str] | None = "8f1a0b2c3d4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rl_train_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("artefact_name", sa.String(length=255), nullable=False),
        sa.Column("env_id", sa.String(length=128), nullable=False),
        sa.Column("algorithm", sa.String(length=16), nullable=False),
        sa.Column("total_timesteps", sa.Integer(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_sub", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rl_train_artefact_locks",
        sa.Column("artefact_name", sa.String(length=255), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["rl_train_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("artefact_name"),
        sa.UniqueConstraint("job_id"),
    )


def downgrade() -> None:
    op.drop_table("rl_train_artefact_locks")
    op.drop_table("rl_train_jobs")
