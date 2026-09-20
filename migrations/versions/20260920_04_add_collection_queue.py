"""Add the durable collection queue, attempts, cycles and proven coverage.

Revision ID: 20260920_04
Revises: 20260919_03
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision: str = "20260920_04"
down_revision: str | None = "20260919_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class GeographyPoint(UserDefinedType[str]):
    """PostGIS WGS84 geography point used by this migration."""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        return "geography(Point,4326)"


def upgrade() -> None:
    """Create the minimal durable execution and coverage model."""

    op.create_table(
        "collection_cycle",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=True),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reference_position_id", sa.Uuid(), nullable=False),
        sa.Column("center", GeographyPoint(), nullable=False),
        sa.Column("collection_radius_meters", sa.Integer(), nullable=False),
        sa.Column("schedule_timezone", sa.String(length=64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "counters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "connector IN ('SIRENE', 'DATATOURISME')",
            name="ck_collection_cycle_connector",
        ),
        sa.CheckConstraint(
            "trigger IN ('MANUAL', 'SCHEDULED')",
            name="ck_collection_cycle_trigger",
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_collection_cycle_result",
        ),
        sa.CheckConstraint(
            "collection_radius_meters BETWEEN 1 AND 50000",
            name="ck_collection_cycle_radius",
        ),
        sa.ForeignKeyConstraint(
            ["reference_position_id"],
            ["reference_position.id"],
            name="fk_collection_cycle_reference_position",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_cycle")),
    )
    op.create_index(
        op.f("ix_collection_cycle_connector"),
        "collection_cycle",
        ["connector"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_cycle_request_fingerprint"),
        "collection_cycle",
        ["request_fingerprint"],
        unique=False,
    )

    op.create_table(
        "collection_job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("connector", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "progress",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text('\'{"stage": "waiting", "processed": 0}\'::jsonb'),
            nullable=False,
        ),
        sa.Column(
            "last_safe_checkpoint",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("last_error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "connector IN ('SIRENE', 'DATATOURISME')",
            name="ck_collection_job_connector",
        ),
        sa.CheckConstraint(
            "trigger IN ('MANUAL', 'SCHEDULED')",
            name="ck_collection_job_trigger",
        ),
        sa.CheckConstraint(
            "state IN ('WAITING', 'RUNNING', 'WAITING_RETRY', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_collection_job_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_collection_job_attempt_count"),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 10",
            name="ck_collection_job_max_attempts",
        ),
        sa.CheckConstraint(
            "(trigger = 'MANUAL' AND scheduled_for IS NULL) OR "
            "(trigger = 'SCHEDULED' AND scheduled_for IS NOT NULL)",
            name="ck_collection_job_scheduled_trigger",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["collection_cycle.id"],
            name="fk_collection_job_cycle",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_job")),
        sa.UniqueConstraint("cycle_id", name=op.f("uq_collection_job_cycle_id")),
    )
    op.create_index(
        "ix_collection_job_reservation",
        "collection_job",
        ["state", "available_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_collection_job_active_request",
        "collection_job",
        ["request_fingerprint"],
        unique=True,
        postgresql_where=sa.text("state IN ('WAITING', 'RUNNING', 'WAITING_RETRY')"),
    )
    op.create_index(
        "uq_collection_job_scheduled_slot",
        "collection_job",
        ["connector", "scheduled_for"],
        unique=True,
        postgresql_where=sa.text("scheduled_for IS NOT NULL"),
    )

    op.create_table(
        "collection_attempt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column(
            "last_safe_checkpoint",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('SUCCEEDED', 'RETRYABLE_FAILURE', 'PARTIAL', 'FAILED')",
            name="ck_collection_attempt_result",
        ),
        sa.CheckConstraint("attempt_number >= 1", name="ck_collection_attempt_number"),
        sa.ForeignKeyConstraint(
            ["collection_job_id"],
            ["collection_job.id"],
            name="fk_collection_attempt_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_attempt")),
    )
    op.create_index(
        op.f("ix_collection_attempt_collection_job_id"),
        "collection_attempt",
        ["collection_job_id"],
        unique=False,
    )
    op.create_index(
        "uq_collection_attempt_number",
        "collection_attempt",
        ["collection_job_id", "attempt_number"],
        unique=True,
    )

    op.create_table(
        "connector_coverage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector", sa.String(length=32), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("center", GeographyPoint(), nullable=False),
        sa.Column("collection_radius_meters", sa.Integer(), nullable=False),
        sa.Column("established_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_freshness",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "explicit_limits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "connector IN ('SIRENE', 'DATATOURISME')",
            name="ck_connector_coverage_connector",
        ),
        sa.CheckConstraint(
            "collection_radius_meters BETWEEN 1 AND 50000",
            name="ck_connector_coverage_radius",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["collection_cycle.id"],
            name="fk_connector_coverage_cycle",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_coverage")),
        sa.UniqueConstraint("cycle_id", name=op.f("uq_connector_coverage_cycle_id")),
    )
    op.create_index(
        "ix_connector_coverage_center",
        "connector_coverage",
        ["center"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        op.f("ix_connector_coverage_connector"),
        "connector_coverage",
        ["connector"],
        unique=False,
    )


def downgrade() -> None:
    """Drop collection execution state in reverse dependency order."""

    op.drop_table("connector_coverage")
    op.drop_table("collection_attempt")
    op.drop_table("collection_job")
    op.drop_table("collection_cycle")
