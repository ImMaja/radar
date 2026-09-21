"""Durable PostgreSQL lifecycle for Sirene source runs, batches and pages."""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.prospects.planning import SireneCollectionPlan, SireneMunicipalityBatch
from radar.prospects.sirene_collection import (
    SireneEnumerationResult,
    SireneExecutionError,
    SireneSourceState,
)
from radar.providers.sirene import SireneBatchSummary, SirenePage, SireneServiceInformation


def _json_object(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _optional_freshness(information: SireneServiceInformation) -> datetime | None:
    parsed_values: list[datetime] = []
    for _, value in information.freshness:
        if value is None:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed_values.append(parsed)
    return max(parsed_values, default=None)


def _source_metadata(information: SireneServiceInformation) -> dict[str, object]:
    return {
        "service_state": information.service_state,
        "service_version": information.service_version,
        "freshness": [
            {"collection": collection, "last_availability": availability}
            for collection, availability in information.freshness
        ],
    }


class SqlAlchemySireneExecutionRepository:
    """Persist restart-safe Sirene enumeration evidence without raw responses."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def source_state(self, plan: SireneCollectionPlan) -> SireneSourceState:
        """Load status and the date frozen from the cycle request instant."""

        with self._engine.connect() as connection:
            return self._source_state(connection, plan)

    def start_source(
        self,
        reservation: ReservedCollection,
        plan: SireneCollectionPlan,
        information: SireneServiceInformation,
        now: datetime,
    ) -> SireneSourceState:
        """Capture provider information once before the first establishment request."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                updated = connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET
                            status = 'RUNNING',
                            started_at = COALESCE(started_at, :now),
                            freshness_at = :freshness_at,
                            metadata = CAST(:metadata AS jsonb),
                            request_count = request_count + 1,
                            updated_at = :now
                        WHERE id = :source_run_id
                          AND collection_cycle_id = :cycle_id
                          AND status = 'PLANNED'
                        RETURNING id
                        """
                    ),
                    {
                        "source_run_id": plan.source_run_id,
                        "cycle_id": reservation.cycle_id,
                        "freshness_at": _optional_freshness(information),
                        "metadata": json.dumps(_source_metadata(information)),
                        "now": now,
                    },
                ).scalar_one_or_none()
                if updated is None:
                    state = self._source_state(connection, plan)
                    if state.status not in {"RUNNING", "SUCCEEDED"}:
                        raise SireneExecutionError("the Sirene source run cannot be started")
                    return state
                return self._source_state(connection, plan)
        except SireneExecutionError:
            raise
        except SQLAlchemyError as error:
            raise SireneExecutionError("cannot start the Sirene source run") from error

    def start_batch(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        now: datetime,
    ) -> bool:
        """Start or restart one whole batch from its initial cursor."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                current = (
                    connection.execute(
                        text(
                            """
                            SELECT batch.state, batch.last_collection_attempt_id, source.status
                            FROM collection_batch AS batch
                            JOIN collection_source_run AS source ON source.id = batch.source_run_id
                            WHERE batch.id = :batch_id
                              AND batch.collection_cycle_id = :cycle_id
                            FOR UPDATE OF batch
                            """
                        ),
                        {"batch_id": batch.id, "cycle_id": reservation.cycle_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if current is None:
                    raise SireneExecutionError("the Sirene batch does not belong to this cycle")
                if current["state"] == "SUCCEEDED":
                    return False
                if current["status"] != "RUNNING":
                    raise SireneExecutionError("the Sirene source run is not running")
                if (
                    current["state"] == "RUNNING"
                    and current["last_collection_attempt_id"] == reservation.attempt_id
                ):
                    raise SireneExecutionError(
                        "the Sirene batch is already running in this attempt"
                    )

                updated = connection.execute(
                    text(
                        """
                        UPDATE collection_batch
                        SET
                            state = 'RUNNING',
                            last_collection_attempt_id = :attempt_id,
                            attempt_count = attempt_count + 1,
                            started_at = :now,
                            finished_at = NULL,
                            error = NULL,
                            resume_state = '{}'::jsonb,
                            updated_at = :now
                        WHERE id = :batch_id
                          AND state IN ('WAITING', 'RUNNING', 'FAILED')
                        RETURNING id
                        """
                    ),
                    {
                        "batch_id": batch.id,
                        "attempt_id": reservation.attempt_id,
                        "now": now,
                    },
                ).scalar_one_or_none()
                if updated is None:
                    raise SireneExecutionError("the Sirene batch cannot be restarted")
                if current["state"] != "WAITING":
                    connection.execute(
                        text(
                            """
                            UPDATE collection_source_run
                            SET retry_count = retry_count + 1, updated_at = :now
                            WHERE id = (
                                SELECT source_run_id
                                FROM collection_batch
                                WHERE id = :batch_id
                            )
                            """
                        ),
                        {"batch_id": batch.id, "now": now},
                    )
                connection.execute(
                    text(
                        """
                        UPDATE collection_cycle_commune
                        SET state = 'RUNNING', updated_at = :now
                        WHERE collection_batch_id = :batch_id
                        """
                    ),
                    {"batch_id": batch.id, "now": now},
                )
                return True
        except SireneExecutionError:
            raise
        except SQLAlchemyError as error:
            raise SireneExecutionError("cannot start the Sirene batch") from error

    def record_page(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        page: SirenePage,
        now: datetime,
    ) -> None:
        """Acknowledge one page only after its candidate handler succeeded."""

        try:
            with self._engine.begin() as connection:
                self._require_running_batch(connection, reservation, batch.id)
                page_key = f"attempt:{reservation.attempt_number}:page:{page.number}"
                page_id = uuid4()
                connection.execute(
                    text(
                        """
                        INSERT INTO collection_page (
                            id,
                            collection_batch_id,
                            collection_attempt_id,
                            page_key,
                            responded_at,
                            http_status,
                            received_count,
                            unique_identifier_count,
                            announced_total,
                            next_link_fingerprint,
                            is_terminal,
                            state,
                            created_at,
                            updated_at
                        ) VALUES (
                            :id,
                            :batch_id,
                            :attempt_id,
                            :page_key,
                            :responded_at,
                            200,
                            :received_count,
                            :unique_identifier_count,
                            :announced_total,
                            :next_link_fingerprint,
                            :is_terminal,
                            'PROCESSED',
                            :created_at,
                            :updated_at
                        )
                        """
                    ),
                    {
                        "id": page_id,
                        "batch_id": batch.id,
                        "attempt_id": reservation.attempt_id,
                        "page_key": page_key,
                        "responded_at": now,
                        "received_count": page.received_count,
                        "unique_identifier_count": page.received_count,
                        "announced_total": page.announced_total,
                        "next_link_fingerprint": page.next_cursor_fingerprint,
                        "is_terminal": page.terminal,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_item
                        SET collection_page_id = :page_id, updated_at = :now
                        WHERE collection_batch_id = :batch_id
                          AND collection_attempt_id = :attempt_id
                          AND page_number = :page_number
                          AND collection_page_id IS NULL
                        """
                    ),
                    {
                        "page_id": page_id,
                        "batch_id": batch.id,
                        "attempt_id": reservation.attempt_id,
                        "page_number": page.number,
                        "now": now,
                    },
                )
                staged_item_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM collection_item
                        WHERE collection_batch_id = :batch_id
                          AND collection_attempt_id = :attempt_id
                          AND page_number = :page_number
                          AND collection_page_id = :page_id
                        """
                    ),
                    {
                        "page_id": page_id,
                        "batch_id": batch.id,
                        "attempt_id": reservation.attempt_id,
                        "page_number": page.number,
                    },
                ).scalar_one()
                if staged_item_count != len(page.importable_candidates):
                    raise SireneExecutionError(
                        "Sirene page evidence does not match its staged candidates"
                    )
                connection.execute(
                    text(
                        """
                        UPDATE source_observation AS observation
                        SET collection_page_id = :page_id
                        FROM collection_item AS item
                        WHERE item.collection_page_id = :page_id
                          AND item.source_observation_id = observation.id
                          AND observation.collection_cycle_id = :cycle_id
                          AND observation.collection_page_id IS NULL
                        """
                    ),
                    {"page_id": page_id, "cycle_id": reservation.cycle_id},
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_batch
                        SET
                            resume_state = jsonb_build_object(
                                'restart_policy', 'BATCH_FROM_START',
                                'last_completed_page', :page_number
                            ),
                            updated_at = :now
                        WHERE id = :batch_id
                        """
                    ),
                    {"batch_id": batch.id, "page_number": page.number, "now": now},
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET request_count = request_count + 1, updated_at = :now
                        WHERE id = (
                            SELECT source_run_id FROM collection_batch WHERE id = :batch_id
                        )
                        """
                    ),
                    {"batch_id": batch.id, "now": now},
                )
        except SireneExecutionError:
            raise
        except SQLAlchemyError as error:
            raise SireneExecutionError("cannot record the Sirene page") from error

    def complete_batch(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        summary: SireneBatchSummary,
        now: datetime,
    ) -> None:
        """Reconcile current-attempt page evidence before completing one batch."""

        try:
            with self._engine.begin() as connection:
                self._require_running_batch(connection, reservation, batch.id)
                evidence = (
                    connection.execute(
                        text(
                            """
                            SELECT
                                count(*) AS page_count,
                                sum(received_count) AS received_count,
                                sum(unique_identifier_count) AS unique_identifier_count,
                                min(announced_total) AS minimum_total,
                                max(announced_total) AS maximum_total,
                                count(*) FILTER (WHERE is_terminal) AS terminal_count
                            FROM collection_page
                            WHERE collection_batch_id = :batch_id
                              AND collection_attempt_id = :attempt_id
                              AND state = 'PROCESSED'
                            """
                        ),
                        {
                            "batch_id": batch.id,
                            "attempt_id": reservation.attempt_id,
                        },
                    )
                    .mappings()
                    .one()
                )
                if (
                    evidence["page_count"] != summary.page_count
                    or evidence["received_count"] != summary.received_count
                    or evidence["unique_identifier_count"] != summary.unique_siret_count
                    or evidence["minimum_total"] != summary.announced_total
                    or evidence["maximum_total"] != summary.announced_total
                    or evidence["terminal_count"] != 1
                ):
                    raise SireneExecutionError("Sirene page evidence does not match its summary")

                processing_counts = {
                    "page_count": summary.page_count,
                    "importable_count": summary.importable_count,
                    "rejection_counts": summary.rejection_counts,
                }
                connection.execute(
                    text(
                        """
                        UPDATE collection_batch
                        SET
                            state = 'SUCCEEDED',
                            finished_at = :now,
                            announced_total = :announced_total,
                            received_count = :received_count,
                            unique_identifier_count = :unique_identifier_count,
                            processing_counts = CAST(:processing_counts AS jsonb),
                            resume_state = jsonb_build_object(
                                'restart_policy', 'BATCH_FROM_START',
                                'terminal_page', :page_count
                            ),
                            error = NULL,
                            updated_at = :now
                        WHERE id = :batch_id
                        """
                    ),
                    {
                        "batch_id": batch.id,
                        "now": now,
                        "announced_total": summary.announced_total,
                        "received_count": summary.received_count,
                        "unique_identifier_count": summary.unique_siret_count,
                        "processing_counts": json.dumps(processing_counts),
                        "page_count": summary.page_count,
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_cycle_commune
                        SET state = 'SUCCEEDED', updated_at = :now
                        WHERE collection_batch_id = :batch_id
                        """
                    ),
                    {"batch_id": batch.id, "now": now},
                )
        except SireneExecutionError:
            raise
        except SQLAlchemyError as error:
            raise SireneExecutionError("cannot complete the Sirene batch") from error

    def fail_batch(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        *,
        code: str,
        message: str,
        transient: bool,
        now: datetime,
    ) -> None:
        """Retain non-sensitive failure state while allowing whole-batch retry."""

        error_payload = json.dumps({"code": code, "message": message, "transient": transient})
        try:
            with self._engine.begin() as connection:
                self._require_running_batch(connection, reservation, batch.id)
                connection.execute(
                    text(
                        """
                        UPDATE collection_batch
                        SET state = 'FAILED', finished_at = :now,
                            error = CAST(:error AS jsonb), updated_at = :now
                        WHERE id = :batch_id
                        """
                    ),
                    {"batch_id": batch.id, "now": now, "error": error_payload},
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_cycle_commune
                        SET state = 'FAILED', updated_at = :now
                        WHERE collection_batch_id = :batch_id
                        """
                    ),
                    {"batch_id": batch.id, "now": now},
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET
                            status = CASE WHEN :transient THEN status ELSE 'FAILED' END,
                            finished_at = CASE WHEN :transient THEN finished_at ELSE :now END,
                            error_count = error_count + 1,
                            updated_at = :now
                        WHERE id = (
                            SELECT source_run_id FROM collection_batch WHERE id = :batch_id
                        )
                        """
                    ),
                    {
                        "batch_id": batch.id,
                        "transient": transient,
                        "now": now,
                    },
                )
        except SireneExecutionError:
            raise
        except SQLAlchemyError as error:
            raise SireneExecutionError("cannot fail the Sirene batch safely") from error

    def finish_source(
        self,
        reservation: ReservedCollection,
        plan: SireneCollectionPlan,
        now: datetime,
    ) -> SireneEnumerationResult:
        """Publish aggregate source counts only after every batch succeeded."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                rows = self._completed_batch_rows(connection, plan)
                if len(rows) != len(plan.batches) or any(
                    row["state"] != "SUCCEEDED" for row in rows
                ):
                    raise SireneExecutionError("not every Sirene batch is complete")
                result = self._result_from_rows(connection, plan, rows)
                completed = connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET
                            status = 'SUCCEEDED',
                            finished_at = :now,
                            counters = CAST(:counters AS jsonb),
                            updated_at = :now
                        WHERE id = :source_run_id AND status = 'RUNNING'
                        RETURNING id
                        """
                    ),
                    {
                        "source_run_id": plan.source_run_id,
                        "now": now,
                        "counters": json.dumps(
                            {
                                "announced_total": result.announced_total,
                                "received_count": result.received_count,
                                "unique_siret_count": result.unique_siret_count,
                                "importable_count": result.importable_count,
                                "page_count": result.page_count,
                                "batch_count": result.batch_count,
                                "rejection_counts": result.rejection_counts,
                            }
                        ),
                    },
                ).scalar_one_or_none()
                if completed is None:
                    raise SireneExecutionError("the Sirene source run cannot be completed")
                return result
        except SireneExecutionError:
            raise
        except SQLAlchemyError as error:
            raise SireneExecutionError("cannot complete the Sirene source run") from error

    def completed_result(self, plan: SireneCollectionPlan) -> SireneEnumerationResult:
        """Rebuild a completed result from durable batches without provider calls."""

        with self._engine.connect() as connection:
            state = self._source_state(connection, plan)
            if state.status != "SUCCEEDED":
                raise SireneExecutionError("the Sirene source run is not complete")
            rows = self._completed_batch_rows(connection, plan)
            if len(rows) != len(plan.batches) or any(row["state"] != "SUCCEEDED" for row in rows):
                raise SireneExecutionError("the completed Sirene source has incomplete batches")
            return self._result_from_rows(connection, plan, rows)

    @staticmethod
    def _source_state(connection: Connection, plan: SireneCollectionPlan) -> SireneSourceState:
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        source.status,
                        to_char(
                            cycle.requested_at AT TIME ZONE cycle.schedule_timezone,
                            'YYYY-MM-DD'
                        ) AS query_date
                    FROM collection_source_run AS source
                    JOIN collection_cycle AS cycle ON cycle.id = source.collection_cycle_id
                    WHERE source.id = :source_run_id
                      AND source.collection_cycle_id = :cycle_id
                    """
                ),
                {"source_run_id": plan.source_run_id, "cycle_id": plan.cycle_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise SireneExecutionError("the Sirene source run does not exist")
        return SireneSourceState(
            status=cast(str, row["status"]),
            query_date=cast(str, row["query_date"]),
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
            raise SireneExecutionError("the collection attempt is no longer active")

    def _require_running_batch(
        self,
        connection: Connection,
        reservation: ReservedCollection,
        batch_id: UUID,
    ) -> None:
        self._require_active_attempt(connection, reservation)
        active = connection.execute(
            text(
                """
                SELECT id
                FROM collection_batch
                WHERE id = :batch_id
                  AND collection_cycle_id = :cycle_id
                  AND state = 'RUNNING'
                  AND last_collection_attempt_id = :attempt_id
                """
            ),
            {
                "batch_id": batch_id,
                "cycle_id": reservation.cycle_id,
                "attempt_id": reservation.attempt_id,
            },
        ).scalar_one_or_none()
        if active is None:
            raise SireneExecutionError("the Sirene batch is not owned by this attempt")

    @staticmethod
    def _completed_batch_rows(
        connection: Connection,
        plan: SireneCollectionPlan,
    ) -> Sequence[RowMapping]:
        return (
            connection.execute(
                text(
                    """
                    SELECT
                        state,
                        announced_total,
                        received_count,
                        unique_identifier_count,
                        processing_counts
                    FROM collection_batch
                    WHERE source_run_id = :source_run_id
                      AND batch_type = 'SIRENE_MUNICIPALITIES'
                    ORDER BY order_number
                    """
                ),
                {"source_run_id": plan.source_run_id},
            )
            .mappings()
            .all()
        )

    @staticmethod
    def _result_from_rows(
        connection: Connection,
        plan: SireneCollectionPlan,
        rows: Sequence[RowMapping],
    ) -> SireneEnumerationResult:
        rejection_counts: Counter[str] = Counter()
        importable_count = 0
        page_count = 0
        for row in rows:
            if (
                not isinstance(row["announced_total"], int)
                or not isinstance(row["received_count"], int)
                or not isinstance(row["unique_identifier_count"], int)
            ):
                raise SireneExecutionError("a completed Sirene batch has invalid totals")
            processing = _json_object(row["processing_counts"])
            raw_importable = processing.get("importable_count")
            raw_page_count = processing.get("page_count")
            if not isinstance(raw_importable, int) or not isinstance(raw_page_count, int):
                raise SireneExecutionError("a completed Sirene batch has invalid counters")
            importable_count += raw_importable
            page_count += raw_page_count
            raw_rejections = processing.get("rejection_counts")
            if isinstance(raw_rejections, Mapping):
                for key, value in raw_rejections.items():
                    if isinstance(key, str) and isinstance(value, int):
                        rejection_counts[key] += value

        metadata = connection.execute(
            text("SELECT metadata FROM collection_source_run WHERE id = :source_run_id"),
            {"source_run_id": plan.source_run_id},
        ).scalar_one()
        return SireneEnumerationResult(
            announced_total=sum(cast(int, row["announced_total"]) for row in rows),
            received_count=sum(cast(int, row["received_count"]) for row in rows),
            unique_siret_count=sum(cast(int, row["unique_identifier_count"]) for row in rows),
            importable_count=importable_count,
            page_count=page_count,
            batch_count=len(rows),
            rejection_counts=dict(sorted(rejection_counts.items())),
            source_metadata=_json_object(metadata),
        )
