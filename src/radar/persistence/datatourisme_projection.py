"""Project staged DATAtourisme revisions into stable events and source periods."""

import json
from datetime import date, datetime, time
from typing import Any, TypedDict
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.events.projection import (
    EventProjectionError,
    EventProjectionPage,
    EventProjectionSummary,
)
from radar.events.staging import DATATOURISME_DATA_SOURCE_CODE
from radar.persistence.datatourisme_contacts import project_event_contacts
from radar.persistence.datatourisme_location import project_event_location


class _Period(TypedDict):
    source_index: int
    start_date: date
    end_date: date
    start_time: time | None
    end_time: time | None
    precision: str
    interpretation_timezone: str


def _periods(reason: object) -> tuple[_Period, ...]:
    """Validate the staged complete set before replacing a published set."""

    if not isinstance(reason, dict) or not isinstance(reason.get("validated_periods"), list):
        raise EventProjectionError("a staged event has no validated period set")
    result: list[_Period] = []
    for entry in reason["validated_periods"]:
        if not isinstance(entry, dict):
            raise EventProjectionError("a staged event period is malformed")
        try:
            source_index = entry["source_index"]
            start_date = date.fromisoformat(entry["start_date"])
            end_date = date.fromisoformat(entry["end_date"])
            start_time = (
                time.fromisoformat(entry["start_time"]) if entry.get("start_time") else None
            )
            end_time = time.fromisoformat(entry["end_time"]) if entry.get("end_time") else None
            precision = entry["precision"]
            timezone = entry["interpretation_timezone"]
        except (KeyError, TypeError, ValueError) as error:
            raise EventProjectionError("a staged event period is malformed") from error
        if (
            type(source_index) is not int
            or source_index < 1
            or end_date < start_date
            or precision not in ("DATE_ONLY", "DATE_AND_TIME", "MIXED")
            or timezone != "Europe/Paris"
        ):
            raise EventProjectionError("a staged event period violates the source contract")
        result.append(
            {
                "source_index": source_index,
                "start_date": start_date,
                "end_date": end_date,
                "start_time": start_time,
                "end_time": end_time,
                "precision": precision,
                "interpretation_timezone": timezone,
            }
        )
    return tuple(result)


def _event_fields(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise EventProjectionError("a staged event payload is malformed")
    title = payload.get("title")
    uri = payload.get("uri")
    types = payload.get("types")
    descriptions = payload.get("descriptions")
    if (
        not isinstance(title, str)
        or not title.strip()
        or not isinstance(uri, str)
        or not isinstance(types, list)
        or not all(isinstance(value, str) for value in types)
        or not isinstance(descriptions, list)
    ):
        raise EventProjectionError("a staged event payload violates the source contract")
    description: str | None = None
    description_path: str | None = None
    for index, item in enumerate(descriptions):
        if not isinstance(item, dict):
            raise EventProjectionError("a staged event description is malformed")
        for key in ("full", "short"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                description = value.strip()
                description_path = f"descriptions[{index}].{key}"
                break
        if description is not None:
            break
    return {
        "title": title.strip(),
        "description": description,
        "description_path": description_path,
        "types": types,
        "uri": uri,
    }


class SqlAlchemyEventProjectionRepository:
    """Project one completed provider page per transaction, preserving USER data."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _require_ready(connection: Connection, reservation: ReservedCollection) -> None:
        ready = connection.execute(
            text(
                """
                SELECT job.id
                FROM collection_job AS job
                JOIN collection_attempt AS attempt
                  ON attempt.collection_job_id = job.id
                JOIN collection_source_run AS source
                  ON source.collection_cycle_id = job.cycle_id
                WHERE job.id = :job_id
                  AND job.cycle_id = :cycle_id
                  AND job.connector = 'DATATOURISME'
                  AND job.state = 'RUNNING'
                  AND attempt.id = :attempt_id
                  AND attempt.finished_at IS NULL
                  AND source.source = :source_code
                  AND source.status = 'SUCCEEDED'
                """
            ),
            {
                "job_id": reservation.job_id,
                "cycle_id": reservation.cycle_id,
                "attempt_id": reservation.attempt_id,
                "source_code": DATATOURISME_DATA_SOURCE_CODE,
            },
        ).scalar_one_or_none()
        if ready is None:
            raise EventProjectionError("DATAtourisme projection requires a completed source run")

    def pending_pages(self, reservation: ReservedCollection) -> tuple[EventProjectionPage, ...]:
        try:
            with self._engine.connect() as connection:
                self._require_ready(connection, reservation)
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
                          AND item.authority = 'DATATOURISME'
                          AND item.namespace = 'DATATOURISME_UUID'
                          AND item.decision IS NULL
                        GROUP BY item.collection_batch_id, item.page_number, batch.order_number
                        ORDER BY batch.order_number, item.page_number
                        """
                    ),
                    {"cycle_id": reservation.cycle_id},
                ).all()
        except EventProjectionError:
            raise
        except SQLAlchemyError as error:
            raise EventProjectionError("cannot load pending DATAtourisme pages") from error
        return tuple(EventProjectionPage(row[0], row[1]) for row in rows)

    def project_page(
        self, reservation: ReservedCollection, page: EventProjectionPage, now: datetime
    ) -> None:
        if page.page_number < 1:
            raise ValueError("a DATAtourisme projection page number must be positive")
        try:
            with self._engine.begin() as connection:
                self._require_ready(connection, reservation)
                items = (
                    connection.execute(
                        text(
                            """
                        SELECT item.id, item.external_identity_id,
                               item.source_observation_id, item.reason,
                               observation.payload, observation.validation_status
                        FROM collection_item AS item
                        JOIN collection_batch AS batch
                          ON batch.id = item.collection_batch_id
                         AND batch.last_collection_attempt_id = item.collection_attempt_id
                         AND batch.state = 'SUCCEEDED'
                        JOIN source_observation AS observation
                          ON observation.id = item.source_observation_id
                        WHERE item.collection_cycle_id = :cycle_id
                          AND item.collection_batch_id = :batch_id
                          AND item.page_number = :page_number
                          AND item.authority = 'DATATOURISME'
                          AND item.namespace = 'DATATOURISME_UUID'
                          AND item.normalization_result = 'VALID'
                          AND item.geographic_classification = 'IN_RADIUS'
                          AND item.decision IS NULL
                        ORDER BY item.item_rank
                        FOR UPDATE OF item
                        """
                        ),
                        {
                            "cycle_id": reservation.cycle_id,
                            "batch_id": page.collection_batch_id,
                            "page_number": page.page_number,
                        },
                    )
                    .mappings()
                    .all()
                )
                for item in items:
                    self._project_item(connection, reservation, item, now)
        except EventProjectionError:
            raise
        except SQLAlchemyError as error:
            raise EventProjectionError("cannot project a DATAtourisme event page") from error

    @classmethod
    def _project_item(
        cls,
        connection: Connection,
        reservation: ReservedCollection,
        item: RowMapping,
        now: datetime,
    ) -> None:
        periods = _periods(item["reason"])
        fields = _event_fields(item["payload"])
        identity = (
            connection.execute(
                text(
                    """
                SELECT id, opportunity_id
                FROM external_identity
                WHERE id = :identity_id
                  AND authority = 'DATATOURISME'
                  AND namespace = 'DATATOURISME_UUID'
                FOR UPDATE
                """
                ),
                {"identity_id": item["external_identity_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if identity is None:
            raise EventProjectionError("staged DATAtourisme identity is missing")
        binding = (
            connection.execute(
                text(
                    """
                SELECT id, opportunity_id, current_observation_id, source_url
                FROM source_binding
                WHERE data_source_code = :source_code
                  AND external_identity_id = :identity_id
                FOR UPDATE
                """
                ),
                {
                    "source_code": DATATOURISME_DATA_SOURCE_CODE,
                    "identity_id": identity["id"],
                },
            )
            .mappings()
            .one_or_none()
        )
        if binding is not None and identity["opportunity_id"] != binding["opportunity_id"]:
            raise EventProjectionError("DATAtourisme identity and binding disagree")
        if binding is None and identity["opportunity_id"] is not None:
            raise EventProjectionError("DATAtourisme identity has no source binding")
        if item["validation_status"] == "IDENTITY_CONFLICT":
            cls._quarantine_identity_conflict(
                connection, item, "PREVIOUSLY_QUARANTINED_IDENTITY", now
            )
            return
        if item["validation_status"] != "VALID":
            raise EventProjectionError("projection-ready DATAtourisme observation is invalid")
        if cls._identity_was_quarantined(connection, identity["id"]):
            cls._quarantine_identity_conflict(connection, item, "PRIOR_IDENTITY_CONFLICT", now)
            return
        if (binding is None or binding["source_url"] != fields["uri"]) and cls._uri_is_claimed(
            connection, identity["id"], fields["uri"]
        ):
            cls._quarantine_identity_conflict(
                connection, item, "SOURCE_URI_SHARED_BY_MULTIPLE_UUIDS", now
            )
            return
        if not periods:
            raise EventProjectionError("a projection-ready event has no valid period")
        if binding is None and item["reason"].get("temporal_state") == "PAST":
            cls._decide(connection, item["id"], None, "REJECTED", "PAST_ONLY_NEW", now)
            return

        created = binding is None
        opportunity_id = uuid4() if binding is None else binding["opportunity_id"]
        prior_observation_id = None if binding is None else binding["current_observation_id"]
        observation_id = item["source_observation_id"]
        parameters: dict[str, Any] = {
            "opportunity_id": opportunity_id,
            "identity_id": identity["id"],
            "observation_id": observation_id,
            "source_code": DATATOURISME_DATA_SOURCE_CODE,
            "now": now,
            **fields,
        }
        if created:
            connection.execute(
                text(
                    """
                    INSERT INTO opportunity (id, kind, creation_origin, created_at, updated_at)
                    VALUES (:opportunity_id, 'EVENT', 'SOURCE', :now, :now)
                    """
                ),
                parameters,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO event (
                        id, source_title, source_description, source_types,
                        declared_status, source_uri, first_observed_at,
                        last_observed_at, created_at, updated_at
                    ) VALUES (
                        :opportunity_id, :title, :description, CAST(:types AS jsonb),
                        'UNKNOWN', :uri, :now, :now, :now, :now
                    )
                    """
                ),
                {**parameters, "types": _json(fields["types"])},
            )
            connection.execute(
                text(
                    """
                    UPDATE external_identity SET opportunity_id = :opportunity_id
                    WHERE id = :identity_id AND opportunity_id IS NULL
                    """
                ),
                parameters,
            )
        else:
            exists = connection.execute(
                text("SELECT id FROM event WHERE id = :opportunity_id"), parameters
            ).scalar_one_or_none()
            if exists is None:
                raise EventProjectionError("DATAtourisme binding targets a missing event")
            if prior_observation_id != observation_id:
                connection.execute(
                    text(
                        """
                        UPDATE event SET
                            source_title = :title,
                            source_description = :description,
                            source_types = CAST(:types AS jsonb),
                            source_uri = :uri,
                            last_observed_at = GREATEST(last_observed_at, :now),
                            updated_at = GREATEST(updated_at, :now)
                        WHERE id = :opportunity_id
                        """
                    ),
                    {**parameters, "types": _json(fields["types"])},
                )
            else:
                connection.execute(
                    text(
                        """
                        UPDATE event SET last_observed_at = GREATEST(last_observed_at, :now)
                        WHERE id = :opportunity_id
                        """
                    ),
                    parameters,
                )

        binding_id = uuid4() if binding is None else binding["id"]
        connection.execute(
            text(
                """
                INSERT INTO source_binding (
                    id, data_source_code, external_identity_id, opportunity_id,
                    source_url, first_observed_at, last_observed_at,
                    current_observation_id, state, consecutive_absence_count,
                    last_checked_at, created_at, updated_at
                ) VALUES (
                    :binding_id, :source_code, :identity_id, :opportunity_id,
                    :uri, :now, :now, :observation_id, 'CURRENT', 0,
                    :now, :now, :now
                ) ON CONFLICT (data_source_code, external_identity_id) DO UPDATE SET
                    source_url = EXCLUDED.source_url,
                    last_observed_at = GREATEST(source_binding.last_observed_at,
                                                EXCLUDED.last_observed_at),
                    current_observation_id = EXCLUDED.current_observation_id,
                    state = 'CURRENT', consecutive_absence_count = 0,
                    last_checked_at = EXCLUDED.last_checked_at,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {**parameters, "binding_id": binding_id},
        )
        linked = connection.execute(
            text(
                """
                UPDATE source_observation SET source_binding_id = :binding_id
                WHERE id = :observation_id
                  AND (source_binding_id IS NULL OR source_binding_id = :binding_id)
                """
            ),
            {**parameters, "binding_id": binding_id},
        ).rowcount
        if linked != 1:
            raise EventProjectionError("DATAtourisme observation belongs to another binding")
        connection.execute(
            text(
                """
                INSERT INTO source_sighting (
                    source_binding_id, collection_cycle_id, source_observation_id, seen_at
                ) VALUES (:binding_id, :cycle_id, :observation_id, :now)
                ON CONFLICT (source_binding_id, collection_cycle_id) DO UPDATE SET
                    source_observation_id = EXCLUDED.source_observation_id,
                    seen_at = EXCLUDED.seen_at
                """
            ),
            {**parameters, "binding_id": binding_id, "cycle_id": reservation.cycle_id},
        )
        cls._lineage(connection, parameters)
        period_changed = cls._project_periods(
            connection, opportunity_id, observation_id, periods, now
        )
        location_changed = project_event_location(
            connection,
            opportunity_id,
            observation_id,
            item["payload"],
            item["reason"],
            now,
        )
        contacts_changed = project_event_contacts(
            connection, opportunity_id, observation_id, item["payload"], now
        )
        changed = (
            prior_observation_id != observation_id
            or period_changed
            or location_changed
            or contacts_changed
        )
        if not created and changed:
            connection.execute(
                text(
                    """
                    UPDATE opportunity SET updated_at = GREATEST(updated_at, :now)
                    WHERE id = :opportunity_id
                    """
                ),
                parameters,
            )
        decision = "CREATED" if created else ("UPDATED" if changed else "UNCHANGED")
        cls._decide(connection, item["id"], opportunity_id, decision, "EVENT_PROJECTED", now)

    @staticmethod
    def _lineage(connection: Connection, parameters: dict[str, Any]) -> None:
        paths = [("EVENT_TITLE", "title"), ("EVENT_TYPES", "types"), ("EVENT_URI", "uri")]
        if parameters["description_path"] is not None:
            paths.append(("EVENT_DESCRIPTION", parameters["description_path"]))
        for field_code, source_path in paths:
            connection.execute(
                text(
                    """
                    INSERT INTO field_lineage (
                        opportunity_id, field_code, source_observation_id,
                        source_path, resolution_rule, resolved_at
                    ) VALUES (
                        :opportunity_id, :field_code, :observation_id,
                        :source_path, 'datatourisme-event-v1', :now
                    ) ON CONFLICT (opportunity_id, field_code) DO UPDATE SET
                        source_observation_id = EXCLUDED.source_observation_id,
                        source_path = EXCLUDED.source_path,
                        resolution_rule = EXCLUDED.resolution_rule,
                        resolved_at = EXCLUDED.resolved_at
                    """
                ),
                {**parameters, "field_code": field_code, "source_path": source_path},
            )
        if parameters["description_path"] is None:
            connection.execute(
                text(
                    """
                    DELETE FROM field_lineage
                    WHERE opportunity_id = :opportunity_id
                      AND field_code = 'EVENT_DESCRIPTION'
                    """
                ),
                parameters,
            )

    @staticmethod
    def _project_periods(
        connection: Connection,
        event_id: UUID,
        observation_id: UUID,
        periods: tuple[_Period, ...],
        now: datetime,
    ) -> bool:
        current_set_id = connection.execute(
            text(
                """
                SELECT id FROM event_period_set
                WHERE event_id = :event_id AND layer = 'SOURCE' AND is_current
                FOR UPDATE
                """
            ),
            {"event_id": event_id},
        ).scalar_one_or_none()
        if current_set_id is not None:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT display_order, source_path, start_date, end_date,
                           start_time, end_time, precision, interpretation_timezone
                    FROM event_period
                    WHERE period_set_id = :set_id
                    ORDER BY display_order
                    """
                    ),
                    {"set_id": current_set_id},
                )
                .mappings()
                .all()
            )
            before = tuple(
                (
                    row["source_path"],
                    row["start_date"],
                    row["end_date"],
                    row["start_time"],
                    row["end_time"],
                    row["precision"],
                    row["interpretation_timezone"],
                )
                for row in rows
            )
            after = tuple(
                (
                    f"periods[{period['source_index'] - 1}]",
                    period["start_date"],
                    period["end_date"],
                    period["start_time"],
                    period["end_time"],
                    period["precision"],
                    period["interpretation_timezone"],
                )
                for period in periods
            )
            if before == after:
                return False
            connection.execute(
                text(
                    """
                    UPDATE event_period_set SET is_current = FALSE, retired_at = :now
                    WHERE id = :set_id
                    """
                ),
                {"set_id": current_set_id, "now": now},
            )
        set_id = uuid4()
        connection.execute(
            text(
                """
                INSERT INTO event_period_set (
                    id, event_id, layer, source_observation_id,
                    is_current, created_at
                ) VALUES (:set_id, :event_id, 'SOURCE', :observation_id, TRUE, :now)
                """
            ),
            {"set_id": set_id, "event_id": event_id, "observation_id": observation_id, "now": now},
        )
        for order, period in enumerate(periods):
            connection.execute(
                text(
                    """
                    INSERT INTO event_period (
                        id, period_set_id, display_order, start_date, end_date,
                        start_time, end_time, interpretation_timezone, precision,
                        source_path, created_at
                    ) VALUES (
                        :id, :set_id, :display_order, :start_date, :end_date,
                        :start_time, :end_time, :timezone, :precision,
                        :source_path, :now
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "set_id": set_id,
                    "display_order": order,
                    "start_date": period["start_date"],
                    "end_date": period["end_date"],
                    "start_time": period["start_time"],
                    "end_time": period["end_time"],
                    "timezone": period["interpretation_timezone"],
                    "precision": period["precision"],
                    "source_path": f"periods[{period['source_index'] - 1}]",
                    "now": now,
                },
            )
        return True

    @staticmethod
    def _decide(
        connection: Connection,
        item_id: UUID,
        opportunity_id: UUID | None,
        decision: str,
        code: str,
        now: datetime,
    ) -> None:
        changed = connection.execute(
            text(
                """
                UPDATE collection_item SET
                    opportunity_id = :opportunity_id,
                    decision = :decision,
                    reason = reason || jsonb_build_object('projection_code', CAST(:code AS text)),
                    updated_at = :now
                WHERE id = :item_id AND decision IS NULL
                """
            ),
            {
                "item_id": item_id,
                "opportunity_id": opportunity_id,
                "decision": decision,
                "code": code,
                "now": now,
            },
        ).rowcount
        if changed != 1:
            raise EventProjectionError("DATAtourisme event decision was already changed")

    @staticmethod
    def _uri_is_claimed(connection: Connection, identity_id: UUID, uri: object) -> bool:
        claimed = connection.execute(
            text(
                """
                SELECT 1 FROM source_observation
                WHERE data_source_code = :source_code
                  AND source_reference = :uri
                  AND external_identity_id <> :identity_id
                  AND redacted_at IS NULL
                LIMIT 1
                """
            ),
            {
                "source_code": DATATOURISME_DATA_SOURCE_CODE,
                "uri": uri,
                "identity_id": identity_id,
            },
        ).scalar_one_or_none()
        return claimed is not None

    @staticmethod
    def _identity_was_quarantined(connection: Connection, identity_id: UUID) -> bool:
        quarantined = connection.execute(
            text(
                """
                SELECT 1 FROM collection_item
                WHERE external_identity_id = :identity_id
                  AND normalization_result = 'IDENTITY_CONFLICT'
                LIMIT 1
                """
            ),
            {"identity_id": identity_id},
        ).scalar_one_or_none()
        return quarantined is not None

    @staticmethod
    def _quarantine_identity_conflict(
        connection: Connection,
        item: RowMapping,
        code: str,
        now: datetime,
    ) -> None:
        if item["validation_status"] != "IDENTITY_CONFLICT":
            observation = (
                connection.execute(
                    text(
                        """
                        SELECT source_binding_id, validation_status
                        FROM source_observation WHERE id = :observation_id
                        FOR UPDATE
                        """
                    ),
                    {"observation_id": item["source_observation_id"]},
                )
                .mappings()
                .one_or_none()
            )
            if observation is None or observation["validation_status"] != "VALID":
                raise EventProjectionError("DATAtourisme conflict observation is unavailable")
            # A revision already published by a binding remains immutable. Its
            # occurrence is quarantined; a newly staged revision is marked too.
            if observation["source_binding_id"] is None:
                connection.execute(
                    text(
                        """
                    UPDATE source_observation
                    SET validation_status = 'IDENTITY_CONFLICT',
                        normalization_error = jsonb_build_object('code', CAST(:code AS text))
                    WHERE id = :observation_id AND validation_status = 'VALID'
                      AND source_binding_id IS NULL
                    """
                    ),
                    {"observation_id": item["source_observation_id"], "code": code},
                )
        decided = connection.execute(
            text(
                """
                UPDATE collection_item SET
                    normalization_result = 'IDENTITY_CONFLICT',
                    decision = 'ERROR',
                    reason = reason || jsonb_build_object(
                        'projection_code', CAST(:code AS text)
                    ),
                    updated_at = :now
                WHERE id = :item_id AND decision IS NULL
                """
            ),
            {"item_id": item["id"], "code": code, "now": now},
        ).rowcount
        if decided != 1:
            raise EventProjectionError("DATAtourisme identity conflict was already decided")

    def summary(self, reservation: ReservedCollection) -> EventProjectionSummary:
        try:
            with self._engine.connect() as connection:
                self._require_ready(connection, reservation)
                row = (
                    connection.execute(
                        text(
                            """
                        SELECT
                            count(*) AS requested_count,
                            count(*) FILTER (WHERE item.decision = 'CREATED') AS created_count,
                            count(*) FILTER (WHERE item.decision = 'UPDATED') AS updated_count,
                            count(*) FILTER (WHERE item.decision = 'UNCHANGED') AS unchanged_count,
                            count(*) FILTER (WHERE item.decision = 'REJECTED') AS rejected_count,
                            count(*) FILTER (WHERE item.decision = 'COUNTED_ONLY') AS counted_only_count,
                            count(*) FILTER (WHERE item.decision = 'ERROR'
                              AND item.normalization_result = 'IDENTITY_CONFLICT')
                                AS identity_conflict_count,
                            count(*) FILTER (WHERE item.decision IS NULL OR
                                (item.decision = 'ERROR' AND item.normalization_result
                                 <> 'IDENTITY_CONFLICT'))
                                AS undecided_count
                        FROM collection_item AS item
                        JOIN collection_batch AS batch
                          ON batch.id = item.collection_batch_id
                         AND batch.last_collection_attempt_id = item.collection_attempt_id
                         AND batch.state = 'SUCCEEDED'
                        WHERE item.collection_cycle_id = :cycle_id
                          AND item.authority = 'DATATOURISME'
                          AND item.namespace = 'DATATOURISME_UUID'
                        """
                        ),
                        {"cycle_id": reservation.cycle_id},
                    )
                    .mappings()
                    .one()
                )
        except EventProjectionError:
            raise
        except SQLAlchemyError as error:
            raise EventProjectionError("cannot reconcile DATAtourisme event decisions") from error
        if row["undecided_count"]:
            raise EventProjectionError("DATAtourisme event projection has undecided candidates")
        summary = EventProjectionSummary(
            requested_count=row["requested_count"],
            created_count=row["created_count"],
            updated_count=row["updated_count"],
            unchanged_count=row["unchanged_count"],
            rejected_count=row["rejected_count"],
            counted_only_count=row["counted_only_count"],
            identity_conflict_count=row["identity_conflict_count"],
        )
        summary.validate()
        return summary


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
