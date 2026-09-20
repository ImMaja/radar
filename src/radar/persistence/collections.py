"""PostgreSQL durable queue and collection-history persistence."""

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, bindparam, text

from radar.collections.contracts import (
    CollectionDashboard,
    CollectionError,
    CollectionFinalResult,
    CollectionJob,
    CollectionJobState,
    CollectionLeaseLostError,
    CollectionProgress,
    CollectionTrigger,
    Connector,
    ConnectorCollectionStatus,
    ConnectorCoverage,
    ConnectorSpecification,
    EnqueuedCollection,
    JsonObject,
    ReferencePositionRequiredError,
    ReservedCollection,
)

ACTIVE_STATES = ("WAITING", "RUNNING", "WAITING_RETRY")
CONNECTORS: tuple[Connector, ...] = ("SIRENE", "DATATOURISME")

_JOB_COLUMNS = """
    job.id,
    job.cycle_id,
    job.connector,
    job.trigger,
    job.state,
    reference.normalized_label AS reference_label,
    ST_X(cycle.center::geometry) AS longitude,
    ST_Y(cycle.center::geometry) AS latitude,
    cycle.collection_radius_meters,
    job.created_at,
    job.available_at,
    job.started_at,
    job.finished_at,
    job.heartbeat_at,
    job.attempt_count,
    job.max_attempts,
    job.progress,
    job.last_error
"""


def _json_object(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _progress(value: object) -> CollectionProgress:
    data = _json_object(value)
    stage = data.get("stage")
    processed = _optional_int(data.get("processed"))
    observations = _optional_int(data.get("observations"))
    return CollectionProgress(
        stage=stage if isinstance(stage, str) else "unknown",
        processed=processed if processed is not None else 0,
        total=_optional_int(data.get("total")),
        observations=observations if observations is not None else 0,
    )


def _error(value: object) -> CollectionError | None:
    if value is None:
        return None
    data = _json_object(value)
    code = data.get("code")
    message = data.get("message")
    transient = data.get("transient")
    if not isinstance(code, str) or not isinstance(message, str) or not isinstance(transient, bool):
        return None
    return CollectionError(code, message, transient)


def _job_from_row(row: RowMapping) -> CollectionJob:
    return CollectionJob(
        id=cast(UUID, row["id"]),
        cycle_id=cast(UUID, row["cycle_id"]),
        connector=cast(Connector, row["connector"]),
        trigger=cast(CollectionTrigger, row["trigger"]),
        state=cast(CollectionJobState, row["state"]),
        reference_label=cast(str, row["reference_label"]),
        longitude=cast(float, row["longitude"]),
        latitude=cast(float, row["latitude"]),
        collection_radius_meters=cast(int, row["collection_radius_meters"]),
        created_at=cast(datetime, row["created_at"]),
        available_at=cast(datetime, row["available_at"]),
        started_at=cast(datetime | None, row["started_at"]),
        finished_at=cast(datetime | None, row["finished_at"]),
        heartbeat_at=cast(datetime | None, row["heartbeat_at"]),
        attempt_count=cast(int, row["attempt_count"]),
        max_attempts=cast(int, row["max_attempts"]),
        progress=_progress(row["progress"]),
        last_error=_error(row["last_error"]),
    )


def _canonical_fingerprint(payload: Mapping[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _terminal_progress(result: CollectionFinalResult, counters: JsonObject) -> JsonObject:
    observations = _optional_int(counters.get("observations")) or 0
    processed = _optional_int(counters.get("processed"))
    total = _optional_int(counters.get("total"))
    progress: JsonObject = {
        "stage": result.lower(),
        "processed": processed if processed is not None else observations,
        "observations": observations,
    }
    if total is not None:
        progress["total"] = total
    return progress


class SqlAlchemyCollectionRepository:
    """Own queue reservation, leases and terminal collection transactions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def enqueue(
        self,
        connector: Connector,
        trigger: CollectionTrigger,
        specification: ConnectorSpecification,
        now: datetime,
        scheduled_for: datetime | None = None,
    ) -> EnqueuedCollection:
        """Capture current geography and idempotently create a cycle and job."""

        with self._engine.begin() as connection:
            zone = (
                connection.execute(
                    text(
                        """
                        SELECT
                            reference.id AS reference_position_id,
                            reference.point,
                            ST_X(reference.point::geometry) AS longitude,
                            ST_Y(reference.point::geometry) AS latitude,
                            settings.collection_radius_meters
                        FROM application_setting AS settings
                        LEFT JOIN reference_position AS reference
                            ON reference.id = settings.current_reference_position_id
                        WHERE settings.singleton_key = 'primary'
                        FOR UPDATE OF settings
                        """
                    )
                )
                .mappings()
                .one()
            )
            reference_position_id = zone["reference_position_id"]
            if reference_position_id is None:
                raise ReferencePositionRequiredError("a confirmed reference position is required")

            fingerprint = _canonical_fingerprint(
                {
                    "connector": connector,
                    "longitude": round(cast(float, zone["longitude"]), 8),
                    "latitude": round(cast(float, zone["latitude"]), 8),
                    "radius": cast(int, zone["collection_radius_meters"]),
                    "adapter_version": specification.adapter_version,
                    "configuration": specification.configuration_fingerprint,
                }
            )
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:fingerprint, 0))"),
                {"fingerprint": fingerprint},
            )

            existing = self._find_existing(
                connection,
                connector,
                fingerprint,
                scheduled_for,
            )
            if existing is not None:
                return EnqueuedCollection(existing, created=False)

            cycle_id = uuid4()
            job_id = uuid4()
            connection.execute(
                text(
                    """
                    INSERT INTO collection_cycle (
                        id,
                        connector,
                        trigger,
                        result,
                        adapter_version,
                        configuration_fingerprint,
                        reference_position_id,
                        center,
                        collection_radius_meters,
                        schedule_timezone,
                        requested_at,
                        counters,
                        request_fingerprint
                    ) VALUES (
                        :id,
                        :connector,
                        :trigger,
                        NULL,
                        :adapter_version,
                        :configuration_fingerprint,
                        :reference_position_id,
                        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                        :collection_radius_meters,
                        'Europe/Paris',
                        :requested_at,
                        '{}'::jsonb,
                        :request_fingerprint
                    )
                    """
                ),
                {
                    "id": cycle_id,
                    "connector": connector,
                    "trigger": trigger,
                    "adapter_version": specification.adapter_version,
                    "configuration_fingerprint": specification.configuration_fingerprint,
                    "reference_position_id": reference_position_id,
                    "longitude": zone["longitude"],
                    "latitude": zone["latitude"],
                    "collection_radius_meters": zone["collection_radius_meters"],
                    "requested_at": now,
                    "request_fingerprint": fingerprint,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO collection_job (
                        id,
                        cycle_id,
                        connector,
                        trigger,
                        scheduled_for,
                        state,
                        created_at,
                        available_at,
                        attempt_count,
                        max_attempts,
                        progress,
                        request_fingerprint
                    ) VALUES (
                        :id,
                        :cycle_id,
                        :connector,
                        :trigger,
                        :scheduled_for,
                        'WAITING',
                        :created_at,
                        :available_at,
                        0,
                        3,
                        CAST(:progress AS jsonb),
                        :request_fingerprint
                    )
                    """
                ),
                {
                    "id": job_id,
                    "cycle_id": cycle_id,
                    "connector": connector,
                    "trigger": trigger,
                    "scheduled_for": scheduled_for,
                    "created_at": now,
                    "available_at": now,
                    "progress": json.dumps(CollectionProgress("waiting").as_dict()),
                    "request_fingerprint": fingerprint,
                },
            )
            return EnqueuedCollection(self._load_job(connection, job_id), created=True)

    def dashboard(self) -> CollectionDashboard:
        """Return active/latest jobs and last complete success per connector."""

        with self._engine.connect() as connection:
            latest_rows = (
                connection.execute(
                    text(
                        f"""
                        SELECT DISTINCT ON (job.connector) {_JOB_COLUMNS}
                        FROM collection_job AS job
                        JOIN collection_cycle AS cycle ON cycle.id = job.cycle_id
                        JOIN reference_position AS reference
                            ON reference.id = cycle.reference_position_id
                        ORDER BY job.connector, job.created_at DESC, job.id DESC
                        """
                    )
                )
                .mappings()
                .all()
            )
            active_rows = (
                connection.execute(
                    text(
                        f"""
                        SELECT DISTINCT ON (job.connector) {_JOB_COLUMNS}
                        FROM collection_job AS job
                        JOIN collection_cycle AS cycle ON cycle.id = job.cycle_id
                        JOIN reference_position AS reference
                            ON reference.id = cycle.reference_position_id
                        WHERE job.state IN ('WAITING', 'RUNNING', 'WAITING_RETRY')
                        ORDER BY job.connector, job.created_at DESC, job.id DESC
                        """
                    )
                )
                .mappings()
                .all()
            )
            successes = {
                cast(Connector, row.connector): cast(datetime, row.finished_at)
                for row in connection.execute(
                    text(
                        """
                        SELECT connector, max(finished_at) AS finished_at
                        FROM collection_job
                        WHERE state = 'SUCCEEDED'
                        GROUP BY connector
                        """
                    )
                )
                if row.finished_at is not None
            }
            coverage_rows = connection.execute(
                text(
                    """
                    SELECT DISTINCT ON (coverage.connector)
                        coverage.connector,
                        coverage.established_at,
                        ST_X(coverage.center::geometry) AS longitude,
                        ST_Y(coverage.center::geometry) AS latitude,
                        coverage.collection_radius_meters,
                        CASE
                            WHEN reference.point IS NULL THEN FALSE
                            ELSE ST_Distance(coverage.center, reference.point)
                                + settings.search_radius_meters
                                <= coverage.collection_radius_meters
                        END AS search_circle_covered
                    FROM connector_coverage AS coverage
                    CROSS JOIN application_setting AS settings
                    LEFT JOIN reference_position AS reference
                        ON reference.id = settings.current_reference_position_id
                    WHERE settings.singleton_key = 'primary'
                    ORDER BY coverage.connector, coverage.established_at DESC, coverage.id DESC
                    """
                )
            ).mappings()
            coverages = {
                cast(Connector, row["connector"]): ConnectorCoverage(
                    established_at=cast(datetime, row["established_at"]),
                    longitude=cast(float, row["longitude"]),
                    latitude=cast(float, row["latitude"]),
                    collection_radius_meters=cast(int, row["collection_radius_meters"]),
                    search_circle_covered=cast(bool, row["search_circle_covered"]),
                )
                for row in coverage_rows
            }

        latest_jobs = {job.connector: job for job in (_job_from_row(row) for row in latest_rows)}
        active_jobs = {job.connector: job for job in (_job_from_row(row) for row in active_rows)}
        statuses: list[ConnectorCollectionStatus] = []
        for connector in CONNECTORS:
            statuses.append(
                ConnectorCollectionStatus(
                    connector=connector,
                    available=True,
                    active_job=active_jobs.get(connector),
                    latest_job=latest_jobs.get(connector),
                    last_success_at=successes.get(connector),
                    coverage=coverages.get(connector),
                )
            )
        return CollectionDashboard(tuple(statuses))

    def reserve_next(
        self,
        worker_id: str,
        connectors: tuple[Connector, ...],
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReservedCollection | None:
        """Lease one available job with `SKIP LOCKED`, recovering expired leases."""

        if not connectors:
            return None
        reservation_query = text(
            """
            SELECT
                job.id,
                job.cycle_id,
                job.connector,
                job.state,
                job.attempt_count,
                job.max_attempts,
                job.last_safe_checkpoint,
                job.progress,
                ST_X(cycle.center::geometry) AS longitude,
                ST_Y(cycle.center::geometry) AS latitude,
                cycle.collection_radius_meters
            FROM collection_job AS job
            JOIN collection_cycle AS cycle ON cycle.id = job.cycle_id
            WHERE job.connector IN :connectors
              AND (
                    (job.state IN ('WAITING', 'WAITING_RETRY') AND job.available_at <= :now)
                    OR
                    (job.state = 'RUNNING' AND job.lease_expires_at <= :now)
              )
            ORDER BY job.created_at, job.id
            FOR UPDATE OF job SKIP LOCKED
            LIMIT 1
            """
        ).bindparams(bindparam("connectors", expanding=True))

        with self._engine.begin() as connection:
            while True:
                row = (
                    connection.execute(
                        reservation_query,
                        {"connectors": connectors, "now": now},
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None

                attempt_count = cast(int, row["attempt_count"])
                max_attempts = cast(int, row["max_attempts"])
                if cast(str, row["state"]) == "RUNNING":
                    self._close_expired_attempt(connection, cast(UUID, row["id"]), now)
                    if attempt_count >= max_attempts:
                        self._finish_expired_job(connection, row, now)
                        continue

                attempt_number = attempt_count + 1
                attempt_id = uuid4()
                connection.execute(
                    text(
                        """
                        UPDATE collection_job
                        SET
                            state = 'RUNNING',
                            started_at = COALESCE(started_at, :now),
                            attempt_count = :attempt_number,
                            lease_owner = :worker_id,
                            lease_expires_at = :lease_expires_at,
                            heartbeat_at = :now,
                            last_error = NULL,
                            progress = progress || '{"stage": "running"}'::jsonb
                        WHERE id = :job_id
                        """
                    ),
                    {
                        "job_id": row["id"],
                        "attempt_number": attempt_number,
                        "worker_id": worker_id,
                        "lease_expires_at": lease_expires_at,
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_cycle
                        SET started_at = COALESCE(started_at, :now)
                        WHERE id = :cycle_id
                        """
                    ),
                    {"cycle_id": row["cycle_id"], "now": now},
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO collection_attempt (
                            id,
                            collection_job_id,
                            attempt_number,
                            worker_id,
                            started_at,
                            heartbeat_at,
                            last_safe_checkpoint
                        ) VALUES (
                            :id,
                            :job_id,
                            :attempt_number,
                            :worker_id,
                            :now,
                            :now,
                            CAST(:checkpoint AS jsonb)
                        )
                        """
                    ),
                    {
                        "id": attempt_id,
                        "job_id": row["id"],
                        "attempt_number": attempt_number,
                        "worker_id": worker_id,
                        "now": now,
                        "checkpoint": (
                            json.dumps(_json_object(row["last_safe_checkpoint"]))
                            if row["last_safe_checkpoint"] is not None
                            else None
                        ),
                    },
                )
                checkpoint = (
                    _json_object(row["last_safe_checkpoint"])
                    if row["last_safe_checkpoint"] is not None
                    else None
                )
                return ReservedCollection(
                    job_id=cast(UUID, row["id"]),
                    cycle_id=cast(UUID, row["cycle_id"]),
                    attempt_id=attempt_id,
                    attempt_number=attempt_number,
                    max_attempts=max_attempts,
                    connector=cast(Connector, row["connector"]),
                    longitude=cast(float, row["longitude"]),
                    latitude=cast(float, row["latitude"]),
                    collection_radius_meters=cast(int, row["collection_radius_meters"]),
                    last_safe_checkpoint=checkpoint,
                )

    def heartbeat(
        self,
        reservation: ReservedCollection,
        worker_id: str,
        progress: CollectionProgress,
        checkpoint: JsonObject | None,
        now: datetime,
        lease_expires_at: datetime,
    ) -> None:
        """Renew one owned lease while atomically publishing safe progress."""

        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    """
                    UPDATE collection_job
                    SET
                        heartbeat_at = :now,
                        lease_expires_at = :lease_expires_at,
                        progress = CAST(:progress AS jsonb),
                        last_safe_checkpoint = CAST(:checkpoint AS jsonb)
                    WHERE id = :job_id
                      AND state = 'RUNNING'
                      AND lease_owner = :worker_id
                    RETURNING id
                    """
                ),
                {
                    "job_id": reservation.job_id,
                    "worker_id": worker_id,
                    "now": now,
                    "lease_expires_at": lease_expires_at,
                    "progress": json.dumps(progress.as_dict()),
                    "checkpoint": json.dumps(checkpoint) if checkpoint is not None else None,
                },
            ).scalar_one_or_none()
            if updated is None:
                raise CollectionLeaseLostError("the worker no longer owns this collection job")
            attempt_updated = connection.execute(
                text(
                    """
                    UPDATE collection_attempt
                    SET heartbeat_at = :now, last_safe_checkpoint = CAST(:checkpoint AS jsonb)
                    WHERE id = :attempt_id AND finished_at IS NULL
                    RETURNING id
                    """
                ),
                {
                    "attempt_id": reservation.attempt_id,
                    "now": now,
                    "checkpoint": json.dumps(checkpoint) if checkpoint is not None else None,
                },
            ).scalar_one_or_none()
            if attempt_updated is None:
                raise CollectionLeaseLostError("the collection attempt is no longer active")

    def defer_retry(
        self,
        reservation: ReservedCollection,
        worker_id: str,
        error: CollectionError,
        available_at: datetime,
        now: datetime,
    ) -> None:
        """Persist a bounded retry without sleeping inside the worker."""

        with self._engine.begin() as connection:
            self._require_owned_job(connection, reservation, worker_id)
            error_json = json.dumps(error.as_dict())
            connection.execute(
                text(
                    """
                    UPDATE collection_job
                    SET
                        state = 'WAITING_RETRY',
                        available_at = :available_at,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = :now,
                        last_error = CAST(:error AS jsonb),
                        progress = progress || '{"stage": "waiting_retry"}'::jsonb
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": reservation.job_id,
                    "available_at": available_at,
                    "now": now,
                    "error": error_json,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE collection_attempt
                    SET
                        finished_at = :now,
                        heartbeat_at = :now,
                        result = 'RETRYABLE_FAILURE',
                        error = CAST(:error AS jsonb)
                    WHERE id = :attempt_id AND finished_at IS NULL
                    """
                ),
                {"attempt_id": reservation.attempt_id, "now": now, "error": error_json},
            )

    def finish(
        self,
        reservation: ReservedCollection,
        worker_id: str,
        result: CollectionFinalResult,
        counters: JsonObject,
        error: CollectionError | None,
        source_freshness: JsonObject,
        explicit_limits: JsonObject,
        now: datetime,
    ) -> None:
        """Atomically close job, attempt and cycle, publishing coverage on success only."""

        with self._engine.begin() as connection:
            self._require_owned_job(connection, reservation, worker_id)
            error_json = json.dumps(error.as_dict()) if error is not None else None
            counters_json = json.dumps(counters)
            connection.execute(
                text(
                    """
                    UPDATE collection_job
                    SET
                        state = :result,
                        finished_at = :now,
                        heartbeat_at = :now,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        progress = CAST(:progress AS jsonb),
                        last_error = CAST(:error AS jsonb)
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": reservation.job_id,
                    "result": result,
                    "now": now,
                    "progress": json.dumps(_terminal_progress(result, counters)),
                    "error": error_json,
                },
            )
            attempt_result = result if result != "FAILED" else "FAILED"
            connection.execute(
                text(
                    """
                    UPDATE collection_attempt
                    SET
                        finished_at = :now,
                        heartbeat_at = :now,
                        result = :result,
                        error = CAST(:error AS jsonb)
                    WHERE id = :attempt_id AND finished_at IS NULL
                    """
                ),
                {
                    "attempt_id": reservation.attempt_id,
                    "now": now,
                    "result": attempt_result,
                    "error": error_json,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE collection_cycle
                    SET
                        result = :result,
                        finished_at = :now,
                        counters = CAST(:counters AS jsonb),
                        error = CAST(:error AS jsonb)
                    WHERE id = :cycle_id AND result IS NULL
                    """
                ),
                {
                    "cycle_id": reservation.cycle_id,
                    "result": result,
                    "now": now,
                    "counters": counters_json,
                    "error": error_json,
                },
            )
            if result == "SUCCEEDED":
                connection.execute(
                    text(
                        """
                        INSERT INTO connector_coverage (
                            id,
                            connector,
                            cycle_id,
                            center,
                            collection_radius_meters,
                            established_at,
                            source_freshness,
                            explicit_limits
                        )
                        SELECT
                            :id,
                            connector,
                            id,
                            center,
                            collection_radius_meters,
                            :now,
                            CAST(:source_freshness AS jsonb),
                            CAST(:explicit_limits AS jsonb)
                        FROM collection_cycle
                        WHERE id = :cycle_id
                        """
                    ),
                    {
                        "id": uuid4(),
                        "cycle_id": reservation.cycle_id,
                        "now": now,
                        "source_freshness": json.dumps(source_freshness),
                        "explicit_limits": json.dumps(explicit_limits),
                    },
                )

    def _find_existing(
        self,
        connection: Connection,
        connector: Connector,
        fingerprint: str,
        scheduled_for: datetime | None,
    ) -> CollectionJob | None:
        conditions = [
            "(job.request_fingerprint = :fingerprint "
            "AND job.state IN ('WAITING', 'RUNNING', 'WAITING_RETRY'))"
        ]
        parameters: dict[str, object] = {"connector": connector, "fingerprint": fingerprint}
        if scheduled_for is not None:
            conditions.append("(job.connector = :connector AND job.scheduled_for = :scheduled_for)")
            parameters["scheduled_for"] = scheduled_for
        row = (
            connection.execute(
                text(
                    f"""
                    SELECT {_JOB_COLUMNS}
                    FROM collection_job AS job
                    JOIN collection_cycle AS cycle ON cycle.id = job.cycle_id
                    JOIN reference_position AS reference
                        ON reference.id = cycle.reference_position_id
                    WHERE {" OR ".join(conditions)}
                    ORDER BY job.created_at DESC
                    LIMIT 1
                    """
                ),
                parameters,
            )
            .mappings()
            .one_or_none()
        )
        return _job_from_row(row) if row is not None else None

    def _load_job(self, connection: Connection, job_id: UUID) -> CollectionJob:
        row = (
            connection.execute(
                text(
                    f"""
                    SELECT {_JOB_COLUMNS}
                    FROM collection_job AS job
                    JOIN collection_cycle AS cycle ON cycle.id = job.cycle_id
                    JOIN reference_position AS reference
                        ON reference.id = cycle.reference_position_id
                    WHERE job.id = :job_id
                    """
                ),
                {"job_id": job_id},
            )
            .mappings()
            .one()
        )
        return _job_from_row(row)

    @staticmethod
    def _require_owned_job(
        connection: Connection,
        reservation: ReservedCollection,
        worker_id: str,
    ) -> None:
        owned = connection.execute(
            text(
                """
                SELECT job.id
                FROM collection_job AS job
                JOIN collection_attempt AS attempt
                    ON attempt.collection_job_id = job.id
                WHERE job.id = :job_id
                  AND job.state = 'RUNNING'
                  AND job.lease_owner = :worker_id
                  AND attempt.id = :attempt_id
                  AND attempt.finished_at IS NULL
                FOR UPDATE OF job, attempt
                """
            ),
            {
                "job_id": reservation.job_id,
                "attempt_id": reservation.attempt_id,
                "worker_id": worker_id,
            },
        ).scalar_one_or_none()
        if owned is None:
            raise CollectionLeaseLostError("the worker no longer owns this collection job")

    @staticmethod
    def _close_expired_attempt(connection: Connection, job_id: UUID, now: datetime) -> None:
        error = CollectionError(
            "lease_expired",
            "Le worker précédent n'a pas renouvelé son bail.",
            transient=True,
        )
        connection.execute(
            text(
                """
                UPDATE collection_attempt
                SET
                    finished_at = :now,
                    result = 'RETRYABLE_FAILURE',
                    error = CAST(:error AS jsonb)
                WHERE collection_job_id = :job_id AND finished_at IS NULL
                """
            ),
            {"job_id": job_id, "now": now, "error": json.dumps(error.as_dict())},
        )

    @staticmethod
    def _finish_expired_job(connection: Connection, row: RowMapping, now: datetime) -> None:
        progress = _progress(row["progress"])
        result: CollectionFinalResult = "PARTIAL" if progress.observations > 0 else "FAILED"
        error = CollectionError(
            "lease_expired",
            "La collecte a dépassé son nombre maximal de reprises après une interruption.",
            transient=False,
        )
        error_json = json.dumps(error.as_dict())
        counters: JsonObject = {
            "observations": progress.observations,
            "processed": progress.processed,
        }
        connection.execute(
            text(
                """
                UPDATE collection_job
                SET
                    state = :result,
                    finished_at = :now,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = :now,
                    progress = CAST(:progress AS jsonb),
                    last_error = CAST(:error AS jsonb)
                WHERE id = :job_id
                """
            ),
            {
                "job_id": row["id"],
                "result": result,
                "now": now,
                "progress": json.dumps(_terminal_progress(result, counters)),
                "error": error_json,
            },
        )
        connection.execute(
            text(
                """
                UPDATE collection_cycle
                SET
                    result = :result,
                    finished_at = :now,
                    counters = CAST(:counters AS jsonb),
                    error = CAST(:error AS jsonb)
                WHERE id = :cycle_id AND result IS NULL
                """
            ),
            {
                "cycle_id": row["cycle_id"],
                "result": result,
                "now": now,
                "counters": json.dumps(counters),
                "error": error_json,
            },
        )
