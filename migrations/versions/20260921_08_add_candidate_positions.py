"""Add per-source candidate positions before prospect resolution.

Revision ID: 20260921_08
Revises: 20260921_07
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision: str = "20260921_08"
down_revision: str | None = "20260921_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class GeographyPoint(UserDefinedType[str]):
    """PostGIS WGS84 geography point used by this migration."""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        return "geography(Point,4326)"


def upgrade() -> None:
    """Create distinct position assessments and register the monthly file source."""

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
            'SIRENE_GEOLOCATION',
            'Géolocalisation des établissements Sirene',
            'INSEE',
            'https://www.data.gouv.fr/datasets/geolocalisation-des-etablissements-du-repertoire-sirene-pour-les-etudes-statistiques',
            'Licence Ouverte 2.0',
            TRUE,
            '{"format": "parquet", "frequency": "monthly"}'::jsonb,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        """
    )

    op.create_table(
        "candidate_position",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_item_id", sa.Uuid(), nullable=False),
        sa.Column("source_observation_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_release_id", sa.Uuid(), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("point", GeographyPoint(), nullable=True),
        sa.Column("source_crs", sa.String(length=32), nullable=True),
        sa.Column("quality_code", sa.String(length=32), nullable=True),
        sa.Column("precision", sa.String(length=32), nullable=False),
        sa.Column("usability", sa.String(length=32), nullable=False),
        sa.Column("municipality_consistent", sa.Boolean(), nullable=False),
        sa.Column("geographic_classification", sa.String(length=48), nullable=False),
        sa.Column("distance_meters", sa.Float(), nullable=True),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "origin IN ('SIRENE_API', 'SIRENE_GEOLOCATION', 'GEOPLATFORM_GEOCODER')",
            name="ck_candidate_position_origin",
        ),
        sa.CheckConstraint(
            "precision IN ('ROOFTOP', 'ADDRESS', 'STREET', 'MUNICIPALITY', 'UNKNOWN')",
            name="ck_candidate_position_precision",
        ),
        sa.CheckConstraint(
            "usability IN ('USABLE', 'TO_VERIFY', 'MISSING')",
            name="ck_candidate_position_usability",
        ),
        sa.CheckConstraint(
            "geographic_classification IN ("
            "'IN_RADIUS', 'OUTSIDE_RADIUS', 'LOCATION_UNKNOWN', "
            "'OUTSIDE_METROPOLITAN_FRANCE')",
            name="ck_candidate_position_geographic_classification",
        ),
        sa.CheckConstraint(
            "distance_meters IS NULL OR distance_meters >= 0",
            name="ck_candidate_position_distance",
        ),
        sa.CheckConstraint(
            "geographic_classification NOT IN ('IN_RADIUS', 'OUTSIDE_RADIUS') "
            "OR (point IS NOT NULL AND usability = 'USABLE' "
            "AND municipality_consistent IS TRUE AND distance_meters IS NOT NULL)",
            name="ck_candidate_position_exact_classification",
        ),
        sa.CheckConstraint(
            "geographic_classification <> 'LOCATION_UNKNOWN' OR distance_meters IS NULL",
            name="ck_candidate_position_unknown_distance",
        ),
        sa.ForeignKeyConstraint(
            ["collection_item_id"],
            ["collection_item.id"],
            name="fk_candidate_position_collection_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["source_observation.id"],
            name="fk_candidate_position_source_observation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_release_id"],
            ["dataset_release.id"],
            name="fk_candidate_position_dataset_release",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_position")),
        sa.UniqueConstraint(
            "collection_item_id",
            "origin",
            name="uq_candidate_position_item_origin",
        ),
    )
    op.create_index(
        op.f("ix_candidate_position_source_observation_id"),
        "candidate_position",
        ["source_observation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_position_dataset_release_id"),
        "candidate_position",
        ["dataset_release_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_position_point",
        "candidate_position",
        ["point"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    """Drop candidate positions and the monthly file source."""

    op.drop_index("ix_candidate_position_point", table_name="candidate_position")
    op.drop_table("candidate_position")
    op.execute(
        """
        UPDATE collection_item
        SET source_observation_id = NULL
        WHERE source_observation_id IN (
            SELECT id
            FROM source_observation
            WHERE data_source_code = 'SIRENE_GEOLOCATION'
        )
        """
    )
    op.execute(
        "DELETE FROM source_observation "
        "WHERE data_source_code = 'SIRENE_GEOLOCATION'"
    )
    op.execute("DELETE FROM data_source WHERE code = 'SIRENE_GEOLOCATION'")
