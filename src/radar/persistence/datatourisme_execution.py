"""Durable DATAtourisme source, batch and page lifecycle."""

import json
import math
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.events.collection import EventExecutionError, EventRunState
from radar.events.staging import DATATOURISME_ADAPTER_VERSION
from radar.providers.datatourisme import PAGE_SIZE, DatatourismeCollectionSummary, DatatourismePage

_SOURCE = "DATATOURISME_API"


class SqlAlchemyEventExecutionRepository:
    """Restart a failed enumeration from its first provider page."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _require_active_attempt(connection: Connection, reservation: ReservedCollection) -> None:
        active = connection.execute(
            text(
                """
                SELECT job.id
                FROM collection_job AS job
                JOIN collection_attempt AS attempt ON attempt.collection_job_id = job.id
                WHERE job.id = :job_id AND job.cycle_id = :cycle_id
                  AND job.connector = 'DATATOURISME' AND job.state = 'RUNNING'
                  AND attempt.id = :attempt_id AND attempt.finished_at IS NULL
                """
            ),
            {
                "job_id": reservation.job_id,
                "cycle_id": reservation.cycle_id,
                "attempt_id": reservation.attempt_id,
            },
        ).scalar_one_or_none()
        if active is None:
            raise EventExecutionError("DATAtourisme execution requires an active attempt")

    @staticmethod
    def _source_and_batch(
        connection: Connection,
        reservation: ReservedCollection,
        batch_id: UUID,
        *,
        running: bool,
    ) -> RowMapping:
        row = (
            connection.execute(
                text(
                    """
                SELECT batch.id, batch.state, batch.last_collection_attempt_id,
                       batch.resume_state, source.id AS source_run_id,
                       source.status AS source_status
                FROM collection_batch AS batch
                JOIN collection_source_run AS source ON source.id = batch.source_run_id
                WHERE batch.id = :batch_id AND batch.collection_cycle_id = :cycle_id
                  AND batch.batch_type = 'DATATOURISME_EVENTS'
                  AND source.source = :source
                FOR UPDATE OF batch, source
                """
                ),
                {"batch_id": batch_id, "cycle_id": reservation.cycle_id, "source": _SOURCE},
            )
            .mappings()
            .one_or_none()
        )
        if row is None or (
            running
            and (
                row["state"] != "RUNNING"
                or row["source_status"] != "RUNNING"
                or row["last_collection_attempt_id"] != reservation.attempt_id
            )
        ):
            raise EventExecutionError("DATAtourisme batch is not owned by this attempt")
        return row

    def start_or_resume(self, reservation: ReservedCollection, now: datetime) -> EventRunState:
        """Create one logical batch or restart it without reusing an opaque cursor."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                connection.execute(
                    text(
                        """
                        INSERT INTO collection_source_run (
                            id, collection_cycle_id, source, status, counters, metadata,
                            request_count, retry_count, error_count, contract_version,
                            created_at, updated_at
                        ) VALUES (
                            :id, :cycle_id, :source, 'PLANNED', '{}'::jsonb,
                            '{"restart_policy":"FROM_FIRST_PAGE"}'::jsonb,
                            0, 0, 0, :contract_version, :now, :now
                        ) ON CONFLICT (collection_cycle_id, source) DO NOTHING
                        """
                    ),
                    {
                        "id": uuid4(),
                        "cycle_id": reservation.cycle_id,
                        "source": _SOURCE,
                        "contract_version": DATATOURISME_ADAPTER_VERSION,
                        "now": now,
                    },
                )
                source = (
                    connection.execute(
                        text(
                            """
                        SELECT id, status, counters FROM collection_source_run
                        WHERE collection_cycle_id = :cycle_id AND source = :source
                        FOR UPDATE
                        """
                        ),
                        {"cycle_id": reservation.cycle_id, "source": _SOURCE},
                    )
                    .mappings()
                    .one()
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO collection_batch (
                            id, collection_cycle_id, source_run_id, batch_type, batch_key,
                            order_number, state, attempt_count, resume_state,
                            processing_counts, created_at, updated_at
                        ) VALUES (
                            :id, :cycle_id, :source_run_id, 'DATATOURISME_EVENTS',
                            'events', 1, 'WAITING', 0, '{}'::jsonb, '{}'::jsonb,
                            :now, :now
                        ) ON CONFLICT (collection_cycle_id, batch_key) DO NOTHING
                        """
                    ),
                    {
                        "id": uuid4(),
                        "cycle_id": reservation.cycle_id,
                        "source_run_id": source["id"],
                        "now": now,
                    },
                )
                batch = (
                    connection.execute(
                        text(
                            """
                        SELECT id, source_run_id, batch_type, state,
                               last_collection_attempt_id
                        FROM collection_batch
                        WHERE collection_cycle_id = :cycle_id AND batch_key = 'events'
                        FOR UPDATE
                        """
                        ),
                        {"cycle_id": reservation.cycle_id},
                    )
                    .mappings()
                    .one()
                )
                if (
                    batch["source_run_id"] != source["id"]
                    or batch["batch_type"] != "DATATOURISME_EVENTS"
                ):
                    raise EventExecutionError("DATAtourisme source batch belongs to another run")
                if source["status"] == "SUCCEEDED" and batch["state"] == "SUCCEEDED":
                    return EventRunState(batch["id"], self._completed_summary(source["counters"]))
                if source["status"] not in ("PLANNED", "RUNNING") or batch["state"] not in (
                    "WAITING",
                    "RUNNING",
                    "FAILED",
                ):
                    raise EventExecutionError("DATAtourisme source batch is not resumable")
                if (
                    batch["state"] == "RUNNING"
                    and batch["last_collection_attempt_id"] == reservation.attempt_id
                ):
                    raise EventExecutionError("DATAtourisme batch already runs in this attempt")
                connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET status = 'RUNNING', started_at = COALESCE(started_at, :now),
                            retry_count = retry_count + :retry_increment, updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": source["id"],
                        "now": now,
                        "retry_increment": int(batch["state"] != "WAITING"),
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_batch
                        SET state = 'RUNNING', attempt_count = attempt_count + 1,
                            last_collection_attempt_id = :attempt_id,
                            started_at = :now, finished_at = NULL, error = NULL,
                            resume_state = '{"restart_policy":"FROM_FIRST_PAGE"}'::jsonb,
                            updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {"id": batch["id"], "attempt_id": reservation.attempt_id, "now": now},
                )
                return EventRunState(batch["id"])
        except EventExecutionError:
            raise
        except SQLAlchemyError as error:
            raise EventExecutionError("cannot start DATAtourisme event enumeration") from error

    def record_page(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        page: DatatourismePage,
        now: datetime,
    ) -> None:
        """Acknowledge a page only after all its importable candidates are staged."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                state = self._source_and_batch(connection, reservation, batch_id, running=True)
                last_page = state["resume_state"].get("last_completed_page", 0)
                if type(last_page) is not int or page.number != last_page + 1:
                    raise EventExecutionError("DATAtourisme pages are not sequential")
                if (
                    page.received_count < 0
                    or page.received_count
                    != len(page.importable_candidates) + sum(page.rejection_counts.values())
                    or any(count < 0 for count in page.rejection_counts.values())
                ):
                    raise EventExecutionError("DATAtourisme page candidate counts are invalid")
                page_id = uuid4()
                connection.execute(
                    text(
                        """
                        INSERT INTO collection_page (
                            id, collection_batch_id, collection_attempt_id, page_key,
                            responded_at, http_status, received_count,
                            unique_identifier_count, announced_total,
                            announced_page_count, next_link_fingerprint, is_terminal,
                            state, created_at, updated_at
                        ) VALUES (
                            :id, :batch_id, :attempt_id, :page_key, :now, 200,
                            :received_count, :received_count, :announced_total,
                            :announced_page_count, :next_link_fingerprint, :is_terminal,
                            'PROCESSED', :now, :now
                        )
                        """
                    ),
                    {
                        "id": page_id,
                        "batch_id": batch_id,
                        "attempt_id": reservation.attempt_id,
                        "page_key": f"attempt:{reservation.attempt_number}:page:{page.number}",
                        "now": now,
                        "received_count": page.received_count,
                        "announced_total": page.announced_total,
                        "announced_page_count": page.announced_total_pages,
                        "next_link_fingerprint": page.next_link_fingerprint,
                        "is_terminal": page.terminal,
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_item SET collection_page_id = :page_id,
                            updated_at = :now
                        WHERE collection_batch_id = :batch_id
                          AND collection_attempt_id = :attempt_id
                          AND page_number = :page_number
                          AND collection_page_id IS NULL
                        """
                    ),
                    {
                        "page_id": page_id,
                        "batch_id": batch_id,
                        "attempt_id": reservation.attempt_id,
                        "page_number": page.number,
                        "now": now,
                    },
                )
                staged_count = connection.execute(
                    text(
                        """
                        SELECT count(*) FROM collection_item
                        WHERE collection_batch_id = :batch_id
                          AND collection_attempt_id = :attempt_id
                          AND page_number = :page_number
                          AND collection_page_id = :page_id
                        """
                    ),
                    {
                        "batch_id": batch_id,
                        "attempt_id": reservation.attempt_id,
                        "page_number": page.number,
                        "page_id": page_id,
                    },
                ).scalar_one()
                if staged_count != len(page.importable_candidates):
                    raise EventExecutionError("DATAtourisme page staging does not reconcile")
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
                        SET resume_state = jsonb_build_object(
                            'restart_policy', 'FROM_FIRST_PAGE',
                            'last_completed_page', CAST(:page_number AS integer)
                        ), updated_at = :now
                        WHERE id = :batch_id
                        """
                    ),
                    {"batch_id": batch_id, "page_number": page.number, "now": now},
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET request_count = request_count + 1, updated_at = :now
                        WHERE id = :source_run_id
                        """
                    ),
                    {"source_run_id": state["source_run_id"], "now": now},
                )
        except EventExecutionError:
            raise
        except SQLAlchemyError as error:
            raise EventExecutionError("cannot acknowledge DATAtourisme event page") from error

    def complete(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        summary: DatatourismeCollectionSummary,
        now: datetime,
    ) -> None:
        """Reconcile every current-attempt page before publishing source success."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                state = self._source_and_batch(connection, reservation, batch_id, running=True)
                evidence = (
                    connection.execute(
                        text(
                            """
                        SELECT count(*) AS page_count,
                               COALESCE(sum(received_count), 0) AS received_count,
                               COALESCE(sum(unique_identifier_count), 0) AS unique_count,
                               min(announced_total) AS minimum_total,
                               max(announced_total) AS maximum_total,
                               min(announced_page_count) AS minimum_pages,
                               max(announced_page_count) AS maximum_pages,
                               count(*) FILTER (WHERE is_terminal) AS terminal_count
                        FROM collection_page
                        WHERE collection_batch_id = :batch_id
                          AND collection_attempt_id = :attempt_id
                          AND state = 'PROCESSED'
                        """
                        ),
                        {"batch_id": batch_id, "attempt_id": reservation.attempt_id},
                    )
                    .mappings()
                    .one()
                )
                staged_count = connection.execute(
                    text(
                        """
                        SELECT count(*) FROM collection_item
                        WHERE collection_batch_id = :batch_id
                          AND collection_attempt_id = :attempt_id
                          AND collection_page_id IS NOT NULL
                        """
                    ),
                    {"batch_id": batch_id, "attempt_id": reservation.attempt_id},
                ).scalar_one()
                expected_page_total = math.ceil(summary.announced_total / PAGE_SIZE)
                if (
                    summary.received_count != summary.announced_total
                    or summary.unique_uuid_count != summary.received_count
                    or summary.importable_count + sum(summary.rejection_counts.values())
                    != summary.received_count
                    or summary.page_count != max(1, expected_page_total)
                    or evidence["page_count"] != summary.page_count
                    or evidence["received_count"] != summary.received_count
                    or evidence["unique_count"] != summary.unique_uuid_count
                    or evidence["minimum_total"] != summary.announced_total
                    or evidence["maximum_total"] != summary.announced_total
                    or evidence["minimum_pages"] != expected_page_total
                    or evidence["maximum_pages"] != expected_page_total
                    or evidence["terminal_count"] != 1
                    or state["resume_state"].get("last_completed_page") != summary.page_count
                    or staged_count != summary.importable_count
                ):
                    raise EventExecutionError("DATAtourisme page evidence is incomplete")
                counters = {
                    "announced_total": summary.announced_total,
                    "received_count": summary.received_count,
                    "unique_uuid_count": summary.unique_uuid_count,
                    "importable_count": summary.importable_count,
                    "page_count": summary.page_count,
                    "rejection_counts": summary.rejection_counts,
                }
                connection.execute(
                    text(
                        """
                        UPDATE collection_batch SET state = 'SUCCEEDED', finished_at = :now,
                            announced_total = :announced_total,
                            received_count = :received_count,
                            unique_identifier_count = :unique_count,
                            processing_counts = CAST(:counters AS jsonb),
                            resume_state = jsonb_build_object(
                                'restart_policy', 'FROM_FIRST_PAGE',
                                'terminal_page', CAST(:page_count AS integer)
                            ), updated_at = :now
                        WHERE id = :batch_id
                        """
                    ),
                    {
                        "batch_id": batch_id,
                        "now": now,
                        "announced_total": summary.announced_total,
                        "received_count": summary.received_count,
                        "unique_count": summary.unique_uuid_count,
                        "page_count": summary.page_count,
                        "counters": json.dumps(counters),
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET status = 'SUCCEEDED', finished_at = :now,
                            counters = CAST(:counters AS jsonb), updated_at = :now
                        WHERE id = :source_run_id
                        """
                    ),
                    {
                        "source_run_id": state["source_run_id"],
                        "now": now,
                        "counters": json.dumps(counters),
                    },
                )
        except EventExecutionError:
            raise
        except SQLAlchemyError as error:
            raise EventExecutionError("cannot complete DATAtourisme event enumeration") from error

    def fail(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        *,
        code: str,
        transient: bool,
        now: datetime,
    ) -> None:
        """Record a safe failure while allowing a later whole-batch retry."""

        try:
            with self._engine.begin() as connection:
                self._require_active_attempt(connection, reservation)
                state = self._source_and_batch(connection, reservation, batch_id, running=True)
                connection.execute(
                    text(
                        """
                        UPDATE collection_batch
                        SET state = 'FAILED', finished_at = :now,
                            error = jsonb_build_object(
                                'code', CAST(:code AS text), 'transient', CAST(:transient AS boolean)
                            ), updated_at = :now
                        WHERE id = :batch_id
                        """
                    ),
                    {"batch_id": batch_id, "code": code, "transient": transient, "now": now},
                )
                connection.execute(
                    text(
                        """
                        UPDATE collection_source_run
                        SET status = CASE WHEN :transient THEN 'RUNNING' ELSE 'FAILED' END,
                            finished_at = CASE WHEN :transient THEN NULL ELSE :now END,
                            error_count = error_count + 1, updated_at = :now
                        WHERE id = :source_run_id
                        """
                    ),
                    {"source_run_id": state["source_run_id"], "transient": transient, "now": now},
                )
        except EventExecutionError:
            raise
        except SQLAlchemyError as error:
            raise EventExecutionError("cannot record DATAtourisme event failure") from error

    @staticmethod
    def _completed_summary(value: object) -> DatatourismeCollectionSummary:
        if not isinstance(value, dict):
            raise EventExecutionError("completed DATAtourisme source counters are missing")
        names = (
            "announced_total",
            "received_count",
            "unique_uuid_count",
            "importable_count",
            "page_count",
        )
        if any(type(value.get(name)) is not int or value[name] < 0 for name in names):
            raise EventExecutionError("completed DATAtourisme source counters are invalid")
        rejections = value.get("rejection_counts")
        if not isinstance(rejections, dict) or any(
            not isinstance(key, str) or type(count) is not int or count < 0
            for key, count in rejections.items()
        ):
            raise EventExecutionError("completed DATAtourisme rejection counts are invalid")
        return DatatourismeCollectionSummary(
            value["announced_total"],
            value["received_count"],
            value["unique_uuid_count"],
            value["importable_count"],
            value["page_count"],
            rejections,
        )
