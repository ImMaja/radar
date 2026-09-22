"""PostgreSQL projection of resolved Sirene candidates into stable prospects."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.prospects.projection import (
    SireneProjectionPage,
    SireneProspectProjectionError,
    SireneProspectProjectionSummary,
)

_SOURCE_CODE = "SIRENE_API"
_DISPLAY_NAME_RULE = "sirene-display-name-v1"


class SqlAlchemySireneProspectProjectionRepository:
    """Project bounded pages while preserving user-owned opportunity state."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def pending_pages(
        self,
        reservation: ReservedCollection,
    ) -> tuple[SireneProjectionPage, ...]:
        """Return current successful provider pages with undecided candidates."""

        try:
            with self._engine.connect() as connection:
                self._require_ready_cycle(connection, reservation)
                rows = connection.execute(
                    text(
                        """
                        SELECT item.collection_batch_id, item.page_number
                        FROM collection_item AS item
                        JOIN collection_batch AS batch
                          ON batch.id = item.collection_batch_id
                         AND batch.last_collection_attempt_id = item.collection_attempt_id
                         AND batch.state = 'SUCCEEDED'
                        WHERE item.collection_cycle_id = :cycle_id
                          AND item.normalization_result = 'VALID'
                          AND item.decision IS NULL
                        GROUP BY item.collection_batch_id, item.page_number, batch.order_number
                        ORDER BY batch.order_number, item.page_number
                        """
                    ),
                    {"cycle_id": reservation.cycle_id},
                ).all()
        except SireneProspectProjectionError:
            raise
        except SQLAlchemyError as error:
            raise SireneProspectProjectionError(
                "cannot load pending Sirene prospect-projection pages"
            ) from error
        return tuple(
            SireneProjectionPage(collection_batch_id=row[0], page_number=row[1])
            for row in rows
            if isinstance(row[0], UUID) and isinstance(row[1], int)
        )

    def project_page(
        self,
        reservation: ReservedCollection,
        page: SireneProjectionPage,
        now: datetime,
    ) -> None:
        """Apply one page atomically, including lineage and current location."""

        if page.page_number < 1:
            raise ValueError("a Sirene projection page number must be positive")
        parameters: dict[str, object] = {
            "cycle_id": reservation.cycle_id,
            "batch_id": page.collection_batch_id,
            "page_number": page.page_number,
            "source_code": _SOURCE_CODE,
            "display_name_rule": _DISPLAY_NAME_RULE,
            "now": now,
        }
        try:
            with self._engine.begin() as connection:
                self._require_ready_cycle(connection, reservation)
                pending_count = self._lock_page(connection, parameters)
                if pending_count == 0:
                    return
                self._create_projection_input(connection, parameters)
                self._validate_projection_input(connection, pending_count)
                self._upsert_organizations(connection, parameters)
                self._upsert_establishments(connection, parameters)
                self._create_projection_targets(connection)
                self._validate_identity_targets(connection)
                self._insert_opportunities(connection, parameters)
                self._upsert_prospects(connection, parameters)
                self._touch_existing_opportunities(connection, parameters)
                self._link_external_identities(connection)
                self._upsert_source_bindings(connection, parameters)
                self._link_observations(connection)
                self._insert_source_sightings(connection, parameters)
                self._project_locations(connection, parameters)
                self._upsert_field_lineage(connection, parameters)
                self._complete_items(connection, parameters, pending_count)
        except SireneProspectProjectionError:
            raise
        except SQLAlchemyError as error:
            raise SireneProspectProjectionError(
                "cannot project a resolved Sirene candidate page"
            ) from error

    def summary(
        self,
        reservation: ReservedCollection,
    ) -> SireneProspectProjectionSummary:
        """Reconcile projection decisions across current successful attempts."""

        try:
            with self._engine.connect() as connection:
                self._require_ready_cycle(connection, reservation)
                row = (
                    connection.execute(
                        text(
                            """
                            SELECT
                                count(*) AS requested_count,
                                count(*) FILTER (WHERE item.decision = 'CREATED')
                                    AS created_count,
                                count(*) FILTER (WHERE item.decision = 'UPDATED')
                                    AS updated_count,
                                count(*) FILTER (WHERE item.decision = 'UNCHANGED')
                                    AS unchanged_count,
                                count(*) FILTER (WHERE item.decision = 'COUNTED_ONLY')
                                    AS counted_only_count,
                                count(*) FILTER (
                                    WHERE item.decision IN ('CREATED', 'UPDATED', 'UNCHANGED')
                                      AND item.geographic_classification = 'LOCATION_UNKNOWN'
                                ) AS location_unknown_count,
                                count(*) FILTER (WHERE item.decision IS NULL)
                                    AS pending_count,
                                count(*) FILTER (
                                    WHERE item.decision IS NOT NULL
                                      AND item.decision NOT IN (
                                          'CREATED', 'UPDATED', 'UNCHANGED', 'COUNTED_ONLY'
                                      )
                                ) AS unexpected_count
                            FROM collection_item AS item
                            JOIN collection_batch AS batch
                              ON batch.id = item.collection_batch_id
                             AND batch.last_collection_attempt_id
                                    = item.collection_attempt_id
                             AND batch.state = 'SUCCEEDED'
                            WHERE item.collection_cycle_id = :cycle_id
                              AND item.normalization_result = 'VALID'
                            """
                        ),
                        {"cycle_id": reservation.cycle_id},
                    )
                    .mappings()
                    .one()
                )
        except SireneProspectProjectionError:
            raise
        except SQLAlchemyError as error:
            raise SireneProspectProjectionError(
                "cannot reconcile Sirene prospect projections"
            ) from error

        if row["pending_count"] != 0 or row["unexpected_count"] != 0:
            raise SireneProspectProjectionError(
                "Sirene prospect projection contains undecided or unexpected items"
            )
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
            raise SireneProspectProjectionError(
                "Sirene prospect projection requires the active collection attempt"
            )

    def _require_ready_cycle(
        self,
        connection: Connection,
        reservation: ReservedCollection,
    ) -> None:
        self._require_active_attempt(connection, reservation)
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
                        ) AS file_count,
                        count(*) FILTER (
                            WHERE source = 'GEOPLATFORM_GEOCODER' AND status = 'SUCCEEDED'
                        ) AS geocoder_count
                    FROM collection_source_run
                    WHERE collection_cycle_id = :cycle_id
                    """
                ),
                {"cycle_id": reservation.cycle_id},
            )
            .mappings()
            .one()
        )
        source_counts = (
            evidence["api_count"],
            evidence["file_count"],
            evidence["geocoder_count"],
        )
        if source_counts != (1, 1, 1):
            raise SireneProspectProjectionError(
                "Sirene prospect projection requires all geographic sources to succeed"
            )
        unresolved_stage_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM collection_item AS item
                JOIN collection_batch AS batch
                  ON batch.id = item.collection_batch_id
                 AND batch.last_collection_attempt_id = item.collection_attempt_id
                 AND batch.state = 'SUCCEEDED'
                WHERE item.collection_cycle_id = :cycle_id
                  AND item.normalization_result = 'VALID'
                  AND COALESCE(item.reason ->> 'code', '')
                        NOT IN ('POSITION_RESOLVED', 'POSITION_UNRESOLVED')
                """
            ),
            {"cycle_id": reservation.cycle_id},
        ).scalar_one()
        if unresolved_stage_count:
            raise SireneProspectProjectionError(
                "Sirene candidate positions are not finally resolved"
            )

    @staticmethod
    def _lock_page(connection: Connection, parameters: dict[str, object]) -> int:
        rows = connection.execute(
            text(
                """
                SELECT item.id
                FROM collection_item AS item
                JOIN collection_batch AS batch
                  ON batch.id = item.collection_batch_id
                 AND batch.last_collection_attempt_id = item.collection_attempt_id
                 AND batch.state = 'SUCCEEDED'
                WHERE item.collection_cycle_id = :cycle_id
                  AND item.collection_batch_id = :batch_id
                  AND item.page_number = :page_number
                  AND item.normalization_result = 'VALID'
                  AND item.decision IS NULL
                ORDER BY item.item_rank
                FOR UPDATE OF item
                """
            ),
            parameters,
        ).all()
        return len(rows)

    @staticmethod
    def _create_projection_input(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_projection_input ON COMMIT DROP AS
                SELECT
                    item.id AS collection_item_id,
                    item.external_identity_id,
                    item.source_observation_id,
                    item.geographic_classification,
                    item.reason AS resolution_reason,
                    observation.payload,
                    position.id AS candidate_position_id,
                    position.source_observation_id AS position_observation_id,
                    position.dataset_release_id,
                    position.origin AS candidate_origin,
                    position.point,
                    position.source_crs,
                    position.quality_code,
                    position.precision,
                    position.usability,
                    position.diagnostics AS position_diagnostics
                FROM collection_item AS item
                JOIN collection_batch AS batch
                  ON batch.id = item.collection_batch_id
                 AND batch.last_collection_attempt_id = item.collection_attempt_id
                 AND batch.state = 'SUCCEEDED'
                JOIN source_observation AS observation
                  ON observation.id = item.source_observation_id
                 AND observation.data_source_code = :source_code
                 AND observation.validation_status = 'VALID'
                LEFT JOIN candidate_position AS position
                  ON position.id = CASE
                      WHEN item.reason ? 'candidate_position_id'
                      THEN CAST(item.reason ->> 'candidate_position_id' AS uuid)
                      ELSE NULL
                  END
                 AND position.collection_item_id = item.id
                WHERE item.collection_cycle_id = :cycle_id
                  AND item.collection_batch_id = :batch_id
                  AND item.page_number = :page_number
                  AND item.normalization_result = 'VALID'
                  AND item.decision IS NULL
                """
            ),
            parameters,
        )

    @staticmethod
    def _validate_projection_input(connection: Connection, expected_count: int) -> None:
        evidence = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS input_count,
                        count(*) FILTER (
                            WHERE external_identity_id IS NULL
                               OR source_observation_id IS NULL
                               OR payload ->> 'siret' IS NULL
                               OR payload ->> 'siren' IS NULL
                               OR geographic_classification NOT IN (
                                   'IN_RADIUS', 'OUTSIDE_RADIUS', 'LOCATION_UNKNOWN'
                               )
                               OR resolution_reason ->> 'code'
                                    NOT IN ('POSITION_RESOLVED', 'POSITION_UNRESOLVED')
                               OR (
                                   resolution_reason ->> 'code' = 'POSITION_RESOLVED'
                                   AND (
                                       candidate_position_id IS NULL
                                       OR usability <> 'USABLE'
                                   )
                               )
                        ) AS invalid_count
                    FROM sirene_projection_input
                    """
                )
            )
            .mappings()
            .one()
        )
        if evidence["input_count"] != expected_count or evidence["invalid_count"] != 0:
            raise SireneProspectProjectionError(
                "a Sirene projection page contains incomplete resolved candidates"
            )

    @staticmethod
    def _upsert_organizations(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO organization (
                    id,
                    siren,
                    legal_name,
                    usual_name,
                    organization_type,
                    legal_category,
                    administrative_state,
                    diffusion_status,
                    current_observation_id,
                    administrative_state_observation_id,
                    diffusion_status_observation_id,
                    first_observed_at,
                    last_observed_at,
                    created_at,
                    updated_at
                )
                SELECT DISTINCT ON (input.payload ->> 'siren')
                    gen_random_uuid(),
                    input.payload ->> 'siren',
                    NULLIF(input.payload ->> 'legal_name', ''),
                    NULLIF(input.payload #>> '{legal_usual_names,0}', ''),
                    'UNKNOWN',
                    NULLIF(input.payload ->> 'legal_category', ''),
                    'ACTIVE',
                    'FULL',
                    input.source_observation_id,
                    input.source_observation_id,
                    input.source_observation_id,
                    :now,
                    :now,
                    :now,
                    :now
                FROM sirene_projection_input AS input
                WHERE input.geographic_classification IN ('IN_RADIUS', 'LOCATION_UNKNOWN')
                ORDER BY input.payload ->> 'siren', input.collection_item_id
                ON CONFLICT (siren) DO UPDATE SET
                    legal_name = EXCLUDED.legal_name,
                    usual_name = EXCLUDED.usual_name,
                    legal_category = EXCLUDED.legal_category,
                    administrative_state = 'ACTIVE',
                    diffusion_status = 'FULL',
                    current_observation_id = EXCLUDED.current_observation_id,
                    administrative_state_observation_id
                        = EXCLUDED.administrative_state_observation_id,
                    diffusion_status_observation_id
                        = EXCLUDED.diffusion_status_observation_id,
                    last_observed_at = GREATEST(
                        organization.last_observed_at,
                        EXCLUDED.last_observed_at
                    ),
                    updated_at = EXCLUDED.updated_at
                """
            ),
            parameters,
        )

    @staticmethod
    def _upsert_establishments(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO establishment (
                    id,
                    organization_id,
                    siret,
                    is_head_office,
                    source_names,
                    activity_code,
                    activity_nomenclature,
                    activity_label,
                    employee_band,
                    employee_year,
                    employee_scope,
                    administrative_state,
                    diffusion_status,
                    established_on,
                    current_period_started_on,
                    source_processed_at,
                    current_observation_id,
                    administrative_state_observation_id,
                    diffusion_status_observation_id,
                    first_observed_at,
                    last_observed_at,
                    created_at,
                    updated_at
                )
                SELECT
                    gen_random_uuid(),
                    organization.id,
                    input.payload ->> 'siret',
                    CAST(input.payload ->> 'is_head_office' AS boolean),
                    COALESCE(input.payload -> 'establishment_names', '[]'::jsonb),
                    NULLIF(input.payload #>> '{activity,code}', ''),
                    NULLIF(input.payload #>> '{activity,nomenclature}', ''),
                    NULL,
                    NULLIF(input.payload ->> 'employee_band', ''),
                    CAST(NULLIF(input.payload ->> 'employee_year', '') AS integer),
                    CASE
                        WHEN NULLIF(input.payload ->> 'employee_band', '') IS NULL
                        THEN 'UNKNOWN'
                        ELSE 'LOCAL'
                    END,
                    'ACTIVE',
                    'FULL',
                    CAST(NULLIF(input.payload ->> 'establishment_created_on', '') AS date),
                    CAST(NULLIF(input.payload ->> 'current_period_started_on', '') AS date),
                    NULLIF(input.payload ->> 'establishment_processed_at', ''),
                    input.source_observation_id,
                    input.source_observation_id,
                    input.source_observation_id,
                    :now,
                    :now,
                    :now,
                    :now
                FROM sirene_projection_input AS input
                JOIN organization
                  ON organization.siren = input.payload ->> 'siren'
                WHERE input.geographic_classification IN ('IN_RADIUS', 'LOCATION_UNKNOWN')
                ON CONFLICT (siret) DO UPDATE SET
                    organization_id = EXCLUDED.organization_id,
                    is_head_office = EXCLUDED.is_head_office,
                    source_names = EXCLUDED.source_names,
                    activity_code = EXCLUDED.activity_code,
                    activity_nomenclature = EXCLUDED.activity_nomenclature,
                    activity_label = EXCLUDED.activity_label,
                    employee_band = EXCLUDED.employee_band,
                    employee_year = EXCLUDED.employee_year,
                    employee_scope = EXCLUDED.employee_scope,
                    administrative_state = 'ACTIVE',
                    diffusion_status = 'FULL',
                    established_on = EXCLUDED.established_on,
                    current_period_started_on = EXCLUDED.current_period_started_on,
                    source_processed_at = EXCLUDED.source_processed_at,
                    current_observation_id = EXCLUDED.current_observation_id,
                    administrative_state_observation_id
                        = EXCLUDED.administrative_state_observation_id,
                    diffusion_status_observation_id
                        = EXCLUDED.diffusion_status_observation_id,
                    last_observed_at = GREATEST(
                        establishment.last_observed_at,
                        EXCLUDED.last_observed_at
                    ),
                    updated_at = EXCLUDED.updated_at
                """
            ),
            parameters,
        )

    @staticmethod
    def _create_projection_targets(connection: Connection) -> None:
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_projection_target ON COMMIT DROP AS
                SELECT
                    input.*,
                    establishment.id AS establishment_id,
                    existing.id AS existing_opportunity_id,
                    COALESCE(existing.id, gen_random_uuid()) AS opportunity_id,
                    existing.id IS NULL AS was_created,
                    binding.current_observation_id AS prior_observation_id,
                    binding.opportunity_id AS bound_opportunity_id,
                    COALESCE(
                        NULLIF(input.payload #>> '{establishment_names,0}', ''),
                        NULLIF(input.payload #>> '{legal_usual_names,0}', ''),
                        NULLIF(input.payload ->> 'legal_name', ''),
                        'Établissement ' || (input.payload ->> 'siret')
                    ) AS display_name,
                    CASE
                        WHEN NULLIF(input.payload #>> '{establishment_names,0}', '')
                             IS NOT NULL
                        THEN 'establishment_names[0]'
                        WHEN NULLIF(input.payload #>> '{legal_usual_names,0}', '')
                             IS NOT NULL
                        THEN 'legal_usual_names[0]'
                        WHEN NULLIF(input.payload ->> 'legal_name', '') IS NOT NULL
                        THEN 'legal_name'
                        ELSE 'siret'
                    END AS display_name_source_path
                FROM sirene_projection_input AS input
                JOIN establishment
                  ON establishment.siret = input.payload ->> 'siret'
                LEFT JOIN prospect AS existing
                  ON existing.establishment_id = establishment.id
                LEFT JOIN source_binding AS binding
                  ON binding.data_source_code = 'SIRENE_API'
                 AND binding.external_identity_id = input.external_identity_id
                WHERE input.geographic_classification IN ('IN_RADIUS', 'LOCATION_UNKNOWN')
                """
            )
        )

    @staticmethod
    def _validate_identity_targets(connection: Connection) -> None:
        invalid_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM sirene_projection_target AS target
                JOIN external_identity AS identity
                  ON identity.id = target.external_identity_id
                WHERE identity.restricted_at IS NOT NULL
                   OR identity.organization_id IS NOT NULL
                   OR identity.opportunity_id IS NOT NULL
                   OR (
                       identity.establishment_id IS NOT NULL
                       AND identity.establishment_id <> target.establishment_id
                   )
                   OR (
                       target.bound_opportunity_id IS NOT NULL
                       AND target.bound_opportunity_id <> target.opportunity_id
                   )
                """
            )
        ).scalar_one()
        if invalid_count:
            raise SireneProspectProjectionError(
                "a Sirene identity is restricted or targets another business entity"
            )

    @staticmethod
    def _insert_opportunities(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO opportunity (
                    id,
                    kind,
                    creation_origin,
                    hidden_at,
                    hidden_reason,
                    duplicate_of_opportunity_id,
                    created_at,
                    updated_at
                )
                SELECT
                    target.opportunity_id,
                    'PROSPECT',
                    'SOURCE',
                    NULL,
                    NULL,
                    NULL,
                    :now,
                    :now
                FROM sirene_projection_target AS target
                WHERE target.was_created
                """
            ),
            parameters,
        )

    @staticmethod
    def _upsert_prospects(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO prospect (
                    id,
                    establishment_id,
                    source_display_name,
                    source_description,
                    source_organization_type,
                    source_business_signals,
                    eligibility,
                    eligibility_changed_at,
                    eligibility_reason,
                    first_observed_at,
                    last_observed_at,
                    created_at,
                    updated_at
                )
                SELECT
                    target.opportunity_id,
                    target.establishment_id,
                    target.display_name,
                    NULL,
                    'UNKNOWN',
                    '{}'::jsonb,
                    'ELIGIBLE',
                    :now,
                    'SIRENE_FULL_PUBLIC_DIFFUSION',
                    :now,
                    :now,
                    :now,
                    :now
                FROM sirene_projection_target AS target
                ON CONFLICT (establishment_id) DO UPDATE SET
                    source_display_name = EXCLUDED.source_display_name,
                    source_description = EXCLUDED.source_description,
                    source_organization_type = EXCLUDED.source_organization_type,
                    source_business_signals = EXCLUDED.source_business_signals,
                    eligibility = 'ELIGIBLE',
                    eligibility_changed_at = CASE
                        WHEN prospect.eligibility <> 'ELIGIBLE'
                          OR prospect.eligibility_reason
                                <> 'SIRENE_FULL_PUBLIC_DIFFUSION'
                        THEN EXCLUDED.eligibility_changed_at
                        ELSE prospect.eligibility_changed_at
                    END,
                    eligibility_reason = 'SIRENE_FULL_PUBLIC_DIFFUSION',
                    last_observed_at = GREATEST(
                        prospect.last_observed_at,
                        EXCLUDED.last_observed_at
                    ),
                    updated_at = EXCLUDED.updated_at
                """
            ),
            parameters,
        )

    @staticmethod
    def _touch_existing_opportunities(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                UPDATE opportunity AS opportunity
                SET updated_at = :now
                FROM sirene_projection_target AS target
                WHERE opportunity.id = target.opportunity_id
                  AND NOT target.was_created
                  AND target.prior_observation_id
                        IS DISTINCT FROM target.source_observation_id
                """
            ),
            parameters,
        )

    @staticmethod
    def _link_external_identities(connection: Connection) -> None:
        connection.execute(
            text(
                """
                UPDATE external_identity AS identity
                SET establishment_id = target.establishment_id
                FROM sirene_projection_target AS target
                WHERE identity.id = target.external_identity_id
                  AND identity.establishment_id IS DISTINCT FROM target.establishment_id
                """
            )
        )

    @staticmethod
    def _upsert_source_bindings(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO source_binding (
                    id,
                    data_source_code,
                    external_identity_id,
                    opportunity_id,
                    source_url,
                    producer_name,
                    first_observed_at,
                    last_observed_at,
                    current_observation_id,
                    state,
                    consecutive_absence_count,
                    last_checked_at,
                    created_at,
                    updated_at
                )
                SELECT
                    gen_random_uuid(),
                    :source_code,
                    target.external_identity_id,
                    target.opportunity_id,
                    NULL,
                    'INSEE',
                    :now,
                    :now,
                    target.source_observation_id,
                    'CURRENT',
                    0,
                    :now,
                    :now,
                    :now
                FROM sirene_projection_target AS target
                ON CONFLICT (data_source_code, external_identity_id) DO UPDATE SET
                    opportunity_id = EXCLUDED.opportunity_id,
                    last_observed_at = GREATEST(
                        source_binding.last_observed_at,
                        EXCLUDED.last_observed_at
                    ),
                    current_observation_id = EXCLUDED.current_observation_id,
                    state = 'CURRENT',
                    consecutive_absence_count = 0,
                    last_checked_at = EXCLUDED.last_checked_at,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            parameters,
        )

    @staticmethod
    def _link_observations(connection: Connection) -> None:
        connection.execute(
            text(
                """
                UPDATE source_observation AS observation
                SET source_binding_id = binding.id
                FROM sirene_projection_target AS target
                JOIN source_binding AS binding
                  ON binding.data_source_code = 'SIRENE_API'
                 AND binding.external_identity_id = target.external_identity_id
                WHERE observation.id = target.source_observation_id
                  AND observation.source_binding_id IS DISTINCT FROM binding.id
                """
            )
        )

    @staticmethod
    def _insert_source_sightings(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO source_sighting (
                    source_binding_id,
                    collection_cycle_id,
                    source_observation_id,
                    seen_at
                )
                SELECT
                    binding.id,
                    :cycle_id,
                    target.source_observation_id,
                    :now
                FROM sirene_projection_target AS target
                JOIN source_binding AS binding
                  ON binding.data_source_code = :source_code
                 AND binding.external_identity_id = target.external_identity_id
                ON CONFLICT (source_binding_id, collection_cycle_id) DO UPDATE SET
                    source_observation_id = EXCLUDED.source_observation_id,
                    seen_at = EXCLUDED.seen_at
                """
            ),
            parameters,
        )

    def _project_locations(
        self,
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        self._create_location_values(connection)
        connection.execute(
            text(
                """
                UPDATE location_assertion AS current
                SET
                    is_current = FALSE,
                    retired_at = :now,
                    updated_at = :now
                FROM sirene_location_value AS value
                WHERE current.opportunity_id = value.opportunity_id
                  AND current.layer = 'SOURCE'
                  AND current.is_current
                  AND (
                      current.full_address IS DISTINCT FROM value.full_address
                      OR current.structured_address IS DISTINCT FROM value.structured_address
                      OR current.municipality_code
                            IS DISTINCT FROM value.municipality_code
                      OR current.postcode IS DISTINCT FROM value.postcode
                      OR current.position_origin IS DISTINCT FROM value.position_origin
                      OR current.source_crs IS DISTINCT FROM value.source_crs
                      OR current.quality_code IS DISTINCT FROM value.quality_code
                      OR current.match_score IS DISTINCT FROM value.match_score
                      OR current.precision IS DISTINCT FROM value.precision
                      OR current.usability IS DISTINCT FROM value.usability
                      OR current.address_observation_id
                            IS DISTINCT FROM value.address_observation_id
                      OR current.position_observation_id
                            IS DISTINCT FROM value.position_observation_id
                      OR current.dataset_release_id
                            IS DISTINCT FROM value.dataset_release_id
                      OR current.rule_version IS DISTINCT FROM value.rule_version
                      OR current.diagnostics IS DISTINCT FROM value.diagnostics
                      OR (current.point IS NULL) <> (value.point IS NULL)
                      OR (
                          current.point IS NOT NULL
                          AND value.point IS NOT NULL
                          AND NOT ST_Equals(current.point::geometry, value.point::geometry)
                      )
                  )
                """
            ),
            parameters,
        )
        connection.execute(
            text(
                """
                INSERT INTO location_assertion (
                    id,
                    opportunity_id,
                    layer,
                    full_address,
                    structured_address,
                    municipality_code,
                    postcode,
                    country_code,
                    point,
                    position_origin,
                    source_crs,
                    quality_code,
                    match_score,
                    precision,
                    usability,
                    address_observation_id,
                    position_observation_id,
                    dataset_release_id,
                    candidate_position_id,
                    rule_version,
                    diagnostics,
                    is_current,
                    created_at,
                    retired_at,
                    updated_at
                )
                SELECT
                    gen_random_uuid(),
                    value.opportunity_id,
                    'SOURCE',
                    value.full_address,
                    value.structured_address,
                    value.municipality_code,
                    value.postcode,
                    'FR',
                    value.point,
                    value.position_origin,
                    value.source_crs,
                    value.quality_code,
                    value.match_score,
                    value.precision,
                    value.usability,
                    value.address_observation_id,
                    value.position_observation_id,
                    value.dataset_release_id,
                    value.candidate_position_id,
                    value.rule_version,
                    value.diagnostics,
                    TRUE,
                    :now,
                    NULL,
                    :now
                FROM sirene_location_value AS value
                LEFT JOIN location_assertion AS current
                  ON current.opportunity_id = value.opportunity_id
                 AND current.layer = 'SOURCE'
                 AND current.is_current
                WHERE current.id IS NULL
                """
            ),
            parameters,
        )

    @staticmethod
    def _create_location_values(connection: Connection) -> None:
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_location_value ON COMMIT DROP AS
                SELECT
                    target.opportunity_id,
                    NULLIF(
                        concat_ws(
                            ' ',
                            NULLIF(target.payload #>> '{address,street_number}', ''),
                            NULLIF(target.payload #>> '{address,repetition_index}', ''),
                            NULLIF(target.payload #>> '{address,street_type}', ''),
                            NULLIF(target.payload #>> '{address,street_label}', ''),
                            NULLIF(target.payload #>> '{address,address_complement}', ''),
                            NULLIF(target.payload #>> '{address,postcode}', ''),
                            NULLIF(target.payload #>> '{address,municipality_label}', '')
                        ),
                        ''
                    ) AS full_address,
                    (COALESCE(target.payload #> '{address}', '{}'::jsonb) - 'coordinates')
                        AS structured_address,
                    NULLIF(target.payload #>> '{address,municipality_code}', '')
                        AS municipality_code,
                    NULLIF(target.payload #>> '{address,postcode}', '') AS postcode,
                    target.point,
                    CASE target.candidate_origin
                        WHEN 'SIRENE_GEOLOCATION' THEN 'SIRENE_DATASET'
                        WHEN 'GEOPLATFORM_GEOCODER' THEN 'GEOPLATFORM_GEOCODER'
                        ELSE 'SIRENE_API'
                    END AS position_origin,
                    target.source_crs,
                    target.quality_code,
                    CAST(
                        NULLIF(target.position_diagnostics ->> 'score', '')
                        AS double precision
                    ) AS match_score,
                    COALESCE(target.precision, 'UNKNOWN') AS precision,
                    CASE
                        WHEN target.candidate_position_id IS NOT NULL THEN 'USABLE'
                        WHEN target.resolution_reason ->> 'geocoder_usability' = 'TO_VERIFY'
                        THEN 'TO_VERIFY'
                        ELSE 'MISSING'
                    END AS usability,
                    target.source_observation_id AS address_observation_id,
                    target.position_observation_id,
                    target.dataset_release_id,
                    target.candidate_position_id,
                    target.resolution_reason ->> 'rule_version' AS rule_version,
                    target.resolution_reason - 'candidate_position_id' AS diagnostics
                FROM sirene_projection_target AS target
                """
            )
        )

    @staticmethod
    def _upsert_field_lineage(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO field_lineage (
                    opportunity_id,
                    field_code,
                    source_observation_id,
                    source_path,
                    resolution_rule,
                    resolved_at
                )
                SELECT
                    target.opportunity_id,
                    lineage.field_code,
                    target.source_observation_id,
                    lineage.source_path,
                    lineage.resolution_rule,
                    :now
                FROM sirene_projection_target AS target
                CROSS JOIN LATERAL (
                    VALUES
                        (
                            'PROSPECT_DISPLAY_NAME',
                            target.display_name_source_path,
                            CAST(:display_name_rule AS text)
                        ),
                        ('PROSPECT_ORGANIZATION_TYPE', 'legal_category',
                            'sirene-organization-type-unmapped-v1'),
                        ('PROSPECT_ACTIVITY', 'activity', NULL),
                        ('PROSPECT_EMPLOYEE_BAND', 'employee_band', NULL)
                ) AS lineage(field_code, source_path, resolution_rule)
                WHERE lineage.field_code NOT IN ('PROSPECT_ACTIVITY', 'PROSPECT_EMPLOYEE_BAND')
                   OR (
                       lineage.field_code = 'PROSPECT_ACTIVITY'
                       AND target.payload -> 'activity' IS NOT NULL
                   )
                   OR (
                       lineage.field_code = 'PROSPECT_EMPLOYEE_BAND'
                       AND target.payload ->> 'employee_band' IS NOT NULL
                   )
                ON CONFLICT (opportunity_id, field_code) DO UPDATE SET
                    source_observation_id = EXCLUDED.source_observation_id,
                    source_path = EXCLUDED.source_path,
                    resolution_rule = EXCLUDED.resolution_rule,
                    resolved_at = EXCLUDED.resolved_at
                """
            ),
            parameters,
        )

    @staticmethod
    def _complete_items(
        connection: Connection,
        parameters: dict[str, object],
        expected_count: int,
    ) -> None:
        updated_count = connection.execute(
            text(
                """
                UPDATE collection_item AS item
                SET
                    opportunity_id = target.opportunity_id,
                    decision = CASE
                        WHEN input.geographic_classification = 'OUTSIDE_RADIUS'
                        THEN 'COUNTED_ONLY'
                        WHEN target.was_created THEN 'CREATED'
                        WHEN target.prior_observation_id
                             IS DISTINCT FROM target.source_observation_id
                        THEN 'UPDATED'
                        ELSE 'UNCHANGED'
                    END,
                    reason = input.resolution_reason || jsonb_build_object(
                        'projection_code', CASE
                            WHEN input.geographic_classification = 'OUTSIDE_RADIUS'
                            THEN 'OUTSIDE_COLLECTION_RADIUS'
                            ELSE 'PROSPECT_PROJECTED'
                        END
                    ),
                    updated_at = :now
                FROM sirene_projection_input AS input
                LEFT JOIN sirene_projection_target AS target
                  ON target.collection_item_id = input.collection_item_id
                WHERE item.id = input.collection_item_id
                  AND item.decision IS NULL
                """
            ),
            parameters,
        ).rowcount
        if updated_count != expected_count:
            raise SireneProspectProjectionError(
                "Sirene prospect-projection page decisions do not reconcile"
            )

    @staticmethod
    def _summary_from_row(row: RowMapping) -> SireneProspectProjectionSummary:
        values = (
            row["requested_count"],
            row["created_count"],
            row["updated_count"],
            row["unchanged_count"],
            row["counted_only_count"],
            row["location_unknown_count"],
        )
        if any(not isinstance(value, int) for value in values):
            raise SireneProspectProjectionError(
                "Sirene prospect-projection counters have unexpected types"
            )
        return SireneProspectProjectionSummary(
            requested_count=values[0],
            created_count=values[1],
            updated_count=values[2],
            unchanged_count=values[3],
            counted_only_count=values[4],
            location_unknown_count=values[5],
        )
