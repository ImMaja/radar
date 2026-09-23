"""Add versioned professional contact sets for opportunities.

Revision ID: 20260923_11
Revises: 20260922_10
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_11"
down_revision: str | None = "20260922_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create source/user contact sets and their normalized contact points."""

    op.create_table(
        "contact_set",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("layer", sa.String(length=16), nullable=False),
        sa.Column("source_observation_id", sa.Uuid(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "layer IN ('SOURCE', 'USER')",
            name="ck_contact_set_layer",
        ),
        sa.CheckConstraint(
            "(layer = 'SOURCE' AND source_observation_id IS NOT NULL) OR "
            "(layer = 'USER' AND source_observation_id IS NULL)",
            name="ck_contact_set_observation_layer",
        ),
        sa.CheckConstraint(
            "is_current OR retired_at IS NOT NULL",
            name="ck_contact_set_retired",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunity.id"],
            name="fk_contact_set_opportunity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["source_observation.id"],
            name="fk_contact_set_source_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_set")),
    )
    op.create_index(
        "uq_contact_set_current_layer",
        "contact_set",
        ["opportunity_id", "layer"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "contact_point",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contact_set_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("display_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('EMAIL', 'PHONE', 'WEBSITE', 'BOOKING_URL', 'CONTACT_RELAY')",
            name="ck_contact_point_type",
        ),
        sa.CheckConstraint(
            "scope IN ('LOCAL', 'CENTRAL', 'UNKNOWN')",
            name="ck_contact_point_scope",
        ),
        sa.CheckConstraint(
            "length(btrim(display_value)) > 0 AND length(btrim(normalized_value)) > 0",
            name="ck_contact_point_non_empty",
        ),
        sa.CheckConstraint(
            "display_order >= 0",
            name="ck_contact_point_display_order",
        ),
        sa.ForeignKeyConstraint(
            ["contact_set_id"],
            ["contact_set.id"],
            name="fk_contact_point_contact_set",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_point")),
        sa.UniqueConstraint(
            "contact_set_id",
            "type",
            "normalized_value",
            "scope",
            name="uq_contact_point_set_type_value_scope",
        ),
    )
    op.create_index(
        "ix_contact_point_type_normalized",
        "contact_point",
        ["type", "normalized_value"],
        unique=False,
    )


def downgrade() -> None:
    """Remove opportunity contact projections."""

    op.drop_index("ix_contact_point_type_normalized", table_name="contact_point")
    op.drop_table("contact_point")
    op.drop_index("uq_contact_set_current_layer", table_name="contact_set")
    op.drop_table("contact_set")
