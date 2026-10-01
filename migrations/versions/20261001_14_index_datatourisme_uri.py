"""Index DATAtourisme URI collisions and sticky identity conflicts.

Revision ID: 20261001_14
Revises: 20261001_13
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_14"
down_revision: str | None = "20261001_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Accelerate URI collision and prior-conflict checks."""

    op.create_index(
        "ix_source_observation_datatourisme_uri_identity",
        "source_observation",
        ["source_reference", "external_identity_id"],
        unique=False,
        postgresql_where=sa.text(
            "data_source_code = 'DATATOURISME_API' "
            "AND source_reference IS NOT NULL AND redacted_at IS NULL"
        ),
    )
    op.create_index(
        "ix_collection_item_identity_conflict",
        "collection_item",
        ["external_identity_id"],
        unique=False,
        postgresql_where=sa.text("normalization_result = 'IDENTITY_CONFLICT'"),
    )


def downgrade() -> None:
    """Remove the DATAtourisme identity-check indexes."""

    op.drop_index("ix_collection_item_identity_conflict", table_name="collection_item")
    op.drop_index(
        "ix_source_observation_datatourisme_uri_identity",
        table_name="source_observation",
    )
