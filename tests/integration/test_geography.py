"""PostgreSQL/PostGIS integration tests for reference geography."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text

from radar.geography.contracts import GeocodedAddress, StructuredAddress
from radar.persistence.geography import SqlAlchemyGeographyRepository

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)


def dax_candidate() -> GeocodedAddress:
    return GeocodedAddress(
        normalized_label="12 Rue Saint Pierre 40100 Dax",
        structured_address=StructuredAddress(
            house_number="12",
            street="Rue Saint Pierre",
            postcode="40100",
            city="Dax",
            context="40, Landes, Nouvelle-Aquitaine",
        ),
        longitude=-1.051952,
        latitude=43.70884,
        municipality_code="40088",
        ban_id="40088_1750_00012",
        result_type="housenumber",
        score=0.9653,
        provider_name="Géoplateforme",
        provider_url="https://data.geopf.fr/geocodage/search",
    )


def bayonne_candidate() -> GeocodedAddress:
    return GeocodedAddress(
        normalized_label="1 Avenue Maréchal Leclerc 64100 Bayonne",
        structured_address=StructuredAddress(
            house_number="1",
            street="Avenue Maréchal Leclerc",
            postcode="64100",
            city="Bayonne",
            context="64, Pyrénées-Atlantiques, Nouvelle-Aquitaine",
        ),
        longitude=-1.4748,
        latitude=43.4933,
        municipality_code="64102",
        ban_id=None,
        result_type="housenumber",
        score=0.91,
        provider_name="Géoplateforme",
        provider_url="https://data.geopf.fr/geocodage/search",
    )


def test_confirmed_position_is_historical_and_radii_are_independent(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    repository = SqlAlchemyGeographyRepository(engine)
    try:
        initial = repository.get_settings()
        assert initial.reference_position is None
        assert initial.collection_radius_meters == 50_000
        assert initial.search_radius_meters == 50_000

        candidate = repository.save_candidate(
            "12 rue Saint-Pierre 40100 Dax",
            dax_candidate(),
            NOW,
        )
        assert repository.get_settings().reference_position is None

        confirmed = repository.confirm_candidate(candidate.id, NOW)
        assert confirmed.reference_position is not None
        assert confirmed.reference_position.id == candidate.id
        assert confirmed.reference_position.confirmed_at == NOW

        changed = repository.update_radii(50_000, 30_000, NOW)
        assert changed.reference_position is not None
        assert changed.reference_position.id == candidate.id
        assert changed.collection_radius_meters == 50_000
        assert changed.search_radius_meters == 30_000

        replacement = repository.save_candidate(
            "1 avenue Maréchal Leclerc 64100 Bayonne",
            bayonne_candidate(),
            NOW,
        )
        replaced = repository.confirm_candidate(replacement.id, NOW)
        assert replaced.reference_position is not None
        assert replaced.reference_position.id == replacement.id

        with engine.connect() as connection:
            history_count = connection.execute(
                text("SELECT count(*) FROM reference_position")
            ).scalar_one()
        assert history_count == 2
    finally:
        engine.dispose()


def test_postgis_filters_local_points_by_geodesic_distance(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    repository = SqlAlchemyGeographyRepository(engine)
    try:
        candidate = repository.save_candidate(
            "12 rue Saint-Pierre 40100 Dax",
            dax_candidate(),
            NOW,
        )
        repository.confirm_candidate(candidate.id, NOW)

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT sample.name,
                           ST_Distance(
                               reference.point,
                               ST_SetSRID(ST_MakePoint(sample.longitude, sample.latitude), 4326)
                                   ::geography
                           ) AS distance_meters
                    FROM reference_position AS reference
                    CROSS JOIN (
                        VALUES
                            ('Dax', -1.051952::double precision, 43.70884::double precision),
                            ('Saint-Vincent-de-Tyrosse', -1.3074, 43.6607),
                            ('Bayonne', -1.4748, 43.4933),
                            ('Bordeaux', -0.5792, 44.8378)
                    ) AS sample(name, longitude, latitude)
                    WHERE reference.id = :reference_id
                      AND ST_DWithin(
                          reference.point,
                          ST_SetSRID(ST_MakePoint(sample.longitude, sample.latitude), 4326)
                              ::geography,
                          :radius_meters
                      )
                    ORDER BY distance_meters
                    """
                ),
                {"reference_id": candidate.id, "radius_meters": 30_000},
            ).all()

        assert [row.name for row in rows] == ["Dax", "Saint-Vincent-de-Tyrosse"]
        assert rows[0].distance_meters == pytest.approx(0, abs=0.01)
        assert 20_000 < rows[1].distance_meters < 30_000
    finally:
        engine.dispose()
