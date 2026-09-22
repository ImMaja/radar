"""Register the Géoplateforme fallback-geocoding source.

Revision ID: 20260921_09
Revises: 20260921_08
Create Date: 2026-09-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260921_09"
down_revision: str | None = "20260921_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Register the independent address-geocoding provenance."""

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
            'GEOPLATFORM_GEOCODER',
            'API de géocodage de la Géoplateforme',
            'IGN',
            'https://data.geopf.fr/geocodage/search',
            NULL,
            TRUE,
            '{"index": "address", "fallback_for": "SIRENE"}'::jsonb,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        """
    )


def downgrade() -> None:
    """Remove fallback results before unregistering their source."""

    op.execute(
        """
        UPDATE collection_item
        SET
            geographic_classification = 'LOCATION_UNKNOWN',
            distance_meters = NULL,
            reason = jsonb_build_object(
                'code', 'POSITION_GEOCODING_REQUIRED',
                'rule_version', 'sirene-position-selection-v1'
            )
        WHERE reason ->> 'position_source' = 'GEOPLATFORM_GEOCODER'
        """
    )
    op.execute("DELETE FROM candidate_position WHERE origin = 'GEOPLATFORM_GEOCODER'")
    op.execute("DELETE FROM source_observation WHERE data_source_code = 'GEOPLATFORM_GEOCODER'")
    op.execute("DELETE FROM collection_source_run WHERE source = 'GEOPLATFORM_GEOCODER'")
    op.execute("DELETE FROM data_source WHERE code = 'GEOPLATFORM_GEOCODER'")
