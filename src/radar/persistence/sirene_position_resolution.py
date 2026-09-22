"""PostgreSQL resolution of independently assessed Sirene candidate positions."""

from datetime import datetime

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.prospects.position_resolution import (
    SIRENE_POSITION_RESOLUTION_RULE_VERSION,
    SirenePositionResolutionError,
    SirenePositionResolutionSummary,
)


class SqlAlchemySirenePositionResolutionRepository:
    """Apply source priority without transferring quality between positions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def resolve_positions(
        self,
        reservation: ReservedCollection,
        now: datetime,
    ) -> SirenePositionResolutionSummary:
        """Select API, then usable file positions, in one reconciled transaction."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                self._require_completed_sources(connection, reservation)
                self._validate_targets(connection, reservation)
                row = (
                    connection.execute(
                        text(self._resolution_statement()),
                        {
                            "cycle_id": reservation.cycle_id,
                            "rule_version": SIRENE_POSITION_RESOLUTION_RULE_VERSION,
                            "now": now,
                        },
                    )
                    .mappings()
                    .one()
                )
        except SirenePositionResolutionError:
            raise
        except SQLAlchemyError as error:
            raise SirenePositionResolutionError(
                "cannot resolve Sirene candidate positions"
            ) from error

        summary = self._summary_from_row(row)
        summary.validate()
        return summary

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
            raise SirenePositionResolutionError(
                "Sirene position resolution requires the active collection attempt"
            )

    @staticmethod
    def _require_completed_sources(
        connection: Connection,
        reservation: ReservedCollection,
    ) -> None:
        evidence = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) FILTER (
                            WHERE source.source = 'SIRENE_API'
                              AND source.status = 'SUCCEEDED'
                        ) AS api_source_count,
                        count(*) FILTER (
                            WHERE source.source = 'SIRENE_GEOLOCATION'
                              AND source.status = 'SUCCEEDED'
                              AND release.status = 'ACTIVE'
                        ) AS file_source_count
                    FROM collection_source_run AS source
                    LEFT JOIN dataset_release AS release
                      ON release.id = source.dataset_release_id
                    WHERE source.collection_cycle_id = :cycle_id
                      AND source.source IN ('SIRENE_API', 'SIRENE_GEOLOCATION')
                    """
                ),
                {"cycle_id": reservation.cycle_id},
            )
            .mappings()
            .one()
        )
        if evidence["api_source_count"] != 1 or evidence["file_source_count"] != 1:
            raise SirenePositionResolutionError(
                "Sirene API and geolocation sources must both be reconciled first"
            )

    @staticmethod
    def _validate_targets(
        connection: Connection,
        reservation: ReservedCollection,
    ) -> None:
        evidence = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(item.id) AS item_count,
                        count(position.id) AS api_position_count
                    FROM collection_item AS item
                    JOIN collection_batch AS batch
                      ON batch.id = item.collection_batch_id
                     AND batch.last_collection_attempt_id = item.collection_attempt_id
                     AND batch.state = 'SUCCEEDED'
                    JOIN collection_source_run AS source
                      ON source.id = batch.source_run_id
                     AND source.source = 'SIRENE_API'
                     AND source.status = 'SUCCEEDED'
                    LEFT JOIN candidate_position AS position
                      ON position.collection_item_id = item.id
                     AND position.origin = 'SIRENE_API'
                    WHERE item.collection_cycle_id = :cycle_id
                      AND item.normalization_result = 'VALID'
                    """
                ),
                {"cycle_id": reservation.cycle_id},
            )
            .mappings()
            .one()
        )
        if evidence["item_count"] != evidence["api_position_count"]:
            raise SirenePositionResolutionError(
                "a current Sirene candidate is missing its API position assessment"
            )

    @staticmethod
    def _resolution_statement() -> str:
        return """
            WITH targets AS (
                SELECT
                    item.id AS collection_item_id,
                    api.id AS api_position_id,
                    api.point AS api_point,
                    api.precision AS api_precision,
                    api.usability AS api_usability,
                    api.municipality_consistent AS api_municipality_consistent,
                    api.geographic_classification AS api_classification,
                    api.distance_meters AS api_distance_meters,
                    api.diagnostics ->> 'code' AS api_diagnostic_code,
                    file.id AS file_position_id,
                    file.point AS file_point,
                    file.precision AS file_precision,
                    file.usability AS file_usability,
                    file.municipality_consistent AS file_municipality_consistent,
                    file.geographic_classification AS file_classification,
                    file.distance_meters AS file_distance_meters,
                    file.quality_code AS file_quality_code,
                    file.diagnostics ->> 'code' AS file_diagnostic_code,
                    geocoded.id AS geocoder_position_id,
                    geocoded.precision AS geocoder_precision,
                    geocoded.usability AS geocoder_usability,
                    geocoded.municipality_consistent AS geocoder_municipality_consistent,
                    geocoded.geographic_classification AS geocoder_classification,
                    geocoded.distance_meters AS geocoder_distance_meters,
                    geocoded.diagnostics ->> 'code' AS geocoder_diagnostic_code,
                    COALESCE(geocoder_source.status = 'SUCCEEDED', FALSE)
                        AS geocoder_completed
                FROM collection_item AS item
                JOIN collection_batch AS batch
                  ON batch.id = item.collection_batch_id
                 AND batch.last_collection_attempt_id = item.collection_attempt_id
                 AND batch.state = 'SUCCEEDED'
                JOIN collection_source_run AS api_source
                  ON api_source.id = batch.source_run_id
                 AND api_source.source = 'SIRENE_API'
                 AND api_source.status = 'SUCCEEDED'
                JOIN collection_source_run AS file_source
                  ON file_source.collection_cycle_id = item.collection_cycle_id
                 AND file_source.source = 'SIRENE_GEOLOCATION'
                 AND file_source.status = 'SUCCEEDED'
                JOIN dataset_release AS file_release
                  ON file_release.id = file_source.dataset_release_id
                 AND file_release.status = 'ACTIVE'
                JOIN candidate_position AS api
                  ON api.collection_item_id = item.id
                 AND api.origin = 'SIRENE_API'
                LEFT JOIN candidate_position AS file
                  ON file.collection_item_id = item.id
                 AND file.origin = 'SIRENE_GEOLOCATION'
                 AND file.dataset_release_id = file_release.id
                LEFT JOIN collection_source_run AS geocoder_source
                  ON geocoder_source.collection_cycle_id = item.collection_cycle_id
                 AND geocoder_source.source = 'GEOPLATFORM_GEOCODER'
                LEFT JOIN candidate_position AS geocoded
                  ON geocoded.collection_item_id = item.id
                 AND geocoded.origin = 'GEOPLATFORM_GEOCODER'
                WHERE item.collection_cycle_id = :cycle_id
                  AND item.normalization_result = 'VALID'
            ),
            assessed AS (
                SELECT
                    targets.*,
                    COALESCE(
                        api_point IS NOT NULL
                        AND api_usability = 'USABLE'
                        AND api_municipality_consistent IS TRUE
                        AND api_classification IN ('IN_RADIUS', 'OUTSIDE_RADIUS')
                        AND api_distance_meters IS NOT NULL,
                        FALSE
                    ) AS api_usable,
                    COALESCE(
                        file_point IS NOT NULL
                        AND file_usability = 'USABLE'
                        AND file_municipality_consistent IS TRUE
                        AND file_classification IN ('IN_RADIUS', 'OUTSIDE_RADIUS')
                        AND file_distance_meters IS NOT NULL,
                        FALSE
                    ) AS file_usable,
                    COALESCE(
                        geocoder_completed
                        AND geocoder_position_id IS NOT NULL
                        AND geocoder_usability = 'USABLE'
                        AND geocoder_municipality_consistent IS TRUE
                        AND geocoder_classification IN ('IN_RADIUS', 'OUTSIDE_RADIUS')
                        AND geocoder_distance_meters IS NOT NULL,
                        FALSE
                    ) AS geocoder_usable
                FROM targets
            ),
            resolved AS (
                SELECT
                    assessed.*,
                    CASE
                        WHEN api_usable THEN 'SIRENE_API'
                        WHEN file_usable THEN 'SIRENE_GEOLOCATION'
                        WHEN geocoder_usable THEN 'GEOPLATFORM_GEOCODER'
                        ELSE NULL
                    END AS selected_origin,
                    CASE
                        WHEN api_usable THEN api_position_id
                        WHEN file_usable THEN file_position_id
                        WHEN geocoder_usable THEN geocoder_position_id
                        ELSE NULL
                    END AS selected_position_id,
                    CASE
                        WHEN api_usable THEN api_precision
                        WHEN file_usable THEN file_precision
                        WHEN geocoder_usable THEN geocoder_precision
                        ELSE NULL
                    END AS selected_precision,
                    CASE
                        WHEN api_usable THEN api_classification
                        WHEN file_usable THEN file_classification
                        WHEN geocoder_usable THEN geocoder_classification
                        ELSE 'LOCATION_UNKNOWN'
                    END AS selected_classification,
                    CASE
                        WHEN api_usable THEN api_distance_meters
                        WHEN file_usable THEN file_distance_meters
                        WHEN geocoder_usable THEN geocoder_distance_meters
                        ELSE NULL
                    END AS selected_distance_meters,
                    CASE
                        WHEN api_usable AND file_usable
                        THEN ST_Distance(api_point, file_point)
                        ELSE NULL
                    END AS api_file_gap_meters
                FROM assessed
            ),
            desired AS (
                SELECT
                    resolved.*,
                    jsonb_strip_nulls(
                        jsonb_build_object(
                            'code', CASE
                                WHEN selected_origin IS NOT NULL
                                THEN 'POSITION_RESOLVED'
                                WHEN geocoder_completed
                                THEN 'POSITION_UNRESOLVED'
                                ELSE 'POSITION_GEOCODING_REQUIRED'
                            END,
                            'position_source', selected_origin,
                            'candidate_position_id', selected_position_id,
                            'precision', selected_precision,
                            'usability', CASE
                                WHEN selected_origin IS NOT NULL THEN 'USABLE'
                                ELSE NULL
                            END,
                            'rule_version', CAST(:rule_version AS text),
                            'api_file_gap_meters', CASE
                                WHEN api_file_gap_meters > 1000
                                THEN api_file_gap_meters
                                ELSE NULL
                            END,
                            'api_file_divergence', CASE
                                WHEN api_file_gap_meters > 1000 THEN TRUE
                                ELSE NULL
                            END,
                            'api_usability', api_usability,
                            'api_diagnostic_code', api_diagnostic_code,
                            'file_usability', file_usability,
                            'file_quality_code', file_quality_code,
                            'file_diagnostic_code', file_diagnostic_code,
                            'geocoder_usability', geocoder_usability,
                            'geocoder_diagnostic_code', geocoder_diagnostic_code
                        )
                    ) AS resolution_reason
                FROM resolved
            ),
            updated AS (
                UPDATE collection_item AS item
                SET
                    geographic_classification = desired.selected_classification,
                    distance_meters = desired.selected_distance_meters,
                    reason = desired.resolution_reason,
                    updated_at = CASE
                        WHEN item.geographic_classification
                                 IS DISTINCT FROM desired.selected_classification
                          OR item.distance_meters
                                 IS DISTINCT FROM desired.selected_distance_meters
                          OR item.reason IS DISTINCT FROM desired.resolution_reason
                        THEN :now
                        ELSE item.updated_at
                    END
                FROM desired
                WHERE item.id = desired.collection_item_id
                RETURNING
                    desired.selected_origin,
                    desired.api_file_gap_meters,
                    desired.geocoder_completed
            )
            SELECT
                count(*) AS requested_count,
                count(*) FILTER (
                    WHERE selected_origin = 'SIRENE_API'
                ) AS api_selected_count,
                count(*) FILTER (
                    WHERE selected_origin = 'SIRENE_GEOLOCATION'
                ) AS file_selected_count,
                count(*) FILTER (
                    WHERE selected_origin = 'GEOPLATFORM_GEOCODER'
                ) AS geocoder_selected_count,
                count(*) FILTER (
                    WHERE selected_origin IS NULL AND NOT geocoder_completed
                ) AS geocoding_required_count,
                count(*) FILTER (
                    WHERE selected_origin IS NULL AND geocoder_completed
                ) AS unresolved_count,
                count(*) FILTER (
                    WHERE api_file_gap_meters > 1000
                ) AS divergent_count
            FROM updated
        """

    @staticmethod
    def _summary_from_row(row: RowMapping) -> SirenePositionResolutionSummary:
        values = (
            row["requested_count"],
            row["api_selected_count"],
            row["file_selected_count"],
            row["geocoder_selected_count"],
            row["geocoding_required_count"],
            row["unresolved_count"],
            row["divergent_count"],
        )
        if any(not isinstance(value, int) for value in values):
            raise SirenePositionResolutionError(
                "Sirene position-resolution counters have unexpected types"
            )
        return SirenePositionResolutionSummary(
            requested_count=values[0],
            api_selected_count=values[1],
            file_selected_count=values[2],
            geocoder_selected_count=values[3],
            geocoding_required_count=values[4],
            unresolved_count=values[5],
            divergent_count=values[6],
        )
