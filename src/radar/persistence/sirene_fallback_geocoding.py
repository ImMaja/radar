"""PostgreSQL checkpoints and PostGIS assessment for Sirene fallback geocoding."""

import json
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.prospects.fallback_geocoding import (
    GEOPLATFORM_ADAPTER_VERSION,
    GEOPLATFORM_DATA_SOURCE_CODE,
    GEOPLATFORM_POSITION_RULE_VERSION,
    GEOPLATFORM_SCHEMA_VERSION,
    SireneFallbackGeocodingError,
    SireneFallbackGeocodingRun,
    SireneFallbackGeocodingSummary,
    SireneFallbackGeocodingTarget,
    StagedSireneFallbackGeocoding,
)


class SqlAlchemySireneFallbackGeocodingRepository:
    """Persist each provider outcome before marking the fallback source complete."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def prepare_run(
        self,
        reservation: ReservedCollection,
        now: datetime,
    ) -> SireneFallbackGeocodingRun:
        """Create or reload the unique fallback source run for this cycle."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                self._require_prerequisites(connection, reservation.cycle_id)
                existing = (
                    connection.execute(
                        text(
                            """
                            SELECT id, status
                            FROM collection_source_run
                            WHERE collection_cycle_id = :cycle_id
                              AND source = 'GEOPLATFORM_GEOCODER'
                            FOR UPDATE
                            """
                        ),
                        {"cycle_id": reservation.cycle_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    return self._run_from_row(existing)

                run_id = uuid4()
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
                            'GEOPLATFORM_GEOCODER',
                            NULL,
                            NULL,
                            :now,
                            'RUNNING',
                            '{}'::jsonb,
                            '{"concurrency": 1, "maximum_requests_per_second": 20}'::jsonb,
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
                        "id": run_id,
                        "cycle_id": reservation.cycle_id,
                        "contract_version": GEOPLATFORM_ADAPTER_VERSION,
                        "now": now,
                    },
                )
                return SireneFallbackGeocodingRun(id=run_id, status="RUNNING")
        except SireneFallbackGeocodingError:
            raise
        except SQLAlchemyError as error:
            raise SireneFallbackGeocodingError(
                "cannot prepare the fallback geocoding source run",
                transient=False,
            ) from error

    def pending_targets(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
    ) -> tuple[SireneFallbackGeocodingTarget, ...]:
        """Return current unresolved addresses with no persisted geocoder outcome."""

        try:
            with self._engine.connect() as connection:
                self._require_running_run(connection, reservation, run)
                rows = (
                    connection.execute(
                        text(
                            """
                            SELECT
                                item.id AS collection_item_id,
                                item.external_identity_id,
                                observation.payload #>> '{address,street_number}'
                                    AS street_number,
                                observation.payload #>> '{address,repetition_index}'
                                    AS repetition_index,
                                observation.payload #>> '{address,street_type}'
                                    AS street_type,
                                observation.payload #>> '{address,street_label}'
                                    AS street_label,
                                observation.payload #>> '{address,postcode}' AS postcode,
                                observation.payload #>> '{address,municipality_label}'
                                    AS municipality_label,
                                observation.payload #>> '{address,municipality_code}'
                                    AS municipality_code
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
                            JOIN source_observation AS observation
                              ON observation.id = item.source_observation_id
                             AND observation.data_source_code = 'SIRENE_API'
                            LEFT JOIN candidate_position AS geocoded
                              ON geocoded.collection_item_id = item.id
                             AND geocoded.origin = 'GEOPLATFORM_GEOCODER'
                            WHERE item.collection_cycle_id = :cycle_id
                              AND item.normalization_result = 'VALID'
                              AND item.reason ->> 'code' = 'POSITION_GEOCODING_REQUIRED'
                              AND geocoded.id IS NULL
                            ORDER BY item.identifier_fingerprint
                            """
                        ),
                        {"cycle_id": reservation.cycle_id},
                    )
                    .mappings()
                    .all()
                )
        except SireneFallbackGeocodingError:
            raise
        except SQLAlchemyError as error:
            raise SireneFallbackGeocodingError(
                "cannot load fallback geocoding targets",
                transient=False,
            ) from error

        targets = tuple(self._target_from_row(row) for row in rows)
        item_ids = [target.collection_item_id for target in targets]
        if len(item_ids) != len(set(item_ids)):
            raise SireneFallbackGeocodingError(
                "fallback geocoding targets contain duplicate collection items",
                transient=False,
            )
        return targets

    def stage_outcome(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
        outcome: StagedSireneFallbackGeocoding,
        now: datetime,
    ) -> None:
        """Persist one provider response and its independent geographic assessment."""

        parameters: dict[str, object] = {
            "observation_id": uuid4(),
            "position_id": uuid4(),
            "cycle_id": reservation.cycle_id,
            "collection_item_id": outcome.target.collection_item_id,
            "external_identity_id": outcome.target.external_identity_id,
            "expected_municipality_code": outcome.target.expected_municipality_code,
            "source_run_id": run.id,
            "data_source_code": GEOPLATFORM_DATA_SOURCE_CODE,
            "adapter_version": GEOPLATFORM_ADAPTER_VERSION,
            "schema_version": GEOPLATFORM_SCHEMA_VERSION,
            "rule_version": GEOPLATFORM_POSITION_RULE_VERSION,
            "content_fingerprint": outcome.content_fingerprint,
            "payload": json.dumps(outcome.payload, ensure_ascii=False, separators=(",", ":")),
            "outcome": outcome.outcome,
            "longitude": outcome.longitude,
            "latitude": outcome.latitude,
            "municipality_code": outcome.municipality_code,
            "result_type": outcome.result_type,
            "score": outcome.score,
            "provider_name": outcome.provider_name,
            "provider_url": outcome.provider_url,
            "now": now,
        }
        try:
            with self._engine.begin() as connection:
                self._require_running_run(connection, reservation, run)
                self._validate_target(connection, parameters)
                self._upsert_observation(connection, parameters)
                inserted = self._insert_position(connection, parameters)
                self._validate_position(connection, parameters)
                if inserted:
                    connection.execute(
                        text(
                            """
                            UPDATE collection_source_run
                            SET request_count = request_count + 1, updated_at = :now
                            WHERE id = :source_run_id
                              AND collection_cycle_id = :cycle_id
                              AND status = 'RUNNING'
                            """
                        ),
                        parameters,
                    )
        except SireneFallbackGeocodingError:
            raise
        except SQLAlchemyError as error:
            raise SireneFallbackGeocodingError(
                "cannot stage a fallback geocoding outcome",
                transient=False,
            ) from error

    def complete_run(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
        now: datetime,
    ) -> SireneFallbackGeocodingSummary:
        """Reconcile every requested address before publishing source success."""

        try:
            with self._engine.begin() as connection:
                self._require_running_run(connection, reservation, run)
                row = self._summary_row(connection, reservation.cycle_id)
                summary = self._summary_from_row(row)
                summary.validate()
                position_count = cast(int, row["position_count"])
                if position_count != summary.requested_count:
                    raise SireneFallbackGeocodingError(
                        "fallback geocoding has unresolved durable targets",
                        transient=False,
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
                        "source_run_id": run.id,
                        "cycle_id": reservation.cycle_id,
                        "counters": json.dumps(
                            {
                                "requested_count": summary.requested_count,
                                "matched_count": summary.matched_count,
                                "usable_count": summary.usable_count,
                                "to_verify_count": summary.to_verify_count,
                                "missing_count": summary.missing_count,
                            }
                        ),
                        "now": now,
                    },
                )
                return summary
        except SireneFallbackGeocodingError:
            raise
        except SQLAlchemyError as error:
            raise SireneFallbackGeocodingError(
                "cannot complete the fallback geocoding source run",
                transient=False,
            ) from error

    def completed_summary(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
    ) -> SireneFallbackGeocodingSummary:
        """Reload counters without repeating provider requests."""

        try:
            with self._engine.connect() as connection:
                self._require_active_attempt(connection, reservation)
                counters = connection.execute(
                    text(
                        """
                        SELECT counters
                        FROM collection_source_run
                        WHERE id = :source_run_id
                          AND collection_cycle_id = :cycle_id
                          AND source = 'GEOPLATFORM_GEOCODER'
                          AND status = 'SUCCEEDED'
                        """
                    ),
                    {"source_run_id": run.id, "cycle_id": reservation.cycle_id},
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise SireneFallbackGeocodingError(
                "cannot reload completed fallback geocoding counters",
                transient=False,
            ) from error
        if not isinstance(counters, dict):
            raise SireneFallbackGeocodingError(
                "completed fallback geocoding counters are unavailable",
                transient=False,
            )
        summary = SireneFallbackGeocodingSummary(
            requested_count=self._counter(counters, "requested_count"),
            matched_count=self._counter(counters, "matched_count"),
            usable_count=self._counter(counters, "usable_count"),
            to_verify_count=self._counter(counters, "to_verify_count"),
            missing_count=self._counter(counters, "missing_count"),
        )
        summary.validate()
        return summary

    def record_failure(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
        *,
        code: str,
        final: bool,
        now: datetime,
    ) -> None:
        """Keep completed items and mark whether the same source run may resume."""

        try:
            with self._engine.begin() as connection:
                self._require_running_run(connection, reservation, run)
                connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET
                            status = CASE WHEN :final THEN 'FAILED' ELSE 'RUNNING' END,
                            finished_at = CASE WHEN :final THEN :now ELSE NULL END,
                            error_count = error_count + 1,
                            metadata = metadata || jsonb_build_object(
                                'last_failure', jsonb_build_object(
                                    'code', CAST(:code AS text),
                                    'final', CAST(:final AS boolean)
                                )
                            ),
                            updated_at = :now
                        WHERE id = :source_run_id
                          AND collection_cycle_id = :cycle_id
                          AND status = 'RUNNING'
                        """
                    ),
                    {
                        "source_run_id": run.id,
                        "cycle_id": reservation.cycle_id,
                        "code": code,
                        "final": final,
                        "now": now,
                    },
                )
        except SireneFallbackGeocodingError:
            raise
        except SQLAlchemyError as error:
            raise SireneFallbackGeocodingError(
                "cannot record the fallback geocoding failure",
                transient=False,
            ) from error

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
                JOIN collection_attempt AS attempt
                  ON attempt.collection_job_id = job.id
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
            raise SireneFallbackGeocodingError(
                "fallback geocoding requires the active collection attempt",
                transient=False,
            )

    def _require_running_run(
        self,
        connection: Connection,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
    ) -> None:
        self._require_active_attempt(connection, reservation)
        running = connection.execute(
            text(
                """
                SELECT id
                FROM collection_source_run
                WHERE id = :source_run_id
                  AND collection_cycle_id = :cycle_id
                  AND source = 'GEOPLATFORM_GEOCODER'
                  AND status = 'RUNNING'
                """
            ),
            {"source_run_id": run.id, "cycle_id": reservation.cycle_id},
        ).scalar_one_or_none()
        if running is None:
            raise SireneFallbackGeocodingError(
                "fallback geocoding source run is not active for this cycle",
                transient=False,
            )

    @staticmethod
    def _require_prerequisites(connection: Connection, cycle_id: UUID) -> None:
        evidence = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) FILTER (
                            WHERE source = 'SIRENE_API' AND status = 'SUCCEEDED'
                        ) AS api_count,
                        count(*) FILTER (
                            WHERE source = 'SIRENE_GEOLOCATION' AND status = 'SUCCEEDED'
                        ) AS file_count
                    FROM collection_source_run
                    WHERE collection_cycle_id = :cycle_id
                      AND source IN ('SIRENE_API', 'SIRENE_GEOLOCATION')
                    """
                ),
                {"cycle_id": cycle_id},
            )
            .mappings()
            .one()
        )
        if evidence["api_count"] != 1 or evidence["file_count"] != 1:
            raise SireneFallbackGeocodingError(
                "fallback geocoding requires reconciled API and file sources",
                transient=False,
            )

    @staticmethod
    def _validate_target(connection: Connection, parameters: dict[str, object]) -> None:
        target = connection.execute(
            text(
                """
                SELECT item.id
                FROM collection_item AS item
                JOIN collection_batch AS batch
                  ON batch.id = item.collection_batch_id
                 AND batch.last_collection_attempt_id = item.collection_attempt_id
                 AND batch.state = 'SUCCEEDED'
                JOIN collection_source_run AS source
                  ON source.id = batch.source_run_id
                 AND source.source = 'SIRENE_API'
                 AND source.status = 'SUCCEEDED'
                WHERE item.id = :collection_item_id
                  AND item.collection_cycle_id = :cycle_id
                  AND item.external_identity_id = :external_identity_id
                  AND item.normalization_result = 'VALID'
                  AND item.reason ->> 'code' = 'POSITION_GEOCODING_REQUIRED'
                """
            ),
            parameters,
        ).scalar_one_or_none()
        if target is None:
            raise SireneFallbackGeocodingError(
                "fallback geocoding outcome does not match a current unresolved target",
                transient=False,
            )

    @staticmethod
    def _upsert_observation(connection: Connection, parameters: dict[str, object]) -> None:
        connection.execute(
            text(
                """
                INSERT INTO source_observation (
                    id,
                    data_source_code,
                    external_identity_id,
                    collection_cycle_id,
                    retrieved_at,
                    adapter_version,
                    schema_version,
                    content_fingerprint,
                    payload,
                    source_reference,
                    validation_status
                ) VALUES (
                    :observation_id,
                    :data_source_code,
                    :external_identity_id,
                    :cycle_id,
                    :now,
                    :adapter_version,
                    :schema_version,
                    :content_fingerprint,
                    CAST(:payload AS jsonb),
                    :provider_url,
                    'VALID'
                )
                ON CONFLICT (data_source_code, external_identity_id, content_fingerprint)
                DO NOTHING
                """
            ),
            parameters,
        )

    @staticmethod
    def _insert_position(connection: Connection, parameters: dict[str, object]) -> bool:
        inserted = connection.execute(
            text(
                """
                WITH context AS (
                    SELECT
                        item.id AS collection_item_id,
                        observation.id AS source_observation_id,
                        cycle.center,
                        cycle.collection_radius_meters,
                        commune.selection_margin_meters,
                        boundary.boundary,
                        CASE
                            WHEN :outcome = 'MATCHED'
                             AND :longitude BETWEEN -180 AND 180
                             AND :latitude BETWEEN -90 AND 90
                            THEN ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)
                            ELSE NULL
                        END AS source_point
                    FROM collection_item AS item
                    JOIN source_observation AS observation
                      ON observation.data_source_code = :data_source_code
                     AND observation.external_identity_id = :external_identity_id
                     AND observation.content_fingerprint = :content_fingerprint
                    JOIN collection_cycle AS cycle ON cycle.id = :cycle_id
                    JOIN collection_cycle_commune AS commune
                      ON commune.collection_cycle_id = cycle.id
                     AND commune.municipality_code
                            = CAST(:expected_municipality_code AS text)
                    JOIN commune_boundary AS boundary
                      ON boundary.dataset_release_id = commune.dataset_release_id
                     AND boundary.municipality_code = commune.municipality_code
                    WHERE item.id = :collection_item_id
                ),
                assessed AS (
                    SELECT
                        context.*,
                        COALESCE(
                            :outcome = 'MATCHED'
                            AND CAST(:municipality_code AS text)
                                = CAST(:expected_municipality_code AS text)
                            AND context.source_point IS NOT NULL
                            AND ST_DWithin(
                                context.boundary::geography,
                                context.source_point::geography,
                                context.selection_margin_meters
                            ),
                            FALSE
                        ) AS municipality_consistent,
                        COALESCE(
                            CAST(:result_type AS text) IN ('housenumber', 'street'),
                            FALSE
                        )
                            AS precise_enough
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
                    :position_id,
                    assessed.collection_item_id,
                    assessed.source_observation_id,
                    NULL,
                    'GEOPLATFORM_GEOCODER',
                    assessed.source_point::geography,
                    CASE WHEN assessed.source_point IS NOT NULL THEN 'EPSG:4326' ELSE NULL END,
                    CAST(:result_type AS text),
                    CASE
                        WHEN CAST(:result_type AS text) = 'housenumber' THEN 'ADDRESS'
                        WHEN CAST(:result_type AS text) = 'street' THEN 'STREET'
                        WHEN CAST(:result_type AS text) IN ('municipality', 'locality')
                        THEN 'MUNICIPALITY'
                        ELSE 'UNKNOWN'
                    END,
                    CASE
                        WHEN :outcome <> 'MATCHED' THEN 'MISSING'
                        WHEN assessed.municipality_consistent AND assessed.precise_enough
                        THEN 'USABLE'
                        ELSE 'TO_VERIFY'
                    END,
                    assessed.municipality_consistent,
                    CASE
                        WHEN :outcome = 'OUTSIDE_METROPOLITAN_FRANCE'
                        THEN 'OUTSIDE_METROPOLITAN_FRANCE'
                        WHEN NOT assessed.municipality_consistent
                          OR NOT assessed.precise_enough
                        THEN 'LOCATION_UNKNOWN'
                        WHEN ST_DWithin(
                            assessed.center,
                            assessed.source_point::geography,
                            assessed.collection_radius_meters
                        ) THEN 'IN_RADIUS'
                        ELSE 'OUTSIDE_RADIUS'
                    END,
                    CASE
                        WHEN assessed.municipality_consistent AND assessed.precise_enough
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
                                WHEN :outcome = 'NOT_FOUND'
                                THEN 'GEOCODER_ADDRESS_NOT_FOUND'
                                WHEN :outcome = 'OUTSIDE_METROPOLITAN_FRANCE'
                                THEN 'GEOCODER_OUTSIDE_METROPOLITAN_FRANCE'
                                WHEN CAST(:municipality_code AS text)
                                     IS DISTINCT FROM
                                         CAST(:expected_municipality_code AS text)
                                THEN 'GEOCODER_MUNICIPALITY_MISMATCH'
                                WHEN NOT assessed.municipality_consistent
                                THEN 'GEOCODER_OUTSIDE_MUNICIPALITY_MARGIN'
                                WHEN NOT assessed.precise_enough
                                THEN 'GEOCODER_RESULT_TOO_IMPRECISE'
                                ELSE 'GEOCODER_ADDRESS_USABLE'
                            END,
                            'result_type', CAST(:result_type AS text),
                            'score', CAST(:score AS double precision),
                            'source_municipality_code', CAST(:municipality_code AS text),
                            'expected_municipality_code',
                                CAST(:expected_municipality_code AS text),
                            'provider_name', CAST(:provider_name AS text),
                            'selection_margin_meters', assessed.selection_margin_meters,
                            'rule_version', CAST(:rule_version AS text)
                        )
                    ),
                    :now,
                    :now
                FROM assessed
                ON CONFLICT (collection_item_id, origin) DO NOTHING
                RETURNING id
                """
            ),
            parameters,
        ).scalar_one_or_none()
        return inserted is not None

    @staticmethod
    def _validate_position(connection: Connection, parameters: dict[str, object]) -> None:
        position = connection.execute(
            text(
                """
                SELECT position.id
                FROM candidate_position AS position
                JOIN source_observation AS observation
                  ON observation.id = position.source_observation_id
                WHERE position.collection_item_id = :collection_item_id
                  AND position.origin = 'GEOPLATFORM_GEOCODER'
                  AND observation.data_source_code = :data_source_code
                  AND observation.external_identity_id = :external_identity_id
                  AND observation.content_fingerprint = :content_fingerprint
                  AND position.rule_version = :rule_version
                """
            ),
            parameters,
        ).scalar_one_or_none()
        if position is None:
            raise SireneFallbackGeocodingError(
                "persisted fallback geocoding evidence does not match its outcome",
                transient=False,
            )

    @staticmethod
    def _summary_row(connection: Connection, cycle_id: UUID) -> RowMapping:
        return (
            connection.execute(
                text(
                    """
                    SELECT
                        count(item.id) AS requested_count,
                        count(position.id) AS position_count,
                        count(position.id) FILTER (
                            WHERE observation.payload ->> 'outcome' = 'MATCHED'
                        ) AS matched_count,
                        count(position.id) FILTER (
                            WHERE position.usability = 'USABLE'
                        ) AS usable_count,
                        count(position.id) FILTER (
                            WHERE position.usability = 'TO_VERIFY'
                        ) AS to_verify_count,
                        count(position.id) FILTER (
                            WHERE position.usability = 'MISSING'
                        ) AS missing_count
                    FROM collection_item AS item
                    JOIN collection_batch AS batch
                      ON batch.id = item.collection_batch_id
                     AND batch.last_collection_attempt_id = item.collection_attempt_id
                     AND batch.state = 'SUCCEEDED'
                    JOIN collection_source_run AS api_source
                      ON api_source.id = batch.source_run_id
                     AND api_source.source = 'SIRENE_API'
                     AND api_source.status = 'SUCCEEDED'
                    LEFT JOIN candidate_position AS position
                      ON position.collection_item_id = item.id
                     AND position.origin = 'GEOPLATFORM_GEOCODER'
                    LEFT JOIN source_observation AS observation
                      ON observation.id = position.source_observation_id
                    WHERE item.collection_cycle_id = :cycle_id
                      AND item.normalization_result = 'VALID'
                      AND item.reason ->> 'code' = 'POSITION_GEOCODING_REQUIRED'
                    """
                ),
                {"cycle_id": cycle_id},
            )
            .mappings()
            .one()
        )

    @staticmethod
    def _target_from_row(row: RowMapping) -> SireneFallbackGeocodingTarget:
        collection_item_id = row["collection_item_id"]
        external_identity_id = row["external_identity_id"]
        municipality_code = row["municipality_code"]
        if (
            not isinstance(collection_item_id, UUID)
            or not isinstance(external_identity_id, UUID)
            or not isinstance(municipality_code, str)
        ):
            raise SireneFallbackGeocodingError(
                "fallback geocoding target has incomplete identity or municipality data",
                transient=False,
            )
        parts = [
            row["street_number"],
            row["repetition_index"],
            row["street_type"],
            row["street_label"],
            row["postcode"],
            row["municipality_label"],
        ]
        address = " ".join(
            " ".join(part.split()) for part in parts if isinstance(part, str) and part.strip()
        )
        if not address or len(address) > 500:
            raise SireneFallbackGeocodingError(
                "fallback geocoding target has no bounded public address",
                transient=False,
            )
        return SireneFallbackGeocodingTarget(
            collection_item_id=collection_item_id,
            external_identity_id=external_identity_id,
            input_address=address,
            expected_municipality_code=municipality_code,
        )

    @staticmethod
    def _run_from_row(row: RowMapping) -> SireneFallbackGeocodingRun:
        run_id = row["id"]
        status = row["status"]
        if not isinstance(run_id, UUID) or not isinstance(status, str):
            raise SireneFallbackGeocodingError(
                "persisted fallback geocoding run is invalid",
                transient=False,
            )
        return SireneFallbackGeocodingRun(id=run_id, status=status)

    @staticmethod
    def _summary_from_row(row: RowMapping) -> SireneFallbackGeocodingSummary:
        return SireneFallbackGeocodingSummary(
            requested_count=cast(int, row["requested_count"]),
            matched_count=cast(int, row["matched_count"]),
            usable_count=cast(int, row["usable_count"]),
            to_verify_count=cast(int, row["to_verify_count"]),
            missing_count=cast(int, row["missing_count"]),
        )

    @staticmethod
    def _counter(counters: dict[object, object], key: str) -> int:
        value = counters.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SireneFallbackGeocodingError(
                "completed fallback geocoding counters are invalid",
                transient=False,
            )
        return value
