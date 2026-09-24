"""PostgreSQL reconciliation of known SIRET absent from active discovery."""

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.prospects.status_reconciliation import (
    SireneKnownStatusError,
    SireneKnownStatusPlan,
    SireneKnownStatusSummary,
)
from radar.providers.sirene import SireneEstablishmentStatus, SireneStatusLookup

_SOURCE = "SIRENE_KNOWN_STATUS"
_DATA_SOURCE = "SIRENE_API"
_CONTRACT_VERSION = "sirene-known-status-v2"
_SCHEMA_VERSION = "sirene-known-status-v2"
_ADAPTER_VERSION = "sirene-3.11-known-status-v2"
_INPUT_RECORDSET = """
jsonb_to_recordset(CAST(:records AS jsonb)) AS input(
    siret text,
    siren text,
    establishment_state text,
    legal_unit_state text,
    establishment_diffusion text,
    legal_unit_diffusion text,
    outcome text,
    observation_id uuid,
    content_fingerprint text,
    payload jsonb
)
"""
_RESTRICTED_RECORDSET = """
jsonb_to_recordset(CAST(:restricted_records AS jsonb)) AS input(
    siret text,
    siren text,
    legal_unit_restricted boolean
)
"""


def _status_outcome(status: SireneEstablishmentStatus) -> str:
    if status.legal_unit_administrative_state == "CEASED":
        return "CEASED"
    if status.establishment_administrative_state == "CLOSED":
        return "CLOSED"
    return "ACTIVE"


def _payload(status: SireneEstablishmentStatus) -> dict[str, object]:
    return {
        "siret": status.siret,
        "siren": status.siren,
        "establishment_administrative_state": status.establishment_administrative_state,
        "legal_unit_administrative_state": status.legal_unit_administrative_state,
        "establishment_diffusion_status": status.establishment_diffusion_status,
        "legal_unit_diffusion_status": status.legal_unit_diffusion_status,
    }


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SqlAlchemySireneKnownStatusRepository:
    """Persist targeted checks, explicit states, and restriction purges."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def prepare(
        self,
        reservation: ReservedCollection,
        now: datetime,
    ) -> SireneKnownStatusPlan:
        """Start or resume the targeted source and return only unchecked known SIRET."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                self._require_projection_complete(connection, reservation)
                self._ensure_source_run(connection, reservation, now)
                state = self._source_state(connection, reservation)
                if state["status"] not in {"RUNNING", "SUCCEEDED"}:
                    raise SireneKnownStatusError("the Sirene known-status source is not resumable")
                completed_count = self._completed_count(connection, reservation)
                pending_sirets = (
                    ()
                    if state["status"] == "SUCCEEDED"
                    else self._pending_sirets(connection, reservation)
                )
                return SireneKnownStatusPlan(
                    query_date=self._query_date(connection, reservation),
                    total_count=completed_count + len(pending_sirets),
                    completed_count=completed_count,
                    pending_sirets=pending_sirets,
                )
        except SireneKnownStatusError:
            raise
        except SQLAlchemyError as error:
            raise SireneKnownStatusError(
                "cannot prepare known Sirene establishment checks"
            ) from error

    def record(
        self,
        reservation: ReservedCollection,
        lookup: SireneStatusLookup,
        now: datetime,
    ) -> None:
        """Persist one lookup atomically, purging any restricted targets."""

        records, restricted_records = self._records(lookup)
        parameters: dict[str, object] = {
            "cycle_id": reservation.cycle_id,
            "records": json.dumps(records, ensure_ascii=False, separators=(",", ":")),
            "restricted_records": json.dumps(
                restricted_records,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "restricted_count": len(restricted_records),
            "data_source": _DATA_SOURCE,
            "adapter_version": _ADAPTER_VERSION,
            "schema_version": _SCHEMA_VERSION,
            "now": now,
        }
        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                self._require_running_source(connection, reservation)
                self._create_input(connection, parameters)
                self._create_restricted_targets(connection, parameters)
                normal_count = connection.execute(
                    text("SELECT count(*) FROM sirene_known_status_input")
                ).scalar_one()
                restricted_count = connection.execute(
                    text("SELECT count(*) FROM sirene_restricted_input")
                ).scalar_one()
                if normal_count != len(records) or restricted_count != len(restricted_records):
                    raise SireneKnownStatusError(
                        "a targeted Sirene lookup no longer matches its pending identities"
                    )
                self._insert_observations(connection, parameters)
                self._insert_checks(connection, parameters)
                self._apply_organization_states(connection, parameters)
                self._apply_establishment_states(connection, parameters)
                self._reactivate_eligible_prospects(connection, parameters)
                self._touch_changed_opportunities(connection, parameters)
                self._insert_sightings(connection, parameters)
                self._update_bindings(connection, parameters)
                self._purge_restricted_targets(connection, parameters)
                self._increment_request_count(connection, parameters)
        except SireneKnownStatusError:
            raise
        except SQLAlchemyError as error:
            raise SireneKnownStatusError(
                "cannot persist known Sirene establishment checks"
            ) from error

    def record_failure(
        self,
        reservation: ReservedCollection,
        code: str,
        *,
        transient: bool,
        now: datetime,
    ) -> None:
        """Retain only a non-sensitive source-level failure diagnostic."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                updated = connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET
                            status = CASE WHEN :transient THEN status ELSE 'FAILED' END,
                            finished_at = CASE WHEN :transient THEN NULL ELSE :now END,
                            request_count = request_count + 1,
                            retry_count = retry_count + CASE WHEN :transient THEN 1 ELSE 0 END,
                            error_count = error_count + 1,
                            metadata = jsonb_set(
                                metadata,
                                '{last_error_code}',
                                to_jsonb(CAST(:code AS text)),
                                TRUE
                            ),
                            updated_at = :now
                        WHERE collection_cycle_id = :cycle_id
                          AND source = :source
                          AND status = 'RUNNING'
                        RETURNING id
                        """
                    ),
                    {
                        "cycle_id": reservation.cycle_id,
                        "source": _SOURCE,
                        "code": code,
                        "transient": transient,
                        "now": now,
                    },
                ).scalar_one_or_none()
                if updated is None:
                    raise SireneKnownStatusError(
                        "the Sirene known-status source cannot record its failure"
                    )
        except SireneKnownStatusError:
            raise
        except SQLAlchemyError as error:
            raise SireneKnownStatusError(
                "cannot record the known Sirene establishment failure"
            ) from error

    def finish(
        self,
        reservation: ReservedCollection,
        now: datetime,
    ) -> SireneKnownStatusSummary:
        """Reconcile all targeted outcomes and complete the dedicated source run."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                state = self._source_state(connection, reservation)
                if state["status"] == "SUCCEEDED":
                    return self._summary(connection, reservation)
                self._require_running_source(connection, reservation)
                if self._pending_sirets(connection, reservation):
                    raise SireneKnownStatusError("known Sirene establishments remain unchecked")
                summary = self._summary(connection, reservation)
                summary.validate()
                completed = connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET
                            status = 'SUCCEEDED',
                            finished_at = :now,
                            counters = CAST(:counters AS jsonb),
                            metadata = metadata - 'last_error_code',
                            updated_at = :now
                        WHERE collection_cycle_id = :cycle_id
                          AND source = :source
                          AND status = 'RUNNING'
                        RETURNING id
                        """
                    ),
                    {
                        "cycle_id": reservation.cycle_id,
                        "source": _SOURCE,
                        "counters": json.dumps(
                            {
                                "checked_count": summary.checked_count,
                                "active_count": summary.active_count,
                                "closed_count": summary.closed_count,
                                "ceased_count": summary.ceased_count,
                                "restricted_count": summary.restricted_count,
                                "not_found_count": summary.not_found_count,
                            }
                        ),
                        "now": now,
                    },
                ).scalar_one_or_none()
                if completed is None:
                    raise SireneKnownStatusError(
                        "the Sirene known-status source cannot be completed"
                    )
                return summary
        except SireneKnownStatusError:
            raise
        except SQLAlchemyError as error:
            raise SireneKnownStatusError(
                "cannot complete known Sirene establishment checks"
            ) from error

    @staticmethod
    def _records(
        lookup: SireneStatusLookup,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        requested = tuple(lookup.requested_sirets)
        if not requested or len(set(requested)) != len(requested):
            raise SireneKnownStatusError("a targeted Sirene lookup has invalid requests")
        statuses = {status.siret: status for status in lookup.statuses}
        if len(statuses) != len(lookup.statuses):
            raise SireneKnownStatusError("a targeted Sirene lookup contains duplicate states")
        missing = set(lookup.missing_sirets)
        if len(missing) != len(lookup.missing_sirets):
            raise SireneKnownStatusError("a targeted Sirene lookup contains duplicate absences")
        if set(statuses).intersection(missing) or set(requested) != set(statuses).union(missing):
            raise SireneKnownStatusError("a targeted Sirene lookup does not reconcile")
        legal_states: dict[str, tuple[str, str]] = {}
        records: list[dict[str, object]] = []
        restricted_records: list[dict[str, object]] = []
        for siret in requested:
            status = statuses.get(siret)
            if status is None:
                records.append(
                    {
                        "siret": siret,
                        "siren": None,
                        "establishment_state": None,
                        "legal_unit_state": None,
                        "establishment_diffusion": None,
                        "legal_unit_diffusion": None,
                        "outcome": "NOT_FOUND",
                        "observation_id": None,
                        "content_fingerprint": None,
                        "payload": None,
                    }
                )
                continue
            legal_state = (
                status.legal_unit_administrative_state,
                status.legal_unit_diffusion_status,
            )
            previous_legal_state = legal_states.setdefault(status.siren, legal_state)
            if previous_legal_state != legal_state:
                raise SireneKnownStatusError(
                    "targeted Sirene establishments disagree on their legal-unit state"
                )
            if status.has_partial_diffusion:
                restricted_records.append(
                    {
                        "siret": status.siret,
                        "siren": status.siren,
                        "legal_unit_restricted": (status.legal_unit_diffusion_status == "PARTIAL"),
                    }
                )
                continue
            payload = _payload(status)
            records.append(
                {
                    "siret": status.siret,
                    "siren": status.siren,
                    "establishment_state": status.establishment_administrative_state,
                    "legal_unit_state": status.legal_unit_administrative_state,
                    "establishment_diffusion": status.establishment_diffusion_status,
                    "legal_unit_diffusion": status.legal_unit_diffusion_status,
                    "outcome": _status_outcome(status),
                    "observation_id": str(uuid4()),
                    "content_fingerprint": _fingerprint(payload),
                    "payload": payload,
                }
            )
        return records, restricted_records

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
            raise SireneKnownStatusError(
                "known Sirene establishment checks require the active collection attempt"
            )

    @staticmethod
    def _require_projection_complete(
        connection: Connection,
        reservation: ReservedCollection,
    ) -> None:
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
        if (evidence["api_count"], evidence["file_count"], evidence["geocoder_count"]) != (
            1,
            1,
            1,
        ):
            raise SireneKnownStatusError(
                "known Sirene establishment checks require all projected sources"
            )
        pending_projection_count = connection.execute(
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
                  AND item.decision IS NULL
                """
            ),
            {"cycle_id": reservation.cycle_id},
        ).scalar_one()
        if pending_projection_count:
            raise SireneKnownStatusError(
                "known Sirene establishment checks require completed prospect projection"
            )

    @staticmethod
    def _ensure_source_run(
        connection: Connection,
        reservation: ReservedCollection,
        now: datetime,
    ) -> None:
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
                    finished_at,
                    status,
                    counters,
                    metadata,
                    request_count,
                    retry_count,
                    error_count,
                    contract_version,
                    created_at,
                    updated_at
                )
                VALUES (
                    gen_random_uuid(),
                    :cycle_id,
                    :source,
                    NULL,
                    NULL,
                    :now,
                    NULL,
                    'RUNNING',
                    '{}'::jsonb,
                    '{}'::jsonb,
                    0,
                    0,
                    0,
                    :contract_version,
                    :now,
                    :now
                )
                ON CONFLICT (collection_cycle_id, source) DO NOTHING
                """
            ),
            {
                "cycle_id": reservation.cycle_id,
                "source": _SOURCE,
                "contract_version": _CONTRACT_VERSION,
                "now": now,
            },
        )

    @staticmethod
    def _source_state(
        connection: Connection,
        reservation: ReservedCollection,
    ) -> RowMapping:
        row = (
            connection.execute(
                text(
                    """
                    SELECT status, counters
                    FROM collection_source_run
                    WHERE collection_cycle_id = :cycle_id
                      AND source = :source
                    """
                ),
                {"cycle_id": reservation.cycle_id, "source": _SOURCE},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise SireneKnownStatusError("the Sirene known-status source does not exist")
        return row

    @staticmethod
    def _require_running_source(
        connection: Connection,
        reservation: ReservedCollection,
    ) -> None:
        status = SqlAlchemySireneKnownStatusRepository._source_state(
            connection,
            reservation,
        )["status"]
        if status != "RUNNING":
            raise SireneKnownStatusError("the Sirene known-status source is not running")

    @staticmethod
    def _query_date(connection: Connection, reservation: ReservedCollection) -> str:
        value = connection.execute(
            text(
                """
                SELECT to_char(
                    requested_at AT TIME ZONE schedule_timezone,
                    'YYYY-MM-DD'
                )
                FROM collection_cycle
                WHERE id = :cycle_id
                """
            ),
            {"cycle_id": reservation.cycle_id},
        ).scalar_one_or_none()
        if not isinstance(value, str):
            raise SireneKnownStatusError("the Sirene known-status query date is missing")
        return value

    @staticmethod
    def _completed_count(connection: Connection, reservation: ReservedCollection) -> int:
        value = connection.execute(
            text(
                """
                SELECT
                    (SELECT count(*)
                     FROM sirene_known_status_check
                     WHERE collection_cycle_id = :cycle_id)
                    + COALESCE(
                        (SELECT CAST(counters ->> 'restricted_count' AS integer)
                         FROM collection_source_run
                         WHERE collection_cycle_id = :cycle_id
                           AND source = :source),
                        0
                    )
                """
            ),
            {"cycle_id": reservation.cycle_id, "source": _SOURCE},
        ).scalar_one()
        if not isinstance(value, int):
            raise SireneKnownStatusError("the Sirene known-status count is invalid")
        return value

    @staticmethod
    def _pending_sirets(
        connection: Connection,
        reservation: ReservedCollection,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            text(
                """
                SELECT identity.canonical_value
                FROM source_binding AS binding
                JOIN external_identity AS identity
                  ON identity.id = binding.external_identity_id
                 AND identity.authority = 'INSEE'
                 AND identity.namespace = 'SIRET'
                 AND identity.restricted_at IS NULL
                JOIN prospect ON prospect.id = binding.opportunity_id
                JOIN location_assertion AS location
                  ON location.opportunity_id = prospect.id
                 AND location.layer = 'SOURCE'
                 AND location.is_current
                JOIN collection_cycle_commune AS commune
                  ON commune.collection_cycle_id = :cycle_id
                 AND commune.municipality_code = location.municipality_code
                LEFT JOIN source_sighting AS sighting
                  ON sighting.source_binding_id = binding.id
                 AND sighting.collection_cycle_id = :cycle_id
                LEFT JOIN sirene_known_status_check AS checked
                  ON checked.source_binding_id = binding.id
                 AND checked.collection_cycle_id = :cycle_id
                WHERE binding.data_source_code = :data_source
                  AND identity.canonical_value ~ '^[0-9]{14}$'
                  AND sighting.source_binding_id IS NULL
                  AND checked.id IS NULL
                ORDER BY identity.canonical_value
                """
            ),
            {"cycle_id": reservation.cycle_id, "data_source": _DATA_SOURCE},
        ).scalars()
        return tuple(value for value in rows if isinstance(value, str))

    @staticmethod
    def _create_input(connection: Connection, parameters: dict[str, object]) -> None:
        connection.execute(
            text(
                f"""
                CREATE TEMPORARY TABLE sirene_known_status_input ON COMMIT DROP AS
                SELECT
                    input.*,
                    identity.id AS external_identity_id,
                    binding.id AS source_binding_id,
                    binding.opportunity_id,
                    establishment.id AS establishment_id,
                    establishment.organization_id
                FROM {_INPUT_RECORDSET}
                JOIN external_identity AS identity
                  ON identity.authority = 'INSEE'
                 AND identity.namespace = 'SIRET'
                 AND identity.canonical_value = input.siret
                 AND identity.restricted_at IS NULL
                JOIN source_binding AS binding
                  ON binding.external_identity_id = identity.id
                 AND binding.data_source_code = :data_source
                JOIN prospect ON prospect.id = binding.opportunity_id
                JOIN establishment ON establishment.id = prospect.establishment_id
                JOIN location_assertion AS location
                  ON location.opportunity_id = prospect.id
                 AND location.layer = 'SOURCE'
                 AND location.is_current
                JOIN collection_cycle_commune AS commune
                  ON commune.collection_cycle_id = :cycle_id
                 AND commune.municipality_code = location.municipality_code
                LEFT JOIN source_sighting AS sighting
                  ON sighting.source_binding_id = binding.id
                 AND sighting.collection_cycle_id = :cycle_id
                LEFT JOIN sirene_known_status_check AS checked
                  ON checked.source_binding_id = binding.id
                 AND checked.collection_cycle_id = :cycle_id
                WHERE sighting.source_binding_id IS NULL
                  AND checked.id IS NULL
                """
            ),
            parameters,
        )

    @staticmethod
    def _create_restricted_targets(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                f"""
                CREATE TEMPORARY TABLE sirene_restricted_input ON COMMIT DROP AS
                SELECT
                    input.*,
                    identity.id AS external_identity_id,
                    binding.id AS source_binding_id,
                    binding.opportunity_id,
                    establishment.id AS establishment_id,
                    establishment.organization_id
                FROM {_RESTRICTED_RECORDSET}
                JOIN external_identity AS identity
                  ON identity.authority = 'INSEE'
                 AND identity.namespace = 'SIRET'
                 AND identity.canonical_value = input.siret
                 AND identity.restricted_at IS NULL
                JOIN source_binding AS binding
                  ON binding.external_identity_id = identity.id
                 AND binding.data_source_code = :data_source
                JOIN prospect ON prospect.id = binding.opportunity_id
                JOIN establishment ON establishment.id = prospect.establishment_id
                 AND establishment.siret = input.siret
                 AND left(establishment.siret, 9) = input.siren
                JOIN location_assertion AS location
                  ON location.opportunity_id = prospect.id
                 AND location.layer = 'SOURCE'
                 AND location.is_current
                JOIN collection_cycle_commune AS commune
                  ON commune.collection_cycle_id = :cycle_id
                 AND commune.municipality_code = location.municipality_code
                LEFT JOIN source_sighting AS sighting
                  ON sighting.source_binding_id = binding.id
                 AND sighting.collection_cycle_id = :cycle_id
                LEFT JOIN sirene_known_status_check AS checked
                  ON checked.source_binding_id = binding.id
                 AND checked.collection_cycle_id = :cycle_id
                WHERE sighting.source_binding_id IS NULL
                  AND checked.id IS NULL
                """
            ),
            parameters,
        )
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_restricted_organizations
                ON COMMIT DROP AS
                SELECT DISTINCT organization_id
                FROM sirene_restricted_input
                WHERE legal_unit_restricted
                  AND organization_id IS NOT NULL
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_restricted_establishments
                ON COMMIT DROP AS
                SELECT DISTINCT establishment_id
                FROM sirene_restricted_input
                UNION
                SELECT establishment.id
                FROM establishment
                JOIN sirene_restricted_organizations AS restricted
                  ON restricted.organization_id = establishment.organization_id
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_restricted_opportunities
                ON COMMIT DROP AS
                SELECT prospect.id AS opportunity_id
                FROM prospect
                JOIN sirene_restricted_establishments AS restricted
                  ON restricted.establishment_id = prospect.establishment_id
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_restricted_bindings
                ON COMMIT DROP AS
                SELECT binding.id AS source_binding_id
                FROM source_binding AS binding
                JOIN sirene_restricted_opportunities AS restricted
                  ON restricted.opportunity_id = binding.opportunity_id
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_restricted_identities
                ON COMMIT DROP AS
                SELECT DISTINCT identity.id AS external_identity_id
                FROM external_identity AS identity
                WHERE identity.id IN (
                    SELECT external_identity_id FROM sirene_restricted_input
                )
                   OR identity.organization_id IN (
                    SELECT organization_id FROM sirene_restricted_organizations
                )
                   OR identity.establishment_id IN (
                    SELECT establishment_id FROM sirene_restricted_establishments
                )
                   OR identity.opportunity_id IN (
                    SELECT opportunity_id FROM sirene_restricted_opportunities
                )
                   OR identity.id IN (
                    SELECT binding.external_identity_id
                    FROM source_binding AS binding
                    JOIN sirene_restricted_bindings AS restricted
                      ON restricted.source_binding_id = binding.id
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_restricted_items
                ON COMMIT DROP AS
                SELECT DISTINCT item.id AS collection_item_id
                FROM collection_item AS item
                WHERE item.external_identity_id IN (
                    SELECT external_identity_id FROM sirene_restricted_identities
                )
                   OR item.opportunity_id IN (
                    SELECT opportunity_id FROM sirene_restricted_opportunities
                )
                   OR (
                    item.authority = 'INSEE'
                    AND item.namespace = 'SIRET'
                    AND item.identifier_value IN (
                        SELECT establishment.siret
                        FROM establishment
                        JOIN sirene_restricted_establishments AS restricted
                          ON restricted.establishment_id = establishment.id
                    )
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TEMPORARY TABLE sirene_restricted_observations
                ON COMMIT DROP AS
                SELECT DISTINCT observation_id AS source_observation_id
                FROM (
                    SELECT observation.id AS observation_id
                    FROM source_observation AS observation
                    WHERE observation.external_identity_id IN (
                        SELECT external_identity_id FROM sirene_restricted_identities
                    )
                       OR observation.source_binding_id IN (
                        SELECT source_binding_id FROM sirene_restricted_bindings
                    )
                    UNION ALL
                    SELECT organization.current_observation_id
                    FROM organization
                    WHERE organization.id IN (
                        SELECT organization_id FROM sirene_restricted_organizations
                    )
                    UNION ALL
                    SELECT organization.administrative_state_observation_id
                    FROM organization
                    WHERE organization.id IN (
                        SELECT organization_id FROM sirene_restricted_organizations
                    )
                    UNION ALL
                    SELECT organization.diffusion_status_observation_id
                    FROM organization
                    WHERE organization.id IN (
                        SELECT organization_id FROM sirene_restricted_organizations
                    )
                    UNION ALL
                    SELECT establishment.current_observation_id
                    FROM establishment
                    WHERE establishment.id IN (
                        SELECT establishment_id FROM sirene_restricted_establishments
                    )
                    UNION ALL
                    SELECT establishment.administrative_state_observation_id
                    FROM establishment
                    WHERE establishment.id IN (
                        SELECT establishment_id FROM sirene_restricted_establishments
                    )
                    UNION ALL
                    SELECT establishment.diffusion_status_observation_id
                    FROM establishment
                    WHERE establishment.id IN (
                        SELECT establishment_id FROM sirene_restricted_establishments
                    )
                    UNION ALL
                    SELECT binding.current_observation_id
                    FROM source_binding AS binding
                    WHERE binding.id IN (
                        SELECT source_binding_id FROM sirene_restricted_bindings
                    )
                    UNION ALL
                    SELECT item.source_observation_id
                    FROM collection_item AS item
                    WHERE item.id IN (
                        SELECT collection_item_id FROM sirene_restricted_items
                    )
                    UNION ALL
                    SELECT position.source_observation_id
                    FROM candidate_position AS position
                    WHERE position.collection_item_id IN (
                        SELECT collection_item_id FROM sirene_restricted_items
                    )
                    UNION ALL
                    SELECT location.address_observation_id
                    FROM location_assertion AS location
                    WHERE location.opportunity_id IN (
                        SELECT opportunity_id FROM sirene_restricted_opportunities
                    )
                    UNION ALL
                    SELECT location.position_observation_id
                    FROM location_assertion AS location
                    WHERE location.opportunity_id IN (
                        SELECT opportunity_id FROM sirene_restricted_opportunities
                    )
                    UNION ALL
                    SELECT contact.source_observation_id
                    FROM contact_set AS contact
                    WHERE contact.opportunity_id IN (
                        SELECT opportunity_id FROM sirene_restricted_opportunities
                    )
                    UNION ALL
                    SELECT lineage.source_observation_id
                    FROM field_lineage AS lineage
                    WHERE lineage.opportunity_id IN (
                        SELECT opportunity_id FROM sirene_restricted_opportunities
                    )
                ) AS referenced
                WHERE observation_id IS NOT NULL
                """
            )
        )

    @staticmethod
    def _purge_restricted_targets(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        if parameters["restricted_count"] == 0:
            return
        connection.execute(
            text(
                """
                UPDATE source_observation
                SET source_binding_id = NULL
                WHERE source_binding_id IN (
                    SELECT source_binding_id FROM sirene_restricted_bindings
                )
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM candidate_position
                WHERE collection_item_id IN (
                    SELECT collection_item_id FROM sirene_restricted_items
                )
                   OR source_observation_id IN (
                    SELECT source_observation_id FROM sirene_restricted_observations
                )
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE collection_item
                SET
                    identifier_value = NULL,
                    identifier_fingerprint = NULL,
                    external_identity_id = NULL,
                    source_observation_id = NULL,
                    opportunity_id = NULL,
                    geographic_classification = 'NOT_APPLICABLE',
                    distance_meters = NULL,
                    decision = 'REJECTED',
                    reason = '{"code":"SOURCE_PARTIAL_DIFFUSION_PURGED"}'::jsonb,
                    updated_at = :now
                WHERE id IN (
                    SELECT collection_item_id FROM sirene_restricted_items
                )
                """
            ),
            parameters,
        )
        connection.execute(
            text(
                """
                UPDATE opportunity
                SET duplicate_of_opportunity_id = NULL, updated_at = :now
                WHERE duplicate_of_opportunity_id IN (
                    SELECT opportunity_id FROM sirene_restricted_opportunities
                )
                """
            ),
            parameters,
        )
        connection.execute(
            text(
                """
                UPDATE external_identity
                SET organization_id = NULL, establishment_id = NULL, opportunity_id = NULL
                WHERE id IN (
                    SELECT external_identity_id FROM sirene_restricted_identities
                )
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM opportunity
                WHERE id IN (
                    SELECT opportunity_id FROM sirene_restricted_opportunities
                )
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE organization
                SET
                    current_observation_id = CASE
                        WHEN current_observation_id IN (
                            SELECT source_observation_id
                            FROM sirene_restricted_observations
                        ) THEN NULL ELSE current_observation_id END,
                    administrative_state_observation_id = CASE
                        WHEN administrative_state_observation_id IN (
                            SELECT source_observation_id
                            FROM sirene_restricted_observations
                        ) THEN NULL ELSE administrative_state_observation_id END,
                    diffusion_status_observation_id = CASE
                        WHEN diffusion_status_observation_id IN (
                            SELECT source_observation_id
                            FROM sirene_restricted_observations
                        ) THEN NULL ELSE diffusion_status_observation_id END
                WHERE current_observation_id IN (
                        SELECT source_observation_id FROM sirene_restricted_observations
                    )
                   OR administrative_state_observation_id IN (
                        SELECT source_observation_id FROM sirene_restricted_observations
                    )
                   OR diffusion_status_observation_id IN (
                        SELECT source_observation_id FROM sirene_restricted_observations
                    )
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE establishment
                SET
                    current_observation_id = CASE
                        WHEN current_observation_id IN (
                            SELECT source_observation_id
                            FROM sirene_restricted_observations
                        ) THEN NULL ELSE current_observation_id END,
                    administrative_state_observation_id = CASE
                        WHEN administrative_state_observation_id IN (
                            SELECT source_observation_id
                            FROM sirene_restricted_observations
                        ) THEN NULL ELSE administrative_state_observation_id END,
                    diffusion_status_observation_id = CASE
                        WHEN diffusion_status_observation_id IN (
                            SELECT source_observation_id
                            FROM sirene_restricted_observations
                        ) THEN NULL ELSE diffusion_status_observation_id END
                WHERE current_observation_id IN (
                        SELECT source_observation_id FROM sirene_restricted_observations
                    )
                   OR administrative_state_observation_id IN (
                        SELECT source_observation_id FROM sirene_restricted_observations
                    )
                   OR diffusion_status_observation_id IN (
                        SELECT source_observation_id FROM sirene_restricted_observations
                    )
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM establishment
                WHERE id IN (
                    SELECT establishment_id FROM sirene_restricted_establishments
                )
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM organization AS organization
                WHERE (
                    organization.id IN (
                        SELECT organization_id FROM sirene_restricted_organizations
                    )
                    OR organization.id IN (
                        SELECT input.organization_id FROM sirene_restricted_input AS input
                    )
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM establishment
                    WHERE establishment.organization_id = organization.id
                )
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM source_observation
                WHERE id IN (
                    SELECT source_observation_id FROM sirene_restricted_observations
                )
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM external_identity
                WHERE id IN (
                    SELECT external_identity_id FROM sirene_restricted_identities
                )
                """
            )
        )

    @staticmethod
    def _insert_observations(connection: Connection, parameters: dict[str, object]) -> None:
        connection.execute(
            text(
                """
                INSERT INTO source_observation (
                    id,
                    data_source_code,
                    external_identity_id,
                    source_binding_id,
                    collection_cycle_id,
                    retrieved_at,
                    adapter_version,
                    schema_version,
                    content_fingerprint,
                    payload,
                    validation_status
                )
                SELECT
                    observation_id,
                    :data_source,
                    external_identity_id,
                    source_binding_id,
                    :cycle_id,
                    :now,
                    :adapter_version,
                    :schema_version,
                    content_fingerprint,
                    payload,
                    'VALID'
                FROM sirene_known_status_input
                WHERE outcome <> 'NOT_FOUND'
                ON CONFLICT (data_source_code, external_identity_id, content_fingerprint)
                DO NOTHING
                """
            ),
            parameters,
        )

    @staticmethod
    def _insert_checks(connection: Connection, parameters: dict[str, object]) -> None:
        connection.execute(
            text(
                """
                INSERT INTO sirene_known_status_check (
                    id,
                    collection_cycle_id,
                    source_binding_id,
                    external_identity_id,
                    source_observation_id,
                    outcome,
                    checked_at
                )
                SELECT
                    gen_random_uuid(),
                    :cycle_id,
                    input.source_binding_id,
                    input.external_identity_id,
                    observation.id,
                    input.outcome,
                    :now
                FROM sirene_known_status_input AS input
                LEFT JOIN source_observation AS observation
                  ON observation.data_source_code = :data_source
                 AND observation.external_identity_id = input.external_identity_id
                 AND observation.content_fingerprint = input.content_fingerprint
                WHERE input.outcome = 'NOT_FOUND' OR observation.id IS NOT NULL
                ON CONFLICT (collection_cycle_id, source_binding_id) DO NOTHING
                """
            ),
            parameters,
        )
        count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM sirene_known_status_check AS checked
                JOIN sirene_known_status_input AS input
                  ON input.source_binding_id = checked.source_binding_id
                WHERE checked.collection_cycle_id = :cycle_id
                """
            ),
            parameters,
        ).scalar_one()
        input_count = connection.execute(
            text("SELECT count(*) FROM sirene_known_status_input")
        ).scalar_one()
        if count != input_count:
            raise SireneKnownStatusError("targeted Sirene checks were not persisted completely")

    @staticmethod
    def _apply_organization_states(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                WITH state AS (
                    SELECT DISTINCT ON (input.organization_id)
                        input.organization_id,
                        input.legal_unit_state,
                        observation.id AS observation_id
                    FROM sirene_known_status_input AS input
                    JOIN source_observation AS observation
                      ON observation.data_source_code = :data_source
                     AND observation.external_identity_id = input.external_identity_id
                     AND observation.content_fingerprint = input.content_fingerprint
                    WHERE input.outcome <> 'NOT_FOUND'
                    ORDER BY input.organization_id, input.siret
                )
                UPDATE organization
                SET
                    administrative_state = state.legal_unit_state,
                    diffusion_status = 'FULL',
                    administrative_state_observation_id = state.observation_id,
                    diffusion_status_observation_id = state.observation_id,
                    last_observed_at = GREATEST(organization.last_observed_at, :now),
                    updated_at = :now
                FROM state
                WHERE organization.id = state.organization_id
                """
            ),
            parameters,
        )

    @staticmethod
    def _apply_establishment_states(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                UPDATE establishment
                SET
                    administrative_state = input.establishment_state,
                    diffusion_status = 'FULL',
                    administrative_state_observation_id = observation.id,
                    diffusion_status_observation_id = observation.id,
                    last_observed_at = GREATEST(establishment.last_observed_at, :now),
                    updated_at = :now
                FROM sirene_known_status_input AS input
                JOIN source_observation AS observation
                  ON observation.data_source_code = :data_source
                 AND observation.external_identity_id = input.external_identity_id
                 AND observation.content_fingerprint = input.content_fingerprint
                WHERE establishment.id = input.establishment_id
                  AND input.outcome <> 'NOT_FOUND'
                """
            ),
            parameters,
        )

    @staticmethod
    def _reactivate_eligible_prospects(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                UPDATE prospect
                SET
                    eligibility = 'ELIGIBLE',
                    eligibility_changed_at = CASE
                        WHEN prospect.eligibility <> 'ELIGIBLE'
                          OR prospect.eligibility_reason
                                <> 'SIRENE_TARGETED_ACTIVE_FULL'
                        THEN :now
                        ELSE prospect.eligibility_changed_at
                    END,
                    eligibility_reason = 'SIRENE_TARGETED_ACTIVE_FULL',
                    last_observed_at = GREATEST(prospect.last_observed_at, :now),
                    updated_at = :now
                FROM sirene_known_status_input AS input
                WHERE prospect.id = input.opportunity_id
                  AND input.outcome = 'ACTIVE'
                """
            ),
            parameters,
        )

    @staticmethod
    def _touch_changed_opportunities(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        connection.execute(
            text(
                """
                UPDATE opportunity
                SET updated_at = :now
                FROM sirene_known_status_input AS input
                WHERE opportunity.id = input.opportunity_id
                  AND input.outcome <> 'NOT_FOUND'
                """
            ),
            parameters,
        )

    @staticmethod
    def _insert_sightings(connection: Connection, parameters: dict[str, object]) -> None:
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
                    input.source_binding_id,
                    :cycle_id,
                    observation.id,
                    :now
                FROM sirene_known_status_input AS input
                JOIN source_observation AS observation
                  ON observation.data_source_code = :data_source
                 AND observation.external_identity_id = input.external_identity_id
                 AND observation.content_fingerprint = input.content_fingerprint
                WHERE input.outcome <> 'NOT_FOUND'
                ON CONFLICT (source_binding_id, collection_cycle_id) DO UPDATE SET
                    source_observation_id = EXCLUDED.source_observation_id,
                    seen_at = EXCLUDED.seen_at
                """
            ),
            parameters,
        )

    @staticmethod
    def _update_bindings(connection: Connection, parameters: dict[str, object]) -> None:
        connection.execute(
            text(
                """
                UPDATE source_binding AS binding
                SET
                    state = CASE
                        WHEN input.outcome = 'NOT_FOUND' THEN binding.state
                        ELSE 'CURRENT'
                    END,
                    consecutive_absence_count = CASE
                        WHEN input.outcome = 'NOT_FOUND'
                        THEN binding.consecutive_absence_count + 1
                        ELSE 0
                    END,
                    last_checked_at = :now,
                    last_observed_at = CASE
                        WHEN input.outcome = 'NOT_FOUND' THEN binding.last_observed_at
                        ELSE GREATEST(binding.last_observed_at, :now)
                    END,
                    updated_at = :now
                FROM sirene_known_status_input AS input
                WHERE binding.id = input.source_binding_id
                """
            ),
            parameters,
        )

    @staticmethod
    def _increment_request_count(
        connection: Connection,
        parameters: dict[str, object],
    ) -> None:
        updated = connection.execute(
            text(
                """
                UPDATE collection_source_run
                SET
                    request_count = request_count + 1,
                    counters = jsonb_set(
                        counters,
                        '{restricted_count}',
                        to_jsonb(
                            COALESCE(
                                CAST(counters ->> 'restricted_count' AS integer),
                                0
                            ) + CAST(:restricted_count AS integer)
                        ),
                        TRUE
                    ),
                    metadata = metadata - 'last_error_code',
                    updated_at = :now
                WHERE collection_cycle_id = :cycle_id
                  AND source = :source
                  AND status = 'RUNNING'
                RETURNING id
                """
            ),
            {**parameters, "source": _SOURCE},
        ).scalar_one_or_none()
        if updated is None:
            raise SireneKnownStatusError(
                "the Sirene known-status request counter cannot be updated"
            )

    @staticmethod
    def _summary(
        connection: Connection,
        reservation: ReservedCollection,
    ) -> SireneKnownStatusSummary:
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(checked.id) + COALESCE(
                            CAST(source.counters ->> 'restricted_count' AS integer),
                            0
                        ) AS checked_count,
                        count(*) FILTER (WHERE outcome = 'ACTIVE') AS active_count,
                        count(*) FILTER (WHERE outcome = 'CLOSED') AS closed_count,
                        count(*) FILTER (WHERE outcome = 'CEASED') AS ceased_count,
                        COALESCE(
                            CAST(source.counters ->> 'restricted_count' AS integer),
                            0
                        ) AS restricted_count,
                        count(*) FILTER (WHERE outcome = 'NOT_FOUND') AS not_found_count
                    FROM collection_source_run AS source
                    LEFT JOIN sirene_known_status_check AS checked
                      ON checked.collection_cycle_id = source.collection_cycle_id
                    WHERE source.collection_cycle_id = :cycle_id
                      AND source.source = :source
                    GROUP BY source.counters
                    """
                ),
                {"cycle_id": reservation.cycle_id, "source": _SOURCE},
            )
            .mappings()
            .one()
        )
        values = (
            row["checked_count"],
            row["active_count"],
            row["closed_count"],
            row["ceased_count"],
            row["restricted_count"],
            row["not_found_count"],
        )
        if any(not isinstance(value, int) for value in values):
            raise SireneKnownStatusError("Sirene known-status counters have unexpected types")
        summary = SireneKnownStatusSummary(*values)
        summary.validate()
        return summary
