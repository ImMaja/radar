"""PostgreSQL staging for normalized DATAtourisme event candidates."""

import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.events.staging import (
    DATATOURISME_ADAPTER_VERSION,
    DATATOURISME_CANDIDATE_SCHEMA_VERSION,
    DATATOURISME_DATA_SOURCE_CODE,
    DATATOURISME_IDENTITY_AUTHORITY,
    DATATOURISME_IDENTITY_NAMESPACE,
    EventCandidateStagingError,
    StagedEventCandidate,
)
from radar.persistence.reference_data import DATASET_CODE
from radar.providers.datatourisme import DatatourismePage

_INPUT_RECORDSET = """
jsonb_to_recordset(CAST(:candidates AS jsonb)) AS input(
    identity_id uuid,
    observation_id uuid,
    item_id uuid,
    item_rank integer,
    external_identifier text,
    identifier_fingerprint text,
    content_fingerprint text,
    source_uri text,
    source_updated_at timestamptz,
    payload jsonb,
    validated_periods jsonb,
    temporal_state text,
    period_rejection_counts jsonb
)
"""


class SqlAlchemyEventCandidateStagingRepository:
    """Persist event identities, revisions and exact geographic decisions by page."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def stage_page(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        page: DatatourismePage,
        candidates: tuple[StagedEventCandidate, ...],
        now: datetime,
    ) -> None:
        """Stage one page atomically before the page lifecycle is acknowledged."""

        if page.number < 1:
            raise ValueError("a DATAtourisme page number must be positive")
        if not candidates:
            self._require_active_batch(reservation, batch_id)
            return
        parameters: dict[str, object] = {
            "candidates": self._input_payload(candidates),
            "cycle_id": reservation.cycle_id,
            "batch_id": batch_id,
            "attempt_id": reservation.attempt_id,
            "page_number": page.number,
            "data_source_code": DATATOURISME_DATA_SOURCE_CODE,
            "authority": DATATOURISME_IDENTITY_AUTHORITY,
            "namespace": DATATOURISME_IDENTITY_NAMESPACE,
            "adapter_version": DATATOURISME_ADAPTER_VERSION,
            "schema_version": DATATOURISME_CANDIDATE_SCHEMA_VERSION,
            "dataset_code": DATASET_CODE,
            "now": now,
        }
        try:
            with self._engine.begin() as connection:
                self._require_running_batch(connection, reservation, batch_id)
                self._require_active_metropolitan_reference(connection, parameters)
                self._upsert_identities(connection, parameters)
                self._validate_identities(connection, parameters)
                self._upsert_observations(connection, parameters)
                self._validate_observations(connection, parameters)
                self._insert_collection_items(connection, parameters)
                self._validate_collection_items(connection, parameters, len(candidates))
        except EventCandidateStagingError:
            raise
        except SQLAlchemyError as error:
            raise EventCandidateStagingError(
                "cannot stage the normalized DATAtourisme candidate page"
            ) from error

    def _require_active_batch(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
    ) -> None:
        try:
            with self._engine.connect() as connection:
                self._require_running_batch(connection, reservation, batch_id)
        except EventCandidateStagingError:
            raise
        except SQLAlchemyError as error:
            raise EventCandidateStagingError(
                "cannot validate the empty DATAtourisme candidate page"
            ) from error

    @staticmethod
    def _input_payload(candidates: tuple[StagedEventCandidate, ...]) -> str:
        rows = [
            {
                "identity_id": str(uuid4()),
                "observation_id": str(uuid4()),
                "item_id": str(uuid4()),
                "item_rank": candidate.item_rank,
                "external_identifier": candidate.external_identifier,
                "identifier_fingerprint": candidate.identifier_fingerprint,
                "content_fingerprint": candidate.content_fingerprint,
                "source_uri": candidate.source_uri,
                "source_updated_at": (
                    candidate.source_updated_at.isoformat()
                    if candidate.source_updated_at is not None
                    else None
                ),
                "payload": candidate.payload,
                "validated_periods": candidate.validated_periods,
                "temporal_state": candidate.temporal_state,
                "period_rejection_counts": candidate.period_rejection_counts,
            }
            for candidate in candidates
        ]
        return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _require_running_batch(
        connection: Connection,
        reservation: ReservedCollection,
        batch_id: UUID,
    ) -> None:
        active = connection.execute(
            text(
                """
                SELECT batch.id
                FROM collection_batch AS batch
                JOIN collection_source_run AS source ON source.id = batch.source_run_id
                JOIN collection_job AS job ON job.cycle_id = batch.collection_cycle_id
                JOIN collection_attempt AS attempt ON attempt.collection_job_id = job.id
                WHERE batch.id = :batch_id
                  AND batch.collection_cycle_id = :cycle_id
                  AND batch.state = 'RUNNING'
                  AND batch.last_collection_attempt_id = :attempt_id
                  AND source.source = 'DATATOURISME_API'
                  AND source.status = 'RUNNING'
                  AND job.id = :job_id
                  AND job.connector = 'DATATOURISME'
                  AND job.state = 'RUNNING'
                  AND attempt.id = :attempt_id
                  AND attempt.finished_at IS NULL
                """
            ),
            {
                "batch_id": batch_id,
                "cycle_id": reservation.cycle_id,
                "job_id": reservation.job_id,
                "attempt_id": reservation.attempt_id,
            },
        ).scalar_one_or_none()
        if active is None:
            raise EventCandidateStagingError(
                "the DATAtourisme candidate page is not owned by the active attempt"
            )

    @staticmethod
    def _require_active_metropolitan_reference(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM dataset_release
                WHERE dataset_code = :dataset_code
                  AND status = 'ACTIVE'
                """
            ),
            parameters,
        ).scalar_one()
        if count != 1:
            raise EventCandidateStagingError(
                "DATAtourisme staging requires one active metropolitan boundary release"
            )

    @staticmethod
    def _upsert_identities(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                f"""
                INSERT INTO external_identity (
                    id,
                    authority,
                    namespace,
                    canonical_value,
                    identifier_fingerprint,
                    fingerprint_algorithm,
                    first_observed_at,
                    last_observed_at
                )
                SELECT
                    input.identity_id,
                    :authority,
                    :namespace,
                    input.external_identifier,
                    input.identifier_fingerprint,
                    'SHA-256',
                    :now,
                    :now
                FROM {_INPUT_RECORDSET}
                ON CONFLICT (authority, namespace, identifier_fingerprint)
                DO UPDATE SET
                    last_observed_at = GREATEST(
                        external_identity.last_observed_at,
                        EXCLUDED.last_observed_at
                    )
                """
            ),
            parameters,
        )

    @staticmethod
    def _validate_identities(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        invalid_count = connection.execute(
            text(
                f"""
                SELECT count(*)
                FROM {_INPUT_RECORDSET}
                JOIN external_identity AS identity
                  ON identity.authority = :authority
                 AND identity.namespace = :namespace
                 AND identity.identifier_fingerprint = input.identifier_fingerprint
                LEFT JOIN opportunity
                  ON opportunity.id = identity.opportunity_id
                WHERE identity.canonical_value IS DISTINCT FROM input.external_identifier
                   OR identity.restricted_at IS NOT NULL
                   OR identity.organization_id IS NOT NULL
                   OR identity.establishment_id IS NOT NULL
                   OR (
                       identity.opportunity_id IS NOT NULL
                       AND opportunity.kind IS DISTINCT FROM 'EVENT'
                   )
                """
            ),
            parameters,
        ).scalar_one()
        if invalid_count:
            raise EventCandidateStagingError(
                "a DATAtourisme identity is restricted or targets another entity"
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
                    collection_batch_id,
                    retrieved_at,
                    source_updated_at,
                    adapter_version,
                    schema_version,
                    content_fingerprint,
                    payload,
                    source_reference,
                    validation_status,
                    normalization_error
                )
                SELECT
                    input.observation_id,
                    :data_source_code,
                    identity.id,
                    :cycle_id,
                    :batch_id,
                    :now,
                    input.source_updated_at,
                    :adapter_version,
                    :schema_version,
                    input.content_fingerprint,
                    input.payload,
                    input.source_uri,
                    CASE
                        WHEN jsonb_array_length(input.validated_periods) = 0
                        THEN 'REJECTED'
                        ELSE 'VALID'
                    END,
                    CASE
                        WHEN jsonb_array_length(input.validated_periods) = 0
                        THEN jsonb_build_object(
                            'code', 'NO_VALID_PERIOD',
                            'period_rejection_counts', input.period_rejection_counts
                        )
                        ELSE NULL
                    END
                FROM {_INPUT_RECORDSET}
                JOIN external_identity AS identity
                  ON identity.authority = :authority
                 AND identity.namespace = :namespace
                 AND identity.identifier_fingerprint = input.identifier_fingerprint
                ON CONFLICT (data_source_code, external_identity_id, content_fingerprint)
                DO NOTHING
                """
            ),
            parameters,
        )

    @staticmethod
    def _validate_observations(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        invalid_count = connection.execute(
            text(
                f"""
                SELECT count(*)
                FROM {_INPUT_RECORDSET}
                JOIN external_identity AS identity
                  ON identity.authority = :authority
                 AND identity.namespace = :namespace
                 AND identity.identifier_fingerprint = input.identifier_fingerprint
                JOIN source_observation AS observation
                  ON observation.data_source_code = :data_source_code
                 AND observation.external_identity_id = identity.id
                 AND observation.content_fingerprint = input.content_fingerprint
                WHERE observation.payload IS DISTINCT FROM input.payload
                """
            ),
            parameters,
        ).scalar_one()
        if invalid_count:
            raise EventCandidateStagingError(
                "a DATAtourisme revision fingerprint identifies different content"
            )

    @staticmethod
    def _insert_collection_items(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                f"""
                WITH input_rows AS (
                    SELECT * FROM {_INPUT_RECORDSET}
                ),
                candidate_context AS (
                    SELECT
                        input.*,
                        identity.id AS external_identity_id,
                        observation.id AS source_observation_id,
                        cycle.center,
                        cycle.collection_radius_meters
                    FROM input_rows AS input
                    JOIN external_identity AS identity
                      ON identity.authority = :authority
                     AND identity.namespace = :namespace
                     AND identity.identifier_fingerprint = input.identifier_fingerprint
                    JOIN source_observation AS observation
                      ON observation.data_source_code = :data_source_code
                     AND observation.external_identity_id = identity.id
                     AND observation.content_fingerprint = input.content_fingerprint
                    JOIN collection_cycle AS cycle ON cycle.id = :cycle_id
                ),
                location_points AS (
                    SELECT
                        context.item_rank,
                        location.ordinality::integer AS location_index,
                        context.center,
                        context.collection_radius_meters,
                        ST_SetSRID(
                            ST_MakePoint(
                                CAST(location.value ->> 'longitude' AS double precision),
                                CAST(location.value ->> 'latitude' AS double precision)
                            ),
                            4326
                        ) AS point
                    FROM candidate_context AS context
                    CROSS JOIN LATERAL jsonb_array_elements(
                        context.payload -> 'locations'
                    ) WITH ORDINALITY AS location(value, ordinality)
                    WHERE jsonb_typeof(location.value -> 'longitude') = 'number'
                      AND jsonb_typeof(location.value -> 'latitude') = 'number'
                      AND CAST(location.value ->> 'longitude' AS double precision)
                            BETWEEN -180 AND 180
                      AND CAST(location.value ->> 'latitude' AS double precision)
                            BETWEEN -90 AND 90
                ),
                classified_locations AS (
                    SELECT
                        point.*,
                        EXISTS (
                            SELECT 1
                            FROM dataset_release AS release
                            JOIN commune_boundary AS boundary
                              ON boundary.dataset_release_id = release.id
                            WHERE release.dataset_code = :dataset_code
                              AND release.status = 'ACTIVE'
                              AND ST_Covers(boundary.boundary, point.point)
                        ) AS is_metropolitan,
                        ST_Distance(point.point::geography, point.center) AS distance_meters
                    FROM location_points AS point
                ),
                location_counts AS (
                    SELECT
                        item_rank,
                        count(*) AS positioned_count,
                        count(*) FILTER (WHERE is_metropolitan) AS metropolitan_count
                    FROM classified_locations
                    GROUP BY item_rank
                ),
                selected_location AS (
                    SELECT DISTINCT ON (item_rank)
                        item_rank,
                        location_index,
                        distance_meters
                    FROM classified_locations
                    WHERE is_metropolitan
                    ORDER BY item_rank, distance_meters, location_index
                ),
                decisions AS (
                    SELECT
                        context.*,
                        COALESCE(counts.positioned_count, 0) AS positioned_count,
                        COALESCE(counts.metropolitan_count, 0) AS metropolitan_count,
                        selected.location_index,
                        selected.distance_meters,
                        CASE
                            WHEN COALESCE(counts.positioned_count, 0) = 0
                            THEN 'LOCATION_UNKNOWN'
                            WHEN COALESCE(counts.metropolitan_count, 0) = 0
                            THEN 'OUTSIDE_METROPOLITAN_FRANCE'
                            WHEN selected.distance_meters <= context.collection_radius_meters
                            THEN 'IN_RADIUS'
                            ELSE 'OUTSIDE_RADIUS'
                        END AS geographic_classification
                    FROM candidate_context AS context
                    LEFT JOIN location_counts AS counts USING (item_rank)
                    LEFT JOIN selected_location AS selected USING (item_rank)
                )
                INSERT INTO collection_item (
                    id,
                    collection_cycle_id,
                    collection_batch_id,
                    collection_attempt_id,
                    page_number,
                    item_rank,
                    authority,
                    namespace,
                    identifier_value,
                    identifier_fingerprint,
                    external_identity_id,
                    source_observation_id,
                    normalization_result,
                    geographic_classification,
                    distance_meters,
                    decision,
                    reason,
                    created_at,
                    updated_at
                )
                SELECT
                    decision.item_id,
                    :cycle_id,
                    :batch_id,
                    :attempt_id,
                    :page_number,
                    decision.item_rank,
                    :authority,
                    :namespace,
                    decision.external_identifier,
                    decision.identifier_fingerprint,
                    decision.external_identity_id,
                    decision.source_observation_id,
                    CASE
                        WHEN jsonb_array_length(decision.validated_periods) = 0
                        THEN 'REJECTED'
                        ELSE 'VALID'
                    END,
                    decision.geographic_classification,
                    decision.distance_meters,
                    CASE
                        WHEN jsonb_array_length(decision.validated_periods) = 0
                          OR decision.geographic_classification = 'LOCATION_UNKNOWN'
                        THEN 'REJECTED'
                        WHEN decision.geographic_classification IN (
                            'OUTSIDE_RADIUS', 'OUTSIDE_METROPOLITAN_FRANCE'
                        )
                        THEN 'COUNTED_ONLY'
                        ELSE NULL
                    END,
                    jsonb_strip_nulls(jsonb_build_object(
                        'code', CASE
                            WHEN jsonb_array_length(decision.validated_periods) = 0
                            THEN 'NO_VALID_PERIOD'
                            WHEN decision.geographic_classification = 'LOCATION_UNKNOWN'
                            THEN 'LOCATION_MISSING'
                            WHEN decision.geographic_classification
                                = 'OUTSIDE_METROPOLITAN_FRANCE'
                            THEN 'OUTSIDE_METROPOLITAN_FRANCE'
                            WHEN decision.geographic_classification = 'OUTSIDE_RADIUS'
                            THEN 'OUTSIDE_RADIUS'
                            WHEN decision.temporal_state = 'PAST'
                            THEN 'PAST_ONLY'
                            ELSE 'READY_FOR_PROJECTION'
                        END,
                        'temporal_state', decision.temporal_state,
                        'validated_periods', decision.validated_periods,
                        'period_rejection_counts', decision.period_rejection_counts,
                        'selected_location_index', decision.location_index
                    )),
                    :now,
                    :now
                FROM decisions AS decision
                ON CONFLICT (
                    collection_attempt_id,
                    collection_batch_id,
                    page_number,
                    item_rank
                ) DO NOTHING
                """
            ),
            parameters,
        )

    @staticmethod
    def _validate_collection_items(
        connection: Connection,
        parameters: dict[str, object],
        expected_count: int,
    ) -> None:
        matched_count = connection.execute(
            text(
                f"""
                SELECT count(*)
                FROM {_INPUT_RECORDSET}
                JOIN collection_item AS item
                  ON item.collection_attempt_id = :attempt_id
                 AND item.collection_batch_id = :batch_id
                 AND item.page_number = :page_number
                 AND item.item_rank = input.item_rank
                 AND item.authority = :authority
                 AND item.namespace = :namespace
                 AND item.identifier_fingerprint = input.identifier_fingerprint
                JOIN source_observation AS observation
                  ON observation.id = item.source_observation_id
                 AND observation.content_fingerprint = input.content_fingerprint
                """
            ),
            parameters,
        ).scalar_one()
        if matched_count != expected_count:
            raise EventCandidateStagingError(
                "the staged DATAtourisme page does not match its candidate revisions"
            )
