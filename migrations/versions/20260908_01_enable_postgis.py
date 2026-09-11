"""Enable the PostGIS extension.

Revision ID: 20260908_01
Revises: None
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable PostGIS in Radar's dedicated database."""

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    """Remove PostGIS when reverting the empty initial schema."""

    op.execute("DROP EXTENSION IF EXISTS postgis")
