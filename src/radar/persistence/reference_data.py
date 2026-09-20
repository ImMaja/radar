"""PostgreSQL/PostGIS persistence for versioned municipality boundaries."""

import json
from collections.abc import Iterator
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.reference_data.contracts import (
    CandidateMunicipality,
    DatasetRelease,
    MunicipalityBoundary,
    MunicipalityBoundaryFile,
    MunicipalityReferenceError,
    MunicipalityReferenceUnavailableError,
    MunicipalityReleaseSource,
    MunicipalitySelection,
)

SOURCE_NAME = "data.gouv.fr"
DATASET_CODE = "contours-administratifs-communes-100m"
BULK_INSERT_SIZE = 1_000
EXPECTED_SCHEMA: dict[str, object] = {
    "format": "GeoJSON",
    "root_type": "FeatureCollection",
    "feature_type": "Feature",
    "required_properties": ["code", "nom"],
    "geometry_types": ["Polygon", "MultiPolygon"],
    "crs": "EPSG:4326",
}

_ACTIVE_RELEASE = text(
    """
    SELECT
        release.id,
        release.resource_identifier,
        release.file_digest,
        release.updated_at,
        count(boundary.municipality_code) AS boundary_count
    FROM dataset_release AS release
    JOIN commune_boundary AS boundary ON boundary.dataset_release_id = release.id
    WHERE release.dataset_code = :dataset_code
      AND release.status = 'ACTIVE'
    GROUP BY release.id
    """
)


def _chunks(
    boundaries: tuple[MunicipalityBoundary, ...],
) -> Iterator[tuple[MunicipalityBoundary, ...]]:
    for offset in range(0, len(boundaries), BULK_INSERT_SIZE):
        yield boundaries[offset : offset + BULK_INSERT_SIZE]


def _release_from_row(row: RowMapping, *, already_active: bool) -> DatasetRelease:
    return DatasetRelease(
        id=cast(UUID, row["id"]),
        dataset_code=DATASET_CODE,
        resource_identifier=cast(str, row["resource_identifier"]),
        file_digest=cast(str, row["file_digest"]),
        status="ACTIVE",
        boundary_count=cast(int, row["boundary_count"]),
        activated_at=cast(datetime, row["updated_at"]),
        already_active=already_active,
    )


class SqlAlchemyMunicipalityReferenceRepository:
    """Activate complete releases and query their contours atomically."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def activate(
        self,
        source: MunicipalityReleaseSource,
        parsed_file: MunicipalityBoundaryFile,
        now: datetime,
    ) -> DatasetRelease:
        """Insert all boundaries, validate them in PostGIS, then switch the active release."""

        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:dataset_code, 0))"),
                    {"dataset_code": DATASET_CODE},
                )
                active = (
                    connection.execute(
                        _ACTIVE_RELEASE,
                        {"dataset_code": DATASET_CODE},
                    )
                    .mappings()
                    .one_or_none()
                )
                if active is not None and active["file_digest"] == parsed_file.sha256:
                    return _release_from_row(active, already_active=True)

                connection.execute(
                    text(
                        """
                        CREATE TEMPORARY TABLE radar_commune_boundary_stage (
                            municipality_code varchar(5) PRIMARY KEY,
                            official_name text NOT NULL,
                            boundary geometry(Geometry, 4326) NOT NULL
                        ) ON COMMIT DROP
                        """
                    )
                )
                insert_staged_boundary = text(
                    """
                    INSERT INTO radar_commune_boundary_stage (
                        municipality_code,
                        official_name,
                        boundary
                    ) VALUES (
                        :municipality_code,
                        :official_name,
                        ST_SetSRID(ST_GeomFromGeoJSON(:geometry_json), 4326)
                    )
                    """
                )
                for chunk in _chunks(parsed_file.boundaries):
                    connection.execute(
                        insert_staged_boundary,
                        [
                            {
                                "municipality_code": boundary.code,
                                "official_name": boundary.official_name,
                                "geometry_json": boundary.geometry_json,
                            }
                            for boundary in chunk
                        ],
                    )

                staged_validation = (
                    connection.execute(
                        text(
                            """
                            SELECT
                                count(*) AS boundary_count,
                                count(*) FILTER (WHERE ST_IsEmpty(boundary)) AS empty_count,
                                count(*) FILTER (WHERE NOT ST_IsValid(boundary)) AS invalid_count
                            FROM radar_commune_boundary_stage
                            """
                        )
                    )
                    .mappings()
                    .one()
                )
                expected_count = len(parsed_file.boundaries)
                if (
                    staged_validation["boundary_count"] != expected_count
                    or staged_validation["empty_count"] != 0
                ):
                    raise MunicipalityReferenceError(
                        "PostGIS rejected an empty or incomplete municipality release"
                    )

                metadata = {
                    "source_feature_count": parsed_file.source_feature_count,
                    "loaded_boundary_count": expected_count,
                    "ignored_non_metropolitan_count": (parsed_file.ignored_non_metropolitan_count),
                    "geometry_counts": parsed_file.geometry_counts,
                    "repaired_invalid_geometry_count": staged_validation["invalid_count"],
                }
                release_id = uuid4()
                connection.execute(
                    text(
                        """
                        INSERT INTO dataset_release (
                            id,
                            source_name,
                            dataset_code,
                            resource_identifier,
                            resource_url,
                            published_on,
                            retrieved_at,
                            file_size_bytes,
                            digest_algorithm,
                            file_digest,
                            expected_schema,
                            status,
                            license_name,
                            metadata,
                            created_at,
                            updated_at
                        ) VALUES (
                            :id,
                            :source_name,
                            :dataset_code,
                            :resource_identifier,
                            :resource_url,
                            :published_on,
                            :retrieved_at,
                            :file_size_bytes,
                            'SHA-256',
                            :file_digest,
                            CAST(:expected_schema AS jsonb),
                            'STAGED',
                            :license_name,
                            CAST(:metadata AS jsonb),
                            :created_at,
                            :updated_at
                        )
                        """
                    ),
                    {
                        "id": release_id,
                        "source_name": SOURCE_NAME,
                        "dataset_code": DATASET_CODE,
                        "resource_identifier": source.resource_identifier,
                        "resource_url": source.resource_url,
                        "published_on": source.published_on,
                        "retrieved_at": source.retrieved_at,
                        "file_size_bytes": parsed_file.file_size_bytes,
                        "file_digest": parsed_file.sha256,
                        "expected_schema": json.dumps(EXPECTED_SCHEMA),
                        "license_name": source.license_name,
                        "metadata": json.dumps(metadata),
                        "created_at": now,
                        "updated_at": now,
                    },
                )

                connection.execute(
                    text(
                        """
                    INSERT INTO commune_boundary (
                        dataset_release_id,
                        municipality_code,
                        official_name,
                        boundary,
                        is_metropolitan_france
                    )
                    SELECT
                        :dataset_release_id,
                        municipality_code,
                        official_name,
                        ST_Multi(
                            ST_CollectionExtract(
                                CASE
                                    WHEN ST_IsValid(boundary) THEN boundary
                                    ELSE ST_MakeValid(boundary)
                                END,
                                3
                            )
                        ),
                        TRUE
                    FROM radar_commune_boundary_stage
                    ORDER BY municipality_code
                    """
                    ),
                    {"dataset_release_id": release_id},
                )

                validation = (
                    connection.execute(
                        text(
                            """
                        SELECT
                            count(*) AS boundary_count,
                            count(DISTINCT municipality_code) AS distinct_code_count,
                            count(*) FILTER (WHERE NOT ST_IsValid(boundary)) AS invalid_count,
                            count(*) FILTER (WHERE ST_IsEmpty(boundary)) AS empty_count,
                            count(*) FILTER (
                                WHERE NOT ST_CoveredBy(
                                    boundary,
                                    ST_MakeEnvelope(-180, -90, 180, 90, 4326)
                                )
                            ) AS outside_wgs84_count
                        FROM commune_boundary
                        WHERE dataset_release_id = :release_id
                        """
                        ),
                        {"release_id": release_id},
                    )
                    .mappings()
                    .one()
                )
                if (
                    validation["boundary_count"] != expected_count
                    or validation["distinct_code_count"] != expected_count
                    or validation["invalid_count"] != 0
                    or validation["empty_count"] != 0
                    or validation["outside_wgs84_count"] != 0
                ):
                    raise MunicipalityReferenceError(
                        "PostGIS validation rejected the municipality release"
                    )

                connection.execute(
                    text(
                        """
                        UPDATE dataset_release
                        SET status = 'VALIDATED', updated_at = :now
                        WHERE id = :release_id AND status = 'STAGED'
                        """
                    ),
                    {"release_id": release_id, "now": now},
                )
                connection.execute(
                    text(
                        """
                        UPDATE dataset_release
                        SET status = 'RETIRED', updated_at = :now
                        WHERE dataset_code = :dataset_code AND status = 'ACTIVE'
                        """
                    ),
                    {"dataset_code": DATASET_CODE, "now": now},
                )
                connection.execute(
                    text(
                        """
                        UPDATE dataset_release
                        SET status = 'ACTIVE', updated_at = :now
                        WHERE id = :release_id AND status = 'VALIDATED'
                        """
                    ),
                    {"release_id": release_id, "now": now},
                )

                return DatasetRelease(
                    id=release_id,
                    dataset_code=DATASET_CODE,
                    resource_identifier=source.resource_identifier,
                    file_digest=parsed_file.sha256,
                    status="ACTIVE",
                    boundary_count=expected_count,
                    activated_at=now,
                    already_active=False,
                )
        except MunicipalityReferenceError:
            raise
        except SQLAlchemyError as error:
            raise MunicipalityReferenceError(
                "cannot validate and activate the municipality release"
            ) from error

    def select_candidates(
        self,
        longitude: float,
        latitude: float,
        collection_radius_meters: int,
        margin_meters: int,
    ) -> MunicipalitySelection:
        """Use the active release to intersect an indexable expanded geodesic circle."""

        try:
            with self._engine.connect() as connection:
                active = (
                    connection.execute(
                        text(
                            """
                        SELECT id, resource_identifier
                        FROM dataset_release
                        WHERE dataset_code = :dataset_code AND status = 'ACTIVE'
                        """
                        ),
                        {"dataset_code": DATASET_CODE},
                    )
                    .mappings()
                    .one_or_none()
                )
                if active is None:
                    raise MunicipalityReferenceUnavailableError(
                        "no active municipality reference release is available"
                    )

                rows = connection.execute(
                    text(
                        """
                        WITH selection_center AS (
                            SELECT ST_SetSRID(
                                ST_MakePoint(:longitude, :latitude),
                                4326
                            )::geography AS point
                        )
                        SELECT commune.municipality_code, commune.official_name
                        FROM commune_boundary AS commune
                        CROSS JOIN selection_center
                        WHERE commune.dataset_release_id = :dataset_release_id
                          AND ST_DWithin(
                              commune.boundary::geography,
                              selection_center.point,
                              :expanded_radius_meters
                          )
                        ORDER BY commune.municipality_code
                        """
                    ),
                    {
                        "longitude": longitude,
                        "latitude": latitude,
                        "expanded_radius_meters": collection_radius_meters + margin_meters,
                        "dataset_release_id": active["id"],
                    },
                ).mappings()
                municipalities = tuple(
                    CandidateMunicipality(
                        code=cast(str, row["municipality_code"]),
                        official_name=cast(str, row["official_name"]),
                    )
                    for row in rows
                )
        except MunicipalityReferenceUnavailableError:
            raise
        except SQLAlchemyError as error:
            raise MunicipalityReferenceError("cannot select candidate municipalities") from error

        return MunicipalitySelection(
            dataset_release_id=cast(UUID, active["id"]),
            resource_identifier=cast(str, active["resource_identifier"]),
            collection_radius_meters=collection_radius_meters,
            margin_meters=margin_meters,
            municipalities=municipalities,
        )
