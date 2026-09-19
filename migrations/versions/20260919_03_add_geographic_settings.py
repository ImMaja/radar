"""Add the confirmed reference position and local radius settings.

Revision ID: 20260919_03
Revises: 20260911_02
Create Date: 2026-09-19
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision: str = "20260919_03"
down_revision: str | None = "20260911_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class GeographyPoint(UserDefinedType[str]):
    """PostGIS WGS84 geography point used by this migration."""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        return "geography(Point,4326)"


def upgrade() -> None:
    """Create immutable geocoding history and the singleton settings row."""

    op.create_table(
        "reference_position",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("input_address", sa.Text(), nullable=False),
        sa.Column("normalized_label", sa.Text(), nullable=False),
        sa.Column("structured_address", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("point", GeographyPoint(), nullable=False),
        sa.Column("municipality_code", sa.String(length=5), nullable=False),
        sa.Column("ban_id", sa.String(length=128), nullable=True),
        sa.Column("result_type", sa.String(length=64), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_url", sa.Text(), nullable=False),
        sa.Column("geocoded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("is_metropolitan_france", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("country_code = 'FR'", name="ck_reference_position_country_code"),
        sa.CheckConstraint(
            "is_metropolitan_france IS TRUE",
            name="ck_reference_position_metropolitan",
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_reference_position_score",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reference_position")),
    )
    op.create_index(
        op.f("ix_reference_position_municipality_code"),
        "reference_position",
        ["municipality_code"],
        unique=False,
    )
    op.create_index(
        "ix_reference_position_point",
        "reference_position",
        ["point"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "application_setting",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("singleton_key", sa.String(length=16), nullable=False),
        sa.Column("current_reference_position_id", sa.Uuid(), nullable=True),
        sa.Column(
            "collection_radius_meters",
            sa.Integer(),
            server_default="50000",
            nullable=False,
        ),
        sa.Column(
            "search_radius_meters",
            sa.Integer(),
            server_default="50000",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "singleton_key = 'primary'",
            name="ck_application_setting_singleton_key",
        ),
        sa.CheckConstraint(
            "collection_radius_meters BETWEEN 1 AND 50000",
            name="ck_application_setting_collection_radius",
        ),
        sa.CheckConstraint(
            "search_radius_meters BETWEEN 1 AND 50000",
            name="ck_application_setting_search_radius",
        ),
        sa.ForeignKeyConstraint(
            ["current_reference_position_id"],
            ["reference_position.id"],
            name="fk_application_setting_reference_position",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_setting")),
        sa.UniqueConstraint("singleton_key", name=op.f("uq_application_setting_singleton_key")),
    )

    settings_table = sa.table(
        "application_setting",
        sa.column("id", sa.Uuid()),
        sa.column("singleton_key", sa.String()),
        sa.column("collection_radius_meters", sa.Integer()),
        sa.column("search_radius_meters", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        settings_table,
        [
            {
                "id": uuid4(),
                "singleton_key": "primary",
                "collection_radius_meters": 50_000,
                "search_radius_meters": 50_000,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    """Drop geographic settings and their immutable history."""

    op.drop_table("application_setting")
    op.drop_index("ix_reference_position_point", table_name="reference_position")
    op.drop_index(op.f("ix_reference_position_municipality_code"), table_name="reference_position")
    op.drop_table("reference_position")
