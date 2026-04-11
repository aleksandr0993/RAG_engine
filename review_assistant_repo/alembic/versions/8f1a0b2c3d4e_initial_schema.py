"""Initial schema (projects, files, artifacts, criterion_results, project_assignments).

Revision ID: 8f1a0b2c3d4e
Revises:
Create Date: 2025-04-11

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f1a0b2c3d4e"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables from SQLAlchemy metadata (baseline migration)."""
    import app.models  # noqa: F401 — register mappers
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    import app.models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
