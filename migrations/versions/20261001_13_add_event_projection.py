"""Add the DATAtourisme source and versioned event projections.

Revision ID: 20261001_13
Revises: 20260923_12
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261001_13"
down_revision: str | None = "20260923_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create source-owned event fields and independently versioned periods."""

    op.execute(
        """
        INSERT INTO data_source (
            code,
            name,
            authority,
            documentation_url,
            terms_reference,
            is_active,
            metadata,
            created_at,
            updated_at
        ) VALUES (
            'DATATOURISME_API',
            'API DATAtourisme v1',
            'DATAtourisme',
            'https://api.datatourisme.fr/v1/docs',
            'Licence Ouverte 2.0',
            TRUE,
            '{"api_version": "v1", "resource": "entertainmentAndEvent"}'::jsonb,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        """
    )

    op.create_table(
        "event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_description", sa.Text(), nullable=True),
        sa.Column(
            "source_types",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_category", sa.String(length=64), nullable=True),
        sa.Column("source_format", sa.String(length=64), nullable=True),
        sa.Column("source_audience_value", sa.Integer(), nullable=True),
        sa.Column("source_audience_kind", sa.String(length=32), nullable=True),
        sa.Column("source_audience_scope", sa.String(length=32), nullable=True),
        sa.Column("declared_status", sa.String(length=16), nullable=False),
        sa.Column("organizer_name", sa.Text(), nullable=True),
        sa.Column("organizer_organization_id", sa.Uuid(), nullable=True),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column(
            "source_links",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_business_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(source_title)) > 0",
            name="ck_event_source_title_non_empty",
        ),
        sa.CheckConstraint(
            "source_audience_value IS NULL OR source_audience_value > 0",
            name="ck_event_source_audience_positive",
        ),
        sa.CheckConstraint(
            "(source_audience_value IS NULL AND source_audience_kind IS NULL "
            "AND source_audience_scope IS NULL) OR "
            "(source_audience_value IS NOT NULL "
            "AND source_audience_kind IN ('EXPECTED_ATTENDANCE', 'EVENT_CAPACITY') "
            "AND source_audience_scope IS NOT NULL)",
            name="ck_event_source_audience_complete",
        ),
        sa.CheckConstraint(
            "declared_status IN ('SCHEDULED', 'POSTPONED', 'CANCELLED', 'UNKNOWN')",
            name="ck_event_declared_status",
        ),
        sa.ForeignKeyConstraint(
            ["id"],
            ["opportunity.id"],
            name="fk_event_opportunity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organizer_organization_id"],
            ["organization.id"],
            name="fk_event_organizer_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event")),
    )
    op.create_index(
        op.f("ix_event_organizer_organization_id"),
        "event",
        ["organizer_organization_id"],
        unique=False,
    )

    op.create_table(
        "event_period_set",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("layer", sa.String(length=16), nullable=False),
        sa.Column("source_observation_id", sa.Uuid(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "layer IN ('SOURCE', 'USER')",
            name="ck_event_period_set_layer",
        ),
        sa.CheckConstraint(
            "(layer = 'SOURCE' AND source_observation_id IS NOT NULL) OR "
            "(layer = 'USER' AND source_observation_id IS NULL)",
            name="ck_event_period_set_observation_layer",
        ),
        sa.CheckConstraint(
            "is_current OR retired_at IS NOT NULL",
            name="ck_event_period_set_retired",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name="fk_event_period_set_event",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["source_observation.id"],
            name="fk_event_period_set_source_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_period_set")),
    )
    op.create_index(
        "uq_event_period_set_current_layer",
        "event_period_set",
        ["event_id", "layer"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "event_period",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("period_set_id", sa.Uuid(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("interpretation_timezone", sa.String(length=64), nullable=False),
        sa.Column("precision", sa.String(length=24), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "recurrence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_path", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("display_order >= 0", name="ck_event_period_display_order"),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_event_period_date_order",
        ),
        sa.CheckConstraint(
            "COALESCE(end_date, start_date) <> start_date OR start_time IS NULL "
            "OR end_time IS NULL OR end_time >= start_time",
            name="ck_event_period_time_order",
        ),
        sa.CheckConstraint(
            "interpretation_timezone = 'Europe/Paris'",
            name="ck_event_period_timezone",
        ),
        sa.CheckConstraint(
            "precision IN ('DATE_ONLY', 'DATE_AND_TIME', 'MIXED')",
            name="ck_event_period_precision",
        ),
        sa.ForeignKeyConstraint(
            ["period_set_id"],
            ["event_period_set.id"],
            name="fk_event_period_period_set",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_period")),
        sa.UniqueConstraint(
            "period_set_id",
            "display_order",
            name="uq_event_period_set_display_order",
        ),
    )
    op.create_index(
        "ix_event_period_dates",
        "event_period",
        ["start_date", "end_date"],
        unique=False,
    )
    op.execute(
        "CREATE INDEX ix_event_period_date_range ON event_period "
        "USING gist (daterange(start_date, COALESCE(end_date, start_date), '[]'))"
    )


def downgrade() -> None:
    """Remove event projections and the source registration."""

    op.execute("DROP INDEX IF EXISTS ix_event_period_date_range")
    op.drop_index("ix_event_period_dates", table_name="event_period")
    op.drop_table("event_period")
    op.drop_index("uq_event_period_set_current_layer", table_name="event_period_set")
    op.drop_table("event_period_set")
    op.drop_index(op.f("ix_event_organizer_organization_id"), table_name="event")
    op.drop_table("event")
    op.execute(
        "DELETE FROM collection_item "
        "WHERE authority = 'DATATOURISME' AND namespace = 'DATATOURISME_UUID'"
    )
    op.execute(
        "DELETE FROM field_lineage WHERE opportunity_id IN ("
        "SELECT opportunity_id FROM external_identity "
        "WHERE authority = 'DATATOURISME' AND namespace = 'DATATOURISME_UUID')"
    )
    op.execute(
        "UPDATE source_observation SET source_binding_id = NULL "
        "WHERE data_source_code = 'DATATOURISME_API'"
    )
    op.execute("DELETE FROM source_binding WHERE data_source_code = 'DATATOURISME_API'")
    op.execute(
        "CREATE TEMPORARY TABLE datatourisme_downgrade_opportunity ON COMMIT DROP AS "
        "SELECT DISTINCT opportunity_id FROM external_identity "
        "WHERE authority = 'DATATOURISME' AND namespace = 'DATATOURISME_UUID' "
        "AND opportunity_id IS NOT NULL"
    )
    op.execute(
        "UPDATE external_identity SET opportunity_id = NULL "
        "WHERE authority = 'DATATOURISME' AND namespace = 'DATATOURISME_UUID'"
    )
    op.execute(
        "DELETE FROM opportunity WHERE id IN ("
        "SELECT opportunity_id FROM datatourisme_downgrade_opportunity)"
    )
    op.execute("DROP TABLE datatourisme_downgrade_opportunity")
    op.execute("DELETE FROM source_observation WHERE data_source_code = 'DATATOURISME_API'")
    op.execute(
        "DELETE FROM external_identity "
        "WHERE authority = 'DATATOURISME' AND namespace = 'DATATOURISME_UUID'"
    )
    op.execute("DELETE FROM data_source WHERE code = 'DATATOURISME_API'")
