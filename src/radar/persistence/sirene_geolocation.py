"""PostgreSQL staging for the monthly Sirene geolocation reference file."""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.prospects.geolocation import (
    SIRENE_GEOLOCATION_ADAPTER_VERSION,
    SIRENE_GEOLOCATION_DATA_SOURCE_CODE,
    SIRENE_GEOLOCATION_DATASET_CODE,
    SIRENE_GEOLOCATION_RULE_VERSION,
    SIRENE_GEOLOCATION_SCHEMA_VERSION,
    SireneGeolocationImportError,
    SireneGeolocationRelease,
    SireneGeolocationReleaseSource,
    SireneGeolocationTarget,
    StagedSireneGeolocationPosition,
)
from radar.providers.sirene_geolocation import SireneGeolocationFile, SireneGeolocationScan

_EXPECTED_SCHEMA: dict[str, object] = {
    "format": "Parquet",
    "required_columns": [
        "SIRET",
        "X",
        "Y",
        "QUALITE_XY",
        "EPSG",
        "PLG_CODE_COMMUNE",
        "DISTANCE_PRECISION",
        "y_latitude",
        "x_longitude",
    ],
}

_INPUT_RECORDSET = """
jsonb_to_recordset(CAST(:positions AS jsonb)) AS input(
    observation_id uuid,
    position_id uuid,
    collection_item_id uuid,
    external_identity_id uuid,
    siret text,
    expected_municipality_code text,
    content_fingerprint text,
    payload jsonb,
    lambert_x double precision,
    lambert_y double precision,
    longitude double precision,
    latitude double precision,
    source_crs text,
    source_municipality_code text,
    quality_code text
)
"""


def _required_counter(counters: dict[str, object], key: str) -> int:
    value = counters.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SireneGeolocationImportError(
            "completed Sirene geolocation counters are invalid"
        )
    return value


class SqlAlchemySireneGeolocationRepository:
    """Stage only matched file positions and activate a release after reconciliation."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def targets(self, reservation: ReservedCollection) -> tuple[SireneGeolocationTarget, ...]:
        """Return each candidate from the successful API attempt exactly once."""

        try:
            with self._engine.connect() as connection:
                self._require_active_attempt(connection, reservation)
                rows = (
                    connection.execute(
                        text(
                            """
                            SELECT
                                item.id AS collection_item_id,
                                item.external_identity_id,
                                identity.canonical_value AS siret,
                                observation.payload #>> '{address,municipality_code}'
                                    AS municipality_code
                            FROM collection_item AS item
                            JOIN collection_batch AS batch
                              ON batch.id = item.collection_batch_id
                             AND batch.last_collection_attempt_id
                                    = item.collection_attempt_id
                             AND batch.state = 'SUCCEEDED'
                            JOIN collection_source_run AS source
                              ON source.id = batch.source_run_id
                             AND source.source = 'SIRENE_API'
                             AND source.status = 'SUCCEEDED'
                            JOIN external_identity AS identity
                              ON identity.id = item.external_identity_id
                            JOIN source_observation AS observation
                              ON observation.id = item.source_observation_id
                             AND observation.data_source_code = 'SIRENE_API'
                            WHERE item.collection_cycle_id = :cycle_id
                              AND item.normalization_result = 'VALID'
                            ORDER BY identity.canonical_value
                            """
                        ),
                        {"cycle_id": reservation.cycle_id},
                    )
                    .mappings()
                    .all()
                )
        except SireneGeolocationImportError:
            raise
        except SQLAlchemyError as error:
            raise SireneGeolocationImportError(
                "cannot load Sirene geolocation targets"
            ) from error

        targets = tuple(self._target_from_row(row) for row in rows)
        sirets = [target.siret for target in targets]
        if len(sirets) != len(set(sirets)):
            raise SireneGeolocationImportError(
                "the completed Sirene API collection contains duplicate candidate SIRETs"
            )
        return targets

    def prepare_release(
        self,
        reservation: ReservedCollection,
        source: SireneGeolocationReleaseSource,
        file: SireneGeolocationFile,
        now: datetime,
    ) -> SireneGeolocationRelease:
        """Bind the cycle to one staged or already active immutable file release."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:dataset_code, 0))"),
                    {"dataset_code": SIRENE_GEOLOCATION_DATASET_CODE},
                )
                existing = self._existing_run(connection, reservation.cycle_id)
                if existing is not None:
                    if existing["file_digest"] != file.sha256:
                        raise SireneGeolocationImportError(
                            "the collection cycle is already bound to another geolocation file"
                        )
                    return self._release_from_row(existing, newly_created=False)

                active = (
                    connection.execute(
                        text(
                            """
                            SELECT id, status, file_digest
                            FROM dataset_release
                            WHERE dataset_code = :dataset_code
                              AND status = 'ACTIVE'
                            """
                        ),
                        {"dataset_code": SIRENE_GEOLOCATION_DATASET_CODE},
                    )
                    .mappings()
                    .one_or_none()
                )
                newly_created = active is None or active["file_digest"] != file.sha256
                if newly_created:
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
                                'data.gouv.fr',
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
                                :now,
                                :now
                            )
                            """
                        ),
                        {
                            "id": release_id,
                            "dataset_code": SIRENE_GEOLOCATION_DATASET_CODE,
                            "resource_identifier": source.resource_identifier,
                            "resource_url": source.resource_url,
                            "published_on": source.published_on,
                            "retrieved_at": source.retrieved_at,
                            "file_size_bytes": file.file_size_bytes,
                            "file_digest": file.sha256,
                            "expected_schema": json.dumps(_EXPECTED_SCHEMA),
                            "license_name": source.license_name,
                            "metadata": json.dumps(
                                {
                                    "sha1": file.sha1,
                                    "source_row_count": file.source_row_count,
                                    "columns": list(file.columns),
                                }
                            ),
                            "now": now,
                        },
                    )
                else:
                    assert active is not None
                    release_id = cast(UUID, active["id"])

                source_run_id = uuid4()
                connection.execute(
                    text(
                        """
                        INSERT INTO collection_source_run (
                            id,
                            collection_cycle_id,
                            source,
                            dataset_release_id,
                            freshness_at,
                            started_at,
                            status,
                            counters,
                            metadata,
                            request_count,
                            retry_count,
                            error_count,
                            contract_version,
                            created_at,
                            updated_at
                        ) VALUES (
                            :id,
                            :cycle_id,
                            'SIRENE_GEOLOCATION',
                            :release_id,
                            NULL,
                            :now,
                            'RUNNING',
                            '{}'::jsonb,
                            CAST(:metadata AS jsonb),
                            0,
                            0,
                            0,
                            :contract_version,
                            :now,
                            :now
                        )
                        """
                    ),
                    {
                        "id": source_run_id,
                        "cycle_id": reservation.cycle_id,
                        "release_id": release_id,
                        "metadata": json.dumps(
                            {
                                "resource_identifier": source.resource_identifier,
                                "sha1": file.sha1,
                                "sha256": file.sha256,
                            }
                        ),
                        "contract_version": SIRENE_GEOLOCATION_ADAPTER_VERSION,
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO collection_reference_usage (
                            collection_cycle_id,
                            dataset_release_id,
                            role,
                            used_at
                        ) VALUES (
                            :cycle_id,
                            :release_id,
                            'SIRENE_GEOLOCATION',
                            :now
                        )
                        """
                    ),
                    {
                        "cycle_id": reservation.cycle_id,
                        "release_id": release_id,
                        "now": now,
                    },
                )
                return SireneGeolocationRelease(
                    id=release_id,
                    source_run_id=source_run_id,
                    status="RUNNING",
                    newly_created=newly_created,
                )
        except SireneGeolocationImportError:
            raise
        except SQLAlchemyError as error:
            raise SireneGeolocationImportError(
                "cannot prepare the Sirene geolocation release"
            ) from error

    def stage_positions(
        self,
        reservation: ReservedCollection,
        release: SireneGeolocationRelease,
        positions: tuple[StagedSireneGeolocationPosition, ...],
        now: datetime,
    ) -> None:
        """Persist one bounded batch of observations and independent assessments."""

        if not positions:
            return
        parameters: dict[str, object] = {
            "positions": self._position_payload(positions),
            "cycle_id": reservation.cycle_id,
            "job_id": reservation.job_id,
            "attempt_id": reservation.attempt_id,
            "release_id": release.id,
            "source_run_id": release.source_run_id,
            "data_source_code": SIRENE_GEOLOCATION_DATA_SOURCE_CODE,
            "adapter_version": SIRENE_GEOLOCATION_ADAPTER_VERSION,
            "schema_version": SIRENE_GEOLOCATION_SCHEMA_VERSION,
            "rule_version": SIRENE_GEOLOCATION_RULE_VERSION,
            "now": now,
        }
        try:
            with self._engine.begin() as connection:
                self._require_running_release(connection, reservation, release)
                self._validate_inputs(connection, parameters, len(positions))
                self._upsert_observations(connection, parameters)
                self._upsert_positions(connection, parameters)
                self._validate_staged_positions(connection, parameters, len(positions))
        except SireneGeolocationImportError:
            raise
        except SQLAlchemyError as error:
            raise SireneGeolocationImportError(
                "cannot stage Sirene geolocation positions"
            ) from error

    def complete_release(
        self,
        reservation: ReservedCollection,
        release: SireneGeolocationRelease,
        scan: SireneGeolocationScan,
        now: datetime,
    ) -> None:
        """Reconcile every target before atomically publishing the source and release."""

        try:
            with self._engine.begin() as connection:
                self._require_running_release(connection, reservation, release)
                evidence = (
                    connection.execute(
                        text(
                            """
                            SELECT
                                count(item.id) AS requested_count,
                                count(position.id) AS matched_count
                            FROM collection_item AS item
                            JOIN collection_batch AS batch
                              ON batch.id = item.collection_batch_id
                             AND batch.last_collection_attempt_id
                                    = item.collection_attempt_id
                             AND batch.state = 'SUCCEEDED'
                            JOIN collection_source_run AS api_source
                              ON api_source.id = batch.source_run_id
                             AND api_source.source = 'SIRENE_API'
                             AND api_source.status = 'SUCCEEDED'
                            LEFT JOIN candidate_position AS position
                              ON position.collection_item_id = item.id
                             AND position.origin = 'SIRENE_GEOLOCATION'
                             AND position.dataset_release_id = :release_id
                            WHERE item.collection_cycle_id = :cycle_id
                              AND item.normalization_result = 'VALID'
                            """
                        ),
                        {
                            "cycle_id": reservation.cycle_id,
                            "release_id": release.id,
                        },
                    )
                    .mappings()
                    .one()
                )
                if (
                    evidence["requested_count"] != scan.requested_siret_count
                    or evidence["matched_count"] != scan.matched_siret_count
                    or scan.missing_siret_count
                    != scan.requested_siret_count - scan.matched_siret_count
                ):
                    raise SireneGeolocationImportError(
                        "Sirene geolocation evidence does not match the staged positions"
                    )

                status = connection.execute(
                    text(
                        """
                        SELECT status
                        FROM dataset_release
                        WHERE id = :release_id
                        FOR UPDATE
                        """
                    ),
                    {"release_id": release.id},
                ).scalar_one()
                if status == "STAGED":
                    connection.execute(
                        text(
                            """
                            UPDATE dataset_release
                            SET status = 'VALIDATED', updated_at = :now
                            WHERE id = :release_id AND status = 'STAGED'
                            """
                        ),
                        {"release_id": release.id, "now": now},
                    )
                    connection.execute(
                        text(
                            """
                            UPDATE dataset_release
                            SET status = 'RETIRED', updated_at = :now
                            WHERE dataset_code = :dataset_code
                              AND status = 'ACTIVE'
                            """
                        ),
                        {"dataset_code": SIRENE_GEOLOCATION_DATASET_CODE, "now": now},
                    )
                    connection.execute(
                        text(
                            """
                            UPDATE dataset_release
                            SET status = 'ACTIVE', updated_at = :now
                            WHERE id = :release_id AND status = 'VALIDATED'
                            """
                        ),
                        {"release_id": release.id, "now": now},
                    )
                elif status != "ACTIVE":
                    raise SireneGeolocationImportError(
                        "Sirene geolocation release is not publishable"
                    )

                connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET
                            status = 'SUCCEEDED',
                            finished_at = :now,
                            counters = CAST(:counters AS jsonb),
                            updated_at = :now
                        WHERE id = :source_run_id
                          AND collection_cycle_id = :cycle_id
                          AND status = 'RUNNING'
                        """
                    ),
                    {
                        "source_run_id": release.source_run_id,
                        "cycle_id": reservation.cycle_id,
                        "counters": json.dumps(
                            {
                                "source_row_count": scan.source_row_count,
                                "requested_siret_count": scan.requested_siret_count,
                                "matched_siret_count": scan.matched_siret_count,
                                "missing_siret_count": scan.missing_siret_count,
                                "emitted_batch_count": scan.emitted_batch_count,
                            }
                        ),
                        "now": now,
                    },
                )
        except SireneGeolocationImportError:
            raise
        except SQLAlchemyError as error:
            raise SireneGeolocationImportError(
                "cannot complete the Sirene geolocation release"
            ) from error

    def completed_scan(
        self,
        reservation: ReservedCollection,
        release: SireneGeolocationRelease,
    ) -> SireneGeolocationScan:
        """Rebuild the reconciled result without rescanning an already completed source."""

        try:
            with self._engine.connect() as connection:
                self._require_active_attempt(connection, reservation)
                row = (
                    connection.execute(
                        text(
                            """
                            SELECT source.counters, release.file_size_bytes,
                                   release.file_digest, release.metadata
                            FROM collection_source_run AS source
                            JOIN dataset_release AS release
                              ON release.id = source.dataset_release_id
                            WHERE source.id = :source_run_id
                              AND source.collection_cycle_id = :cycle_id
                              AND source.status = 'SUCCEEDED'
                              AND release.id = :release_id
                              AND release.status = 'ACTIVE'
                            """
                        ),
                        {
                            "source_run_id": release.source_run_id,
                            "cycle_id": reservation.cycle_id,
                            "release_id": release.id,
                        },
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise SireneGeolocationImportError(
                "cannot reload the completed Sirene geolocation scan"
            ) from error
        if row is None:
            raise SireneGeolocationImportError(
                "completed Sirene geolocation evidence is unavailable"
            )
        counters = cast(dict[str, object], row["counters"])
        metadata = cast(dict[str, object], row["metadata"])
        columns = metadata.get("columns")
        sha1 = metadata.get("sha1")
        if not isinstance(columns, list) or not all(isinstance(value, str) for value in columns):
            raise SireneGeolocationImportError(
                "completed Sirene geolocation column evidence is invalid"
            )
        if not isinstance(sha1, str):
            raise SireneGeolocationImportError(
                "completed Sirene geolocation SHA-1 evidence is invalid"
            )
        return SireneGeolocationScan(
            file_size_bytes=cast(int, row["file_size_bytes"]),
            sha1=sha1,
            sha256=cast(str, row["file_digest"]),
            source_row_count=_required_counter(counters, "source_row_count"),
            requested_siret_count=_required_counter(counters, "requested_siret_count"),
            matched_siret_count=_required_counter(counters, "matched_siret_count"),
            missing_siret_count=_required_counter(counters, "missing_siret_count"),
            emitted_batch_count=_required_counter(counters, "emitted_batch_count"),
            columns=tuple(columns),
        )

    def fail_release(
        self,
        reservation: ReservedCollection,
        release: SireneGeolocationRelease,
        *,
        code: str,
        now: datetime,
    ) -> None:
        """Remove unpublished assessments and retain non-sensitive failure evidence."""

        try:
            with self._engine.begin() as connection:
                self._require_running_release(connection, reservation, release)
                connection.execute(
                    text(
                        """
                        DELETE FROM candidate_position AS position
                        USING collection_item AS item
                        WHERE position.collection_item_id = item.id
                          AND item.collection_cycle_id = :cycle_id
                          AND position.origin = 'SIRENE_GEOLOCATION'
                          AND position.dataset_release_id = :release_id
                        """
                    ),
                    {
                        "cycle_id": reservation.cycle_id,
                        "release_id": release.id,
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET
                            status = 'FAILED',
                            finished_at = :now,
                            error_count = error_count + 1,
                            metadata = metadata || jsonb_build_object(
                                'failure', jsonb_build_object('code', CAST(:code AS text))
                            ),
                            updated_at = :now
                        WHERE id = :source_run_id
                          AND collection_cycle_id = :cycle_id
                          AND status = 'RUNNING'
                        """
                    ),
                    {
                        "source_run_id": release.source_run_id,
                        "cycle_id": reservation.cycle_id,
                        "code": code,
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE dataset_release
                        SET status = 'REJECTED', updated_at = :now
                        WHERE id = :release_id AND status = 'STAGED'
                        """
                    ),
                    {"release_id": release.id, "now": now},
                )
        except SireneGeolocationImportError:
            raise
        except SQLAlchemyError as error:
            raise SireneGeolocationImportError(
                "cannot fail the Sirene geolocation release safely"
            ) from error

    @staticmethod
    def _target_from_row(row: RowMapping) -> SireneGeolocationTarget:
        values = (
            row["collection_item_id"],
            row["external_identity_id"],
            row["siret"],
            row["municipality_code"],
        )
        if any(value is None for value in values):
            raise SireneGeolocationImportError(
                "a Sirene geolocation target has incomplete identity or municipality data"
            )
        return SireneGeolocationTarget(
            collection_item_id=cast(UUID, row["collection_item_id"]),
            external_identity_id=cast(UUID, row["external_identity_id"]),
            siret=cast(str, row["siret"]),
            municipality_code=cast(str, row["municipality_code"]),
        )

    @staticmethod
    def _position_payload(
        positions: Sequence[StagedSireneGeolocationPosition],
    ) -> str:
        return json.dumps(
            [
                {
                    "observation_id": str(uuid4()),
                    "position_id": str(uuid4()),
                    "collection_item_id": str(position.collection_item_id),
                    "external_identity_id": str(position.external_identity_id),
                    "siret": position.siret,
                    "expected_municipality_code": position.expected_municipality_code,
                    "content_fingerprint": position.content_fingerprint,
                    "payload": position.payload,
                    "lambert_x": position.lambert_x,
                    "lambert_y": position.lambert_y,
                    "longitude": position.longitude,
                    "latitude": position.latitude,
                    "source_crs": position.source_crs,
                    "source_municipality_code": position.source_municipality_code,
                    "quality_code": position.quality_code,
                }
                for position in positions
            ],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _existing_run(connection: Connection, cycle_id: UUID) -> RowMapping | None:
        return (
            connection.execute(
                text(
                    """
                    SELECT
                        source.id AS source_run_id,
                        source.status,
                        release.id AS release_id,
                        release.file_digest
                    FROM collection_source_run AS source
                    JOIN dataset_release AS release ON release.id = source.dataset_release_id
                    WHERE source.collection_cycle_id = :cycle_id
                      AND source.source = 'SIRENE_GEOLOCATION'
                    """
                ),
                {"cycle_id": cycle_id},
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _release_from_row(row: RowMapping, *, newly_created: bool) -> SireneGeolocationRelease:
        return SireneGeolocationRelease(
            id=cast(UUID, row["release_id"]),
            source_run_id=cast(UUID, row["source_run_id"]),
            status=cast(str, row["status"]),
            newly_created=newly_created,
        )

    @staticmethod
    def _require_active_attempt(
        connection: Connection,
        reservation: ReservedCollection,
    ) -> None:
        active = connection.execute(
            text(
                """
                SELECT job.id
                FROM collection_job AS job
                JOIN collection_attempt AS attempt ON attempt.collection_job_id = job.id
                WHERE job.id = :job_id
                  AND job.cycle_id = :cycle_id
                  AND job.state = 'RUNNING'
                  AND attempt.id = :attempt_id
                  AND attempt.finished_at IS NULL
                """
            ),
            {
                "job_id": reservation.job_id,
                "cycle_id": reservation.cycle_id,
                "attempt_id": reservation.attempt_id,
            },
        ).scalar_one_or_none()
        if active is None:
            raise SireneGeolocationImportError(
                "Sirene geolocation import requires the active collection attempt"
            )

    def _require_running_release(
        self,
        connection: Connection,
        reservation: ReservedCollection,
        release: SireneGeolocationRelease,
    ) -> None:
        self._require_active_attempt(connection, reservation)
        running = connection.execute(
            text(
                """
                SELECT source.id
                FROM collection_source_run AS source
                JOIN dataset_release AS release ON release.id = source.dataset_release_id
                WHERE source.id = :source_run_id
                  AND source.collection_cycle_id = :cycle_id
                  AND source.source = 'SIRENE_GEOLOCATION'
                  AND source.status = 'RUNNING'
                  AND release.id = :release_id
                  AND release.status IN ('STAGED', 'ACTIVE')
                """
            ),
            {
                "source_run_id": release.source_run_id,
                "cycle_id": reservation.cycle_id,
                "release_id": release.id,
            },
        ).scalar_one_or_none()
        if running is None:
            raise SireneGeolocationImportError(
                "Sirene geolocation release is not running for this cycle"
            )

    @staticmethod
    def _validate_inputs(
        connection: Connection,
        parameters: dict[str, object],
        expected_count: int,
    ) -> None:
        evidence = (
            connection.execute(
                text(
                    f"""
                    SELECT
                        count(*) AS input_count,
                        count(DISTINCT input.siret) AS distinct_siret_count,
                        count(*) FILTER (
                            WHERE item.id IS NULL
                               OR batch.id IS NULL
                               OR api_source.id IS NULL
                               OR item.external_identity_id
                                      IS DISTINCT FROM input.external_identity_id
                               OR identity.canonical_value IS DISTINCT FROM input.siret
                               OR observation.payload #>> '{{address,municipality_code}}'
                                      IS DISTINCT FROM input.expected_municipality_code
                        ) AS mismatch_count
                    FROM {_INPUT_RECORDSET}
                    LEFT JOIN collection_item AS item
                      ON item.id = input.collection_item_id
                     AND item.collection_cycle_id = :cycle_id
                    LEFT JOIN collection_batch AS batch
                      ON batch.id = item.collection_batch_id
                     AND batch.last_collection_attempt_id = item.collection_attempt_id
                     AND batch.state = 'SUCCEEDED'
                    LEFT JOIN collection_source_run AS api_source
                      ON api_source.id = batch.source_run_id
                     AND api_source.source = 'SIRENE_API'
                     AND api_source.status = 'SUCCEEDED'
                    LEFT JOIN external_identity AS identity
                      ON identity.id = item.external_identity_id
                    LEFT JOIN source_observation AS observation
                      ON observation.id = item.source_observation_id
                     AND observation.data_source_code = 'SIRENE_API'
                    """
                ),
                parameters,
            )
            .mappings()
            .one()
        )
        if (
            evidence["input_count"] != expected_count
            or evidence["distinct_siret_count"] != expected_count
            or evidence["mismatch_count"] != 0
        ):
            raise SireneGeolocationImportError(
                "Sirene geolocation positions do not match the completed API candidates"
            )

    @staticmethod
    def _upsert_observations(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                f"""
                INSERT INTO source_observation (
                    id,
                    data_source_code,
                    external_identity_id,
                    collection_cycle_id,
                    dataset_release_id,
                    retrieved_at,
                    adapter_version,
                    schema_version,
                    content_fingerprint,
                    payload,
                    validation_status
                )
                SELECT
                    input.observation_id,
                    :data_source_code,
                    input.external_identity_id,
                    :cycle_id,
                    :release_id,
                    :now,
                    :adapter_version,
                    :schema_version,
                    input.content_fingerprint,
                    input.payload,
                    'VALID'
                FROM {_INPUT_RECORDSET}
                ON CONFLICT (data_source_code, external_identity_id, content_fingerprint)
                DO NOTHING
                """
            ),
            parameters,
        )

    @staticmethod
    def _upsert_positions(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                f"""
                WITH input_rows AS (
                    SELECT * FROM {_INPUT_RECORDSET}
                ),
                context AS (
                    SELECT
                        input.*,
                        observation.id AS source_observation_id,
                        cycle.center,
                        cycle.collection_radius_meters,
                        commune.selection_margin_meters,
                        boundary.boundary,
                        CASE
                            WHEN input.longitude BETWEEN -180 AND 180
                             AND input.latitude BETWEEN -90 AND 90
                            THEN ST_SetSRID(
                                ST_MakePoint(input.longitude, input.latitude),
                                4326
                            )
                            WHEN input.source_crs = '2154'
                             AND input.lambert_x BETWEEN -1000000 AND 2000000
                             AND input.lambert_y BETWEEN 5000000 AND 8000000
                            THEN ST_Transform(
                                ST_SetSRID(
                                    ST_MakePoint(input.lambert_x, input.lambert_y),
                                    2154
                                ),
                                4326
                            )
                            ELSE NULL
                        END AS source_point
                    FROM input_rows AS input
                    JOIN source_observation AS observation
                      ON observation.data_source_code = :data_source_code
                     AND observation.external_identity_id = input.external_identity_id
                     AND observation.content_fingerprint = input.content_fingerprint
                    JOIN collection_cycle AS cycle ON cycle.id = :cycle_id
                    JOIN collection_cycle_commune AS commune
                      ON commune.collection_cycle_id = cycle.id
                     AND commune.municipality_code = input.expected_municipality_code
                    JOIN commune_boundary AS boundary
                      ON boundary.dataset_release_id = commune.dataset_release_id
                     AND boundary.municipality_code = commune.municipality_code
                ),
                assessed AS (
                    SELECT
                        context.*,
                        COALESCE(
                            context.source_municipality_code
                                = context.expected_municipality_code
                            AND context.source_point IS NOT NULL
                            AND ST_DWithin(
                                context.boundary::geography,
                                context.source_point::geography,
                                context.selection_margin_meters
                            ),
                            FALSE
                        ) AS municipality_consistent,
                        COALESCE(
                            context.quality_code IN ('11', '12', '21', '22'),
                            FALSE
                        ) AS quality_usable
                    FROM context
                )
                INSERT INTO candidate_position (
                    id,
                    collection_item_id,
                    source_observation_id,
                    dataset_release_id,
                    origin,
                    point,
                    source_crs,
                    quality_code,
                    precision,
                    usability,
                    municipality_consistent,
                    geographic_classification,
                    distance_meters,
                    rule_version,
                    diagnostics,
                    created_at,
                    updated_at
                )
                SELECT
                    assessed.position_id,
                    assessed.collection_item_id,
                    assessed.source_observation_id,
                    :release_id,
                    'SIRENE_GEOLOCATION',
                    assessed.source_point::geography,
                    assessed.source_crs,
                    assessed.quality_code,
                    CASE
                        WHEN assessed.quality_code IN ('11', '21') THEN 'ADDRESS'
                        WHEN assessed.quality_code IN ('12', '22') THEN 'STREET'
                        WHEN assessed.quality_code = '33' THEN 'MUNICIPALITY'
                        ELSE 'UNKNOWN'
                    END,
                    CASE
                        WHEN assessed.municipality_consistent AND assessed.quality_usable
                        THEN 'USABLE'
                        WHEN assessed.source_point IS NULL THEN 'MISSING'
                        ELSE 'TO_VERIFY'
                    END,
                    assessed.municipality_consistent,
                    CASE
                        WHEN NOT assessed.municipality_consistent
                          OR NOT assessed.quality_usable
                        THEN 'LOCATION_UNKNOWN'
                        WHEN ST_DWithin(
                            assessed.center,
                            assessed.source_point::geography,
                            assessed.collection_radius_meters
                        ) THEN 'IN_RADIUS'
                        ELSE 'OUTSIDE_RADIUS'
                    END,
                    CASE
                        WHEN assessed.municipality_consistent AND assessed.quality_usable
                        THEN ST_Distance(
                            assessed.center,
                            assessed.source_point::geography
                        )
                        ELSE NULL
                    END,
                    CAST(:rule_version AS text),
                    jsonb_strip_nulls(
                        jsonb_build_object(
                            'code', CASE
                                WHEN assessed.source_point IS NULL
                                THEN 'FILE_COORDINATES_MISSING_OR_INVALID'
                                WHEN assessed.source_municipality_code
                                     IS DISTINCT FROM assessed.expected_municipality_code
                                THEN 'FILE_MUNICIPALITY_MISMATCH'
                                WHEN NOT assessed.municipality_consistent
                                THEN 'FILE_COORDINATES_OUTSIDE_MUNICIPALITY_MARGIN'
                                WHEN assessed.quality_code = '33'
                                THEN 'FILE_QUALITY_REQUIRES_VERIFICATION'
                                WHEN NOT assessed.quality_usable
                                THEN 'FILE_QUALITY_UNKNOWN'
                                ELSE 'FILE_COORDINATES_USABLE'
                            END,
                            'quality_code', assessed.quality_code,
                            'source_municipality_code', assessed.source_municipality_code,
                            'expected_municipality_code', assessed.expected_municipality_code,
                            'selection_margin_meters', assessed.selection_margin_meters,
                            'rule_version', CAST(:rule_version AS text)
                        )
                    ),
                    :now,
                    :now
                FROM assessed
                ON CONFLICT (collection_item_id, origin) DO NOTHING
                """
            ),
            parameters,
        )

    @staticmethod
    def _validate_staged_positions(
        connection: Connection,
        parameters: dict[str, object],
        expected_count: int,
    ) -> None:
        evidence = (
            connection.execute(
                text(
                    f"""
                    SELECT
                        count(position.id) AS position_count,
                        count(*) FILTER (
                            WHERE observation.content_fingerprint
                                      IS DISTINCT FROM input.content_fingerprint
                               OR position.dataset_release_id
                                      IS DISTINCT FROM CAST(:release_id AS uuid)
                               OR position.rule_version
                                      IS DISTINCT FROM CAST(:rule_version AS text)
                        ) AS mismatch_count
                    FROM {_INPUT_RECORDSET}
                    LEFT JOIN candidate_position AS position
                      ON position.collection_item_id = input.collection_item_id
                     AND position.origin = 'SIRENE_GEOLOCATION'
                    LEFT JOIN source_observation AS observation
                      ON observation.id = position.source_observation_id
                    """
                ),
                parameters,
            )
            .mappings()
            .one()
        )
        if evidence["position_count"] != expected_count or evidence["mismatch_count"] != 0:
            raise SireneGeolocationImportError(
                "staged Sirene geolocation positions do not match their input"
            )
