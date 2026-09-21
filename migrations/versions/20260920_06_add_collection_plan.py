"""Add durable source runs, batches, pages and Sirene municipality plans.

Revision ID: 20260920_06
Revises: 20260920_05
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_06"
down_revision: str | None = "20260920_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable, provider-neutral collection-plan tables."""

    op.create_table(
        "collection_source_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("dataset_release_id", sa.Uuid(), nullable=True),
        sa.Column("freshness_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "counters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PLANNED', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_collection_source_run_status",
        ),
        sa.CheckConstraint(
            "request_count >= 0 AND retry_count >= 0 AND error_count >= 0",
            name="ck_collection_source_run_counts",
        ),
        sa.ForeignKeyConstraint(
            ["collection_cycle_id"],
            ["collection_cycle.id"],
            name="fk_collection_source_run_cycle",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_release_id"],
            ["dataset_release.id"],
            name="fk_collection_source_run_dataset_release",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_source_run")),
        sa.UniqueConstraint(
            "collection_cycle_id",
            "source",
            name="uq_collection_source_run_cycle_source",
        ),
    )
    op.create_index(
        op.f("ix_collection_source_run_collection_cycle_id"),
        "collection_source_run",
        ["collection_cycle_id"],
        unique=False,
    )

    op.create_table(
        "collection_batch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), nullable=False),
        sa.Column("last_collection_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("batch_type", sa.String(length=64), nullable=False),
        sa.Column("batch_key", sa.String(length=160), nullable=False),
        sa.Column("order_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announced_total", sa.Integer(), nullable=True),
        sa.Column("received_count", sa.Integer(), nullable=True),
        sa.Column("unique_identifier_count", sa.Integer(), nullable=True),
        sa.Column(
            "resume_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "processing_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("order_number >= 1", name="ck_collection_batch_order"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_collection_batch_attempt_count"),
        sa.CheckConstraint(
            "state IN ('WAITING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_collection_batch_state",
        ),
        sa.CheckConstraint(
            "(announced_total IS NULL OR announced_total >= 0) AND "
            "(received_count IS NULL OR received_count >= 0) AND "
            "(unique_identifier_count IS NULL OR unique_identifier_count >= 0)",
            name="ck_collection_batch_counts",
        ),
        sa.ForeignKeyConstraint(
            ["collection_cycle_id"],
            ["collection_cycle.id"],
            name="fk_collection_batch_cycle",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["collection_source_run.id"],
            name="fk_collection_batch_source_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_collection_attempt_id"],
            ["collection_attempt.id"],
            name="fk_collection_batch_last_attempt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_batch")),
        sa.UniqueConstraint(
            "collection_cycle_id",
            "batch_key",
            name="uq_collection_batch_cycle_key",
        ),
        sa.UniqueConstraint(
            "source_run_id",
            "order_number",
            name="uq_collection_batch_source_order",
        ),
    )
    op.create_index(
        op.f("ix_collection_batch_collection_cycle_id"),
        "collection_batch",
        ["collection_cycle_id"],
        unique=False,
    )

    op.create_table(
        "collection_page",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_batch_id", sa.Uuid(), nullable=False),
        sa.Column("collection_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("page_key", sa.String(length=160), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("received_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unique_identifier_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("announced_total", sa.Integer(), nullable=True),
        sa.Column("announced_page_count", sa.Integer(), nullable=True),
        sa.Column("request_cursor_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("next_link_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("is_terminal", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="ck_collection_page_http_status",
        ),
        sa.CheckConstraint(
            "received_count >= 0 AND unique_identifier_count >= 0 AND "
            "(announced_total IS NULL OR announced_total >= 0) AND "
            "(announced_page_count IS NULL OR announced_page_count >= 0)",
            name="ck_collection_page_counts",
        ),
        sa.CheckConstraint(
            "state IN ('RECEIVED', 'PROCESSED', 'FAILED')",
            name="ck_collection_page_state",
        ),
        sa.ForeignKeyConstraint(
            ["collection_batch_id"],
            ["collection_batch.id"],
            name="fk_collection_page_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_attempt_id"],
            ["collection_attempt.id"],
            name="fk_collection_page_attempt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_page")),
        sa.UniqueConstraint(
            "collection_batch_id",
            "page_key",
            name="uq_collection_page_batch_key",
        ),
    )
    op.create_index(
        op.f("ix_collection_page_collection_batch_id"),
        "collection_page",
        ["collection_batch_id"],
        unique=False,
    )

    op.create_table(
        "collection_reference_usage",
        sa.Column("collection_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_release_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('MUNICIPALITY_BOUNDARIES', 'SIRENE_GEOLOCATION')",
            name="ck_collection_reference_usage_role",
        ),
        sa.ForeignKeyConstraint(
            ["collection_cycle_id"],
            ["collection_cycle.id"],
            name="fk_collection_reference_usage_cycle",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_release_id"],
            ["dataset_release.id"],
            name="fk_collection_reference_usage_dataset_release",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "collection_cycle_id",
            "dataset_release_id",
            "role",
            name=op.f("pk_collection_reference_usage"),
        ),
    )

    op.create_table(
        "collection_cycle_commune",
        sa.Column("collection_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_release_id", sa.Uuid(), nullable=False),
        sa.Column("municipality_code", sa.String(length=5), nullable=False),
        sa.Column("collection_batch_id", sa.Uuid(), nullable=False),
        sa.Column("selection_reason", sa.String(length=96), nullable=False),
        sa.Column("selection_margin_meters", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "selection_margin_meters BETWEEN 0 AND 10000",
            name="ck_collection_cycle_commune_margin",
        ),
        sa.CheckConstraint(
            "state IN ('WAITING', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_collection_cycle_commune_state",
        ),
        sa.ForeignKeyConstraint(
            ["collection_cycle_id"],
            ["collection_cycle.id"],
            name="fk_collection_cycle_commune_cycle",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_batch_id"],
            ["collection_batch.id"],
            name="fk_collection_cycle_commune_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_release_id", "municipality_code"],
            ["commune_boundary.dataset_release_id", "commune_boundary.municipality_code"],
            name="fk_collection_cycle_commune_boundary",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "collection_cycle_id",
            "municipality_code",
            name=op.f("pk_collection_cycle_commune"),
        ),
    )
    op.create_index(
        op.f("ix_collection_cycle_commune_collection_batch_id"),
        "collection_cycle_commune",
        ["collection_batch_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop collection planning and pagination state in dependency order."""

    op.drop_table("collection_cycle_commune")
    op.drop_table("collection_reference_usage")
    op.drop_table("collection_page")
    op.drop_table("collection_batch")
    op.drop_table("collection_source_run")
