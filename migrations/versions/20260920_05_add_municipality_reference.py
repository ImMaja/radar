"""Add versioned municipality boundaries used by Sirene collections.

Revision ID: 20260920_05
Revises: 20260920_04
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision: str = "20260920_05"
down_revision: str | None = "20260920_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class GeometryMultiPolygon(UserDefinedType[str]):
    """PostGIS WGS84 multipolygon used by this migration."""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        return "geometry(MultiPolygon,4326)"


def upgrade() -> None:
    """Create immutable reference releases and municipality boundaries."""

    op.create_table(
        "dataset_release",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("dataset_code", sa.String(length=100), nullable=False),
        sa.Column("resource_identifier", sa.String(length=256), nullable=False),
        sa.Column("resource_url", sa.Text(), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("digest_algorithm", sa.String(length=32), nullable=False),
        sa.Column("file_digest", sa.String(length=128), nullable=False),
        sa.Column("expected_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("license_name", sa.String(length=128), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("file_size_bytes > 0", name="ck_dataset_release_file_size"),
        sa.CheckConstraint(
            "status IN ('STAGED', 'VALIDATED', 'ACTIVE', 'REJECTED', 'RETIRED')",
            name="ck_dataset_release_status",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_release")),
    )
    op.create_index(
        "uq_dataset_release_active_dataset",
        "dataset_release",
        ["dataset_code"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_dataset_release_fingerprint",
        "dataset_release",
        ["dataset_code", "digest_algorithm", "file_digest"],
        unique=False,
    )

    op.create_table(
        "commune_boundary",
        sa.Column("dataset_release_id", sa.Uuid(), nullable=False),
        sa.Column("municipality_code", sa.String(length=5), nullable=False),
        sa.Column("official_name", sa.Text(), nullable=False),
        sa.Column("boundary", GeometryMultiPolygon(), nullable=False),
        sa.Column("is_metropolitan_france", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "municipality_code ~ '^(?:[0-9]{5}|2[AB][0-9]{3})$'",
            name="ck_commune_boundary_code",
        ),
        sa.CheckConstraint(
            "is_metropolitan_france IS TRUE",
            name="ck_commune_boundary_metropolitan",
        ),
        sa.CheckConstraint("NOT ST_IsEmpty(boundary)", name="ck_commune_boundary_not_empty"),
        sa.CheckConstraint("ST_IsValid(boundary)", name="ck_commune_boundary_valid"),
        sa.ForeignKeyConstraint(
            ["dataset_release_id"],
            ["dataset_release.id"],
            name="fk_commune_boundary_dataset_release",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_release_id",
            "municipality_code",
            name=op.f("pk_commune_boundary"),
        ),
    )
    op.create_index(
        "ix_commune_boundary_boundary",
        "commune_boundary",
        ["boundary"],
        unique=False,
        postgresql_using="gist",
    )
    op.execute(
        "CREATE INDEX ix_commune_boundary_boundary_geography "
        "ON commune_boundary USING gist ((boundary::geography))"
    )


def downgrade() -> None:
    """Drop municipality boundaries before their reference releases."""

    op.execute("DROP INDEX IF EXISTS ix_commune_boundary_boundary_geography")
    op.drop_index("ix_commune_boundary_boundary", table_name="commune_boundary")
    op.drop_table("commune_boundary")
    op.drop_index("ix_dataset_release_fingerprint", table_name="dataset_release")
    op.drop_index("uq_dataset_release_active_dataset", table_name="dataset_release")
    op.drop_table("dataset_release")
