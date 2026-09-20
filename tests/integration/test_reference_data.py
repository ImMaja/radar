"""PostGIS integration tests for versioned municipality boundaries."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from radar.persistence.reference_data import SqlAlchemyMunicipalityReferenceRepository
from radar.reference_data.contracts import MunicipalityReferenceError, MunicipalityReleaseSource
from radar.reference_data.service import MunicipalityReferenceService

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 20, 15, tzinfo=UTC)
DAX_LONGITUDE = -1.051952
DAX_LATITUDE = 43.70884


def polygon(longitude: float, latitude: float, size: float = 0.001) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [longitude - size, latitude - size],
                [longitude + size, latitude - size],
                [longitude + size, latitude + size],
                [longitude - size, latitude + size],
                [longitude - size, latitude - size],
            ]
        ],
    }


def feature(code: str, name: str, geometry: dict[str, object]) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"code": code, "nom": name},
        "geometry": geometry,
    }


def write_release(path: Path, features: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def source(identifier: str) -> MunicipalityReleaseSource:
    return MunicipalityReleaseSource(
        resource_identifier=identifier,
        resource_url=f"https://example.data.gouv.fr/{identifier}/communes-100m.geojson",
        published_on=date(2026, 1, 1),
        retrieved_at=NOW,
        license_name="ODbL-1.0",
    )


def test_activates_releases_idempotently_and_selects_with_the_margin(
    integration_database_url: str,
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "communes-2026.geojson"
    write_release(
        first_path,
        [
            feature("40088", "Dax", polygon(DAX_LONGITUDE, DAX_LATITUDE, 0.01)),
            feature("40001", "Commune de bordure", polygon(-0.430, DAX_LATITUDE)),
            feature("33063", "Bordeaux", polygon(-0.5792, 44.8378, 0.01)),
            feature("97105", "Basse-Terre", polygon(-61.73, 15.99, 0.01)),
        ],
    )
    second_path = tmp_path / "communes-2027.geojson"
    write_release(
        second_path,
        [feature("40088", "Dax", polygon(DAX_LONGITUDE, DAX_LATITUDE, 0.01))],
    )

    engine = create_engine(integration_database_url)
    service = MunicipalityReferenceService(
        SqlAlchemyMunicipalityReferenceRepository(engine),
        clock=lambda: NOW,
    )
    try:
        first = service.import_file(first_path, source("2026"))
        assert first.boundary_count == 3
        assert first.already_active is False

        repeated = service.import_file(first_path, source("2026-repeated"))
        assert repeated.id == first.id
        assert repeated.already_active is True

        selection = service.select_candidates(DAX_LONGITUDE, DAX_LATITUDE, 50_000)
        assert selection.dataset_release_id == first.id
        assert selection.margin_meters == 1_000
        assert [item.code for item in selection.municipalities] == ["40001", "40088"]

        with engine.connect() as connection:
            edge_distance = connection.execute(
                text(
                    """
                    SELECT ST_Distance(
                        boundary::geography,
                        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
                    )
                    FROM commune_boundary
                    WHERE dataset_release_id = :release_id AND municipality_code = '40001'
                    """
                ),
                {
                    "longitude": DAX_LONGITUDE,
                    "latitude": DAX_LATITUDE,
                    "release_id": first.id,
                },
            ).scalar_one()
        assert 50_000 < edge_distance < 51_000

        second = service.import_file(second_path, source("2027"))
        assert second.id != first.id
        assert second.already_active is False
        assert [
            item.code
            for item in service.select_candidates(
                DAX_LONGITUDE, DAX_LATITUDE, 50_000
            ).municipalities
        ] == ["40088"]

        with engine.connect() as connection:
            statuses = connection.execute(
                text("SELECT resource_identifier, status FROM dataset_release ORDER BY created_at")
            ).all()
        assert [(row.resource_identifier, row.status) for row in statuses] == [
            ("2026", "RETIRED"),
            ("2027", "ACTIVE"),
        ]
    finally:
        engine.dispose()


def test_repairs_source_topology_but_never_activates_an_empty_repair(
    integration_database_url: str,
    tmp_path: Path,
) -> None:
    valid_path = tmp_path / "valid.geojson"
    write_release(
        valid_path,
        [feature("40088", "Dax", polygon(DAX_LONGITUDE, DAX_LATITUDE, 0.01))],
    )
    repairable_path = tmp_path / "repairable.geojson"
    write_release(
        repairable_path,
        [
            feature(
                "40001",
                "Contour croisé",
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[-1.1, 43.6], [-1.0, 43.8], [-1.1, 43.8], [-1.0, 43.6], [-1.1, 43.6]]
                    ],
                },
            )
        ],
    )
    unrecoverable_path = tmp_path / "unrecoverable.geojson"
    write_release(
        unrecoverable_path,
        [
            feature(
                "40002",
                "Contour effondré",
                {
                    "type": "Polygon",
                    "coordinates": [[[-1.05, 43.7], [-1.05, 43.7], [-1.05, 43.7], [-1.05, 43.7]]],
                },
            )
        ],
    )

    engine = create_engine(integration_database_url)
    service = MunicipalityReferenceService(
        SqlAlchemyMunicipalityReferenceRepository(engine),
        clock=lambda: NOW,
    )
    try:
        service.import_file(valid_path, source("valid"))
        repaired = service.import_file(repairable_path, source("repairable"))
        with pytest.raises(MunicipalityReferenceError, match="activate"):
            service.import_file(unrecoverable_path, source("unrecoverable"))

        selection = service.select_candidates(DAX_LONGITUDE, DAX_LATITUDE, 50_000)
        assert selection.dataset_release_id == repaired.id
        with engine.connect() as connection:
            release_rows = connection.execute(
                text(
                    """
                    SELECT status, metadata->>'repaired_invalid_geometry_count' AS repair_count
                    FROM dataset_release
                    ORDER BY created_at
                    """
                )
            ).all()
            repaired_is_valid = connection.execute(
                text(
                    """
                    SELECT ST_IsValid(boundary) AND NOT ST_IsEmpty(boundary)
                    FROM commune_boundary
                    WHERE dataset_release_id = :release_id
                    """
                ),
                {"release_id": repaired.id},
            ).scalar_one()
        assert [(row.status, row.repair_count) for row in release_rows] == [
            ("RETIRED", "0"),
            ("ACTIVE", "1"),
        ]
        assert repaired_is_valid is True
    finally:
        engine.dispose()
