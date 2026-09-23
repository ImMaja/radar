"""Add durable targeted checks for already-known Sirene establishments.

Revision ID: 20260923_12
Revises: 20260923_11
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_12"
down_revision: str | None = "20260923_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record explicit full-diffusion states without inferring closure from absence."""

    op.create_table(
        "sirene_known_status_check",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("source_binding_id", sa.Uuid(), nullable=False),
        sa.Column("external_identity_id", sa.Uuid(), nullable=False),
        sa.Column("source_observation_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('ACTIVE', 'CLOSED', 'CEASED', 'NOT_FOUND')",
            name="ck_sirene_known_status_check_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'NOT_FOUND' AND source_observation_id IS NULL) OR "
            "(outcome <> 'NOT_FOUND' AND source_observation_id IS NOT NULL)",
            name="ck_sirene_known_status_check_observation",
        ),
        sa.ForeignKeyConstraint(
            ["collection_cycle_id"],
            ["collection_cycle.id"],
            name="fk_sirene_known_status_check_cycle",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_binding_id"],
            ["source_binding.id"],
            name="fk_sirene_known_status_check_binding",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_identity_id"],
            ["external_identity.id"],
            name="fk_sirene_known_status_check_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["source_observation.id"],
            name="fk_sirene_known_status_check_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sirene_known_status_check")),
        sa.UniqueConstraint(
            "collection_cycle_id",
            "source_binding_id",
            name="uq_sirene_known_status_check_cycle_binding",
        ),
        sa.UniqueConstraint(
            "collection_cycle_id",
            "external_identity_id",
            name="uq_sirene_known_status_check_cycle_identity",
        ),
    )
    op.create_index(
        op.f("ix_sirene_known_status_check_source_binding_id"),
        "sirene_known_status_check",
        ["source_binding_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sirene_known_status_check_external_identity_id"),
        "sirene_known_status_check",
        ["external_identity_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove targeted Sirene state-check evidence."""

    op.drop_index(
        op.f("ix_sirene_known_status_check_external_identity_id"),
        table_name="sirene_known_status_check",
    )
    op.drop_index(
        op.f("ix_sirene_known_status_check_source_binding_id"),
        table_name="sirene_known_status_check",
    )
    op.drop_table("sirene_known_status_check")
