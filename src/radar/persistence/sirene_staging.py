"""Bulk PostgreSQL staging for Sirene candidates awaiting final geolocation."""

import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.prospects.planning import SireneMunicipalityBatch
from radar.prospects.staging import (
    SIRENE_ADAPTER_VERSION,
    SIRENE_CANDIDATE_SCHEMA_VERSION,
    SIRENE_DATA_SOURCE_CODE,
    SIRENE_IDENTITY_AUTHORITY,
    SIRENE_IDENTITY_NAMESPACE,
    SireneCandidateStagingError,
    StagedSireneCandidate,
)

POSITION_RULE_VERSION = "sirene-api-position-v1"

_INPUT_RECORDSET = """
jsonb_to_recordset(CAST(:candidates AS jsonb)) AS input(
    identity_id uuid,
    observation_id uuid,
    item_id uuid,
    position_id uuid,
    item_rank integer,
    siret text,
    identifier_fingerprint text,
    content_fingerprint text,
    payload jsonb,
    municipality_code text,
    lambert_x double precision,
    lambert_y double precision,
    coordinate_crs text
)
"""


class SqlAlchemySireneCandidateStagingRepository:
    """Persist revisions once and candidate occurrences with bounded SQL calls."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def stage_page(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        page_number: int,
        candidates: tuple[StagedSireneCandidate, ...],
        now: datetime,
    ) -> None:
        """Stage up to one provider page atomically before page acknowledgement."""

        if not candidates:
            self._require_active_batch(reservation, batch.id)
            return
        parameters: dict[str, object] = {
            "candidates": self._input_payload(candidates),
            "cycle_id": reservation.cycle_id,
            "batch_id": batch.id,
            "attempt_id": reservation.attempt_id,
            "page_number": page_number,
            "data_source_code": SIRENE_DATA_SOURCE_CODE,
            "authority": SIRENE_IDENTITY_AUTHORITY,
            "namespace": SIRENE_IDENTITY_NAMESPACE,
            "adapter_version": SIRENE_ADAPTER_VERSION,
            "schema_version": SIRENE_CANDIDATE_SCHEMA_VERSION,
            "position_rule_version": POSITION_RULE_VERSION,
            "now": now,
        }
        try:
            with self._engine.begin() as connection:
                self._require_running_batch(connection, reservation, batch.id)
                self._upsert_identities(connection, parameters)
                self._validate_identities(connection, parameters)
                self._upsert_observations(connection, parameters)
                self._insert_collection_items(connection, parameters)
                self._insert_api_positions(connection, parameters)
                self._validate_collection_items(connection, parameters, len(candidates))
        except SireneCandidateStagingError:
            raise
        except SQLAlchemyError as error:
            raise SireneCandidateStagingError(
                "cannot stage the normalized Sirene candidate page"
            ) from error

    def _require_active_batch(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
    ) -> None:
        try:
            with self._engine.connect() as connection:
                self._require_running_batch(connection, reservation, batch_id)
        except SireneCandidateStagingError:
            raise
        except SQLAlchemyError as error:
            raise SireneCandidateStagingError(
                "cannot validate the empty Sirene candidate page"
            ) from error

    @staticmethod
    def _input_payload(candidates: tuple[StagedSireneCandidate, ...]) -> str:
        rows = [
            {
                "identity_id": str(uuid4()),
                "observation_id": str(uuid4()),
                "item_id": str(uuid4()),
                "position_id": str(uuid4()),
                "item_rank": candidate.item_rank,
                "siret": candidate.siret,
                "identifier_fingerprint": candidate.identifier_fingerprint,
                "content_fingerprint": candidate.content_fingerprint,
                "payload": candidate.payload,
                "municipality_code": candidate.municipality_code,
                "lambert_x": candidate.lambert_x,
                "lambert_y": candidate.lambert_y,
                "coordinate_crs": candidate.coordinate_crs,
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
                  AND source.source = 'SIRENE_API'
                  AND source.status = 'RUNNING'
                  AND job.id = :job_id
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
            raise SireneCandidateStagingError(
                "the Sirene candidate page is not owned by the active attempt"
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
                    input.siret,
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
                WHERE identity.canonical_value IS DISTINCT FROM input.siret
                   OR identity.restricted_at IS NOT NULL
                """
            ),
            parameters,
        ).scalar_one()
        if invalid_count:
            raise SireneCandidateStagingError(
                "a Sirene identity is restricted or has an inconsistent fingerprint"
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
                    adapter_version,
                    schema_version,
                    content_fingerprint,
                    payload,
                    validation_status
                )
                SELECT
                    input.observation_id,
                    :data_source_code,
                    identity.id,
                    :cycle_id,
                    :batch_id,
                    :now,
                    :adapter_version,
                    :schema_version,
                    input.content_fingerprint,
                    input.payload,
                    'VALID'
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
                        cycle.collection_radius_meters,
                        commune.selection_margin_meters,
                        boundary.boundary,
                        CASE
                            WHEN input.coordinate_crs = 'EPSG:2154'
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
                        END AS api_point
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
                    JOIN collection_cycle_commune AS commune
                      ON commune.collection_cycle_id = cycle.id
                     AND commune.collection_batch_id = :batch_id
                     AND commune.municipality_code = input.municipality_code
                    JOIN commune_boundary AS boundary
                      ON boundary.dataset_release_id = commune.dataset_release_id
                     AND boundary.municipality_code = commune.municipality_code
                ),
                classified AS (
                    SELECT
                        context.*,
                        CASE
                            WHEN context.api_point IS NULL THEN FALSE
                            WHEN ST_X(context.api_point) NOT BETWEEN -180 AND 180
                              OR ST_Y(context.api_point) NOT BETWEEN -90 AND 90 THEN FALSE
                            ELSE ST_DWithin(
                                context.boundary::geography,
                                context.api_point::geography,
                                context.selection_margin_meters
                            )
                        END AS municipality_consistent
                    FROM candidate_context AS context
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
                    reason,
                    created_at,
                    updated_at
                )
                SELECT
                    classified.item_id,
                    :cycle_id,
                    :batch_id,
                    :attempt_id,
                    :page_number,
                    classified.item_rank,
                    :authority,
                    :namespace,
                    classified.siret,
                    classified.identifier_fingerprint,
                    classified.external_identity_id,
                    classified.source_observation_id,
                    'VALID',
                    CASE
                        WHEN NOT classified.municipality_consistent THEN 'LOCATION_UNKNOWN'
                        WHEN ST_DWithin(
                            classified.center,
                            classified.api_point::geography,
                            classified.collection_radius_meters
                        ) THEN 'IN_RADIUS'
                        ELSE 'OUTSIDE_RADIUS'
                    END,
                    CASE
                        WHEN classified.municipality_consistent THEN ST_Distance(
                            classified.center,
                            classified.api_point::geography
                        )
                        ELSE NULL
                    END,
                    CASE
                        WHEN classified.lambert_x IS NULL OR classified.lambert_y IS NULL
                        THEN jsonb_build_object(
                            'code', 'API_COORDINATES_MISSING',
                            'position_source', 'SIRENE_API',
                            'rule_version', CAST(:position_rule_version AS text)
                        )
                        WHEN classified.coordinate_crs <> 'EPSG:2154'
                        THEN jsonb_build_object(
                            'code', 'API_COORDINATE_CRS_UNSUPPORTED',
                            'position_source', 'SIRENE_API',
                            'rule_version', CAST(:position_rule_version AS text)
                        )
                        WHEN classified.api_point IS NULL
                        THEN jsonb_build_object(
                            'code', 'API_COORDINATES_OUTSIDE_LAMBERT93_BOUNDS',
                            'position_source', 'SIRENE_API',
                            'rule_version', CAST(:position_rule_version AS text)
                        )
                        WHEN NOT classified.municipality_consistent
                        THEN jsonb_build_object(
                            'code', 'API_COORDINATES_OUTSIDE_MUNICIPALITY_MARGIN',
                            'position_source', 'SIRENE_API',
                            'rule_version', CAST(:position_rule_version AS text),
                            'selection_margin_meters', classified.selection_margin_meters
                        )
                        ELSE jsonb_build_object(
                            'code', 'API_COORDINATES_USABLE',
                            'position_source', 'SIRENE_API',
                            'precision', 'UNKNOWN',
                            'usability', 'USABLE',
                            'rule_version', CAST(:position_rule_version AS text),
                            'selection_margin_meters', classified.selection_margin_meters
                        )
                    END,
                    :now,
                    :now
                FROM classified
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
    def _insert_api_positions(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                f"""
                WITH input_rows AS (
                    SELECT * FROM {_INPUT_RECORDSET}
                ),
                positioned AS (
                    SELECT
                        input.*,
                        item.id AS collection_item_id,
                        item.source_observation_id,
                        item.geographic_classification,
                        item.distance_meters,
                        item.reason,
                        CASE
                            WHEN input.coordinate_crs = 'EPSG:2154'
                             AND input.lambert_x BETWEEN -1000000 AND 2000000
                             AND input.lambert_y BETWEEN 5000000 AND 8000000
                            THEN ST_Transform(
                                ST_SetSRID(
                                    ST_MakePoint(input.lambert_x, input.lambert_y),
                                    2154
                                ),
                                4326
                            )::geography
                            ELSE NULL
                        END AS api_point
                    FROM input_rows AS input
                    JOIN collection_item AS item
                      ON item.collection_attempt_id = :attempt_id
                     AND item.collection_batch_id = :batch_id
                     AND item.page_number = :page_number
                     AND item.item_rank = input.item_rank
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
                    positioned.position_id,
                    positioned.collection_item_id,
                    positioned.source_observation_id,
                    NULL,
                    'SIRENE_API',
                    positioned.api_point,
                    positioned.coordinate_crs,
                    NULL,
                    'UNKNOWN',
                    CASE
                        WHEN positioned.reason ->> 'code' = 'API_COORDINATES_USABLE'
                        THEN 'USABLE'
                        WHEN positioned.reason ->> 'code'
                             = 'API_COORDINATES_OUTSIDE_MUNICIPALITY_MARGIN'
                        THEN 'TO_VERIFY'
                        ELSE 'MISSING'
                    END,
                    positioned.reason ->> 'code' = 'API_COORDINATES_USABLE',
                    positioned.geographic_classification,
                    positioned.distance_meters,
                    CAST(:position_rule_version AS text),
                    positioned.reason,
                    :now,
                    :now
                FROM positioned
                ON CONFLICT (collection_item_id, origin) DO NOTHING
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
        evidence = (
            connection.execute(
                text(
                    f"""
                    WITH input_rows AS (
                        SELECT * FROM {_INPUT_RECORDSET}
                    )
                    SELECT
                        count(item.id) AS item_count,
                        count(position.id) AS position_count,
                        count(*) FILTER (
                            WHERE item.identifier_fingerprint
                                      IS DISTINCT FROM input.identifier_fingerprint
                               OR observation.content_fingerprint
                                      IS DISTINCT FROM input.content_fingerprint
                               OR identity.canonical_value IS DISTINCT FROM input.siret
                               OR position.source_observation_id
                                      IS DISTINCT FROM observation.id
                               OR position.rule_version
                                      IS DISTINCT FROM CAST(:position_rule_version AS text)
                        ) AS mismatch_count
                    FROM input_rows AS input
                    LEFT JOIN collection_item AS item
                      ON item.collection_attempt_id = :attempt_id
                     AND item.collection_batch_id = :batch_id
                     AND item.page_number = :page_number
                     AND item.item_rank = input.item_rank
                    LEFT JOIN external_identity AS identity
                      ON identity.id = item.external_identity_id
                    LEFT JOIN source_observation AS observation
                      ON observation.id = item.source_observation_id
                    LEFT JOIN candidate_position AS position
                      ON position.collection_item_id = item.id
                     AND position.origin = 'SIRENE_API'
                    """
                ),
                parameters,
            )
            .mappings()
            .one()
        )
        if (
            evidence["item_count"] != expected_count
            or evidence["position_count"] != expected_count
            or evidence["mismatch_count"] != 0
        ):
            raise SireneCandidateStagingError(
                "the staged Sirene page does not match its candidate input"
            )
