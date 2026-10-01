"""PostgreSQL/PostGIS reads for Radar's ordinary event catalogue."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.events.catalog import (
    EventCatalogUnavailableError,
    EventContact,
    EventContactScope,
    EventContactType,
    EventDeclaredStatus,
    EventDetail,
    EventNotFoundError,
    EventPage,
    EventPeriod,
    EventReferencePositionRequiredError,
    EventSearch,
    EventSource,
    EventSummary,
    EventTemporalState,
)

_EFFECTIVE_CTES = """
effective_period_set AS (
    SELECT DISTINCT ON (period_set.event_id)
        period_set.id, period_set.event_id, period_set.layer
    FROM event_period_set AS period_set
    WHERE period_set.is_current
    ORDER BY period_set.event_id,
             CASE period_set.layer WHEN 'USER' THEN 0 ELSE 1 END
),
effective_period AS (
    SELECT period_set.event_id, period.start_date,
           COALESCE(period.end_date, period.start_date) AS end_date,
           (period.start_date + COALESCE(period.start_time, TIME '00:00:00'))
             AT TIME ZONE 'Europe/Paris' AS start_at,
           (COALESCE(period.end_date, period.start_date)
             + COALESCE(period.end_time, TIME '23:59:59.999999'))
             AT TIME ZONE 'Europe/Paris' AS end_at
    FROM effective_period_set AS period_set
    JOIN event_period AS period ON period.period_set_id = period_set.id
),
event_times AS (
    SELECT period.event_id,
           bool_or(period.start_at <= :now AND period.end_at >= :now) AS is_ongoing,
           min(period.start_at) FILTER (WHERE period.end_at >= :now) AS next_start_at
    FROM effective_period AS period
    GROUP BY period.event_id
),
effective_location AS (
    SELECT DISTINCT ON (location.opportunity_id) location.*
    FROM location_assertion AS location
    WHERE location.is_current
    ORDER BY location.opportunity_id,
             CASE location.layer WHEN 'USER' THEN 0 ELSE 1 END
),
effective_contact_set AS (
    SELECT DISTINCT ON (contact_set.opportunity_id)
        contact_set.id, contact_set.opportunity_id
    FROM contact_set
    WHERE contact_set.is_current
    ORDER BY contact_set.opportunity_id,
             CASE contact_set.layer WHEN 'USER' THEN 0 ELSE 1 END
),
effective_contacts AS (
    SELECT contact_set.opportunity_id,
           count(contact.id) > 0 AS has_contact
    FROM effective_contact_set AS contact_set
    LEFT JOIN contact_point AS contact ON contact.contact_set_id = contact_set.id
    GROUP BY contact_set.opportunity_id
)
"""

_VISIBLE_FROM = """
FROM event
JOIN opportunity ON opportunity.id = event.id
 AND opportunity.kind = 'EVENT' AND opportunity.hidden_at IS NULL
JOIN event_times AS times ON times.event_id = event.id
JOIN effective_location AS location ON location.opportunity_id = event.id
LEFT JOIN effective_contacts AS contacts ON contacts.opportunity_id = event.id
JOIN reference_position AS reference ON reference.id = :reference_position_id
WHERE times.next_start_at IS NOT NULL
  AND location.usability = 'USABLE' AND location.point IS NOT NULL
  AND ST_DWithin(location.point, reference.point, :radius_meters)
  AND (CAST(:declared_status AS text) IS NOT NULL
       OR event.declared_status <> 'CANCELLED')
  AND (CAST(:declared_status AS text) IS NULL
       OR event.declared_status = :declared_status)
  AND (CAST(:search_pattern AS text) IS NULL
       OR event.source_title ILIKE :search_pattern ESCAPE '\\'
       OR COALESCE(location.structured_address #>> '{municipality_label}',
                   location.structured_address #>> '{addresses,0,municipality}')
            ILIKE :search_pattern ESCAPE '\\'
       OR location.full_address ILIKE :search_pattern ESCAPE '\\')
  AND (CAST(:category AS text) IS NULL
       OR event.source_types @> jsonb_build_array(CAST(:category AS text)))
  AND (CAST(:organizer_pattern AS text) IS NULL
       OR event.organizer_name ILIKE :organizer_pattern ESCAPE '\\')
  AND (NOT CAST(:has_contact AS boolean) OR COALESCE(contacts.has_contact, FALSE))
  AND (
      CAST(:date_from AS date) IS NULL AND CAST(:date_to AS date) IS NULL
      OR EXISTS (
          SELECT 1 FROM effective_period AS period
          WHERE period.event_id = event.id
            AND (CAST(:date_from AS date) IS NULL OR period.end_date >= :date_from)
            AND (CAST(:date_to AS date) IS NULL OR period.start_date <= :date_to)
      )
  )
"""

_LIST_COLUMNS = """
SELECT event.id, event.source_title, event.source_types,
       event.organizer_name, event.declared_status,
       CASE WHEN times.is_ongoing THEN 'ONGOING' ELSE 'UPCOMING' END
         AS temporal_state,
       times.next_start_at, location.full_address,
       COALESCE(location.structured_address #>> '{municipality_label}',
                location.structured_address #>> '{addresses,0,municipality}')
         AS municipality,
       ST_Distance(location.point, reference.point) AS distance_meters,
       COALESCE(contacts.has_contact, FALSE) AS has_contact,
       event.last_observed_at
"""

_ORDER_BY = """
ORDER BY
    CASE WHEN CAST(:sort AS text) = 'date' AND CAST(:direction AS text) = 'asc'
         THEN times.next_start_at END ASC NULLS LAST,
    CASE WHEN CAST(:sort AS text) = 'date' AND CAST(:direction AS text) = 'desc'
         THEN times.next_start_at END DESC NULLS LAST,
    CASE WHEN CAST(:sort AS text) = 'distance' AND CAST(:direction AS text) = 'asc'
         THEN ST_Distance(location.point, reference.point) END ASC NULLS LAST,
    CASE WHEN CAST(:sort AS text) = 'distance' AND CAST(:direction AS text) = 'desc'
         THEN ST_Distance(location.point, reference.point) END DESC NULLS LAST,
    times.next_start_at ASC, event.id ASC
"""


def utc_now() -> datetime:
    """Return an aware UTC instant for time-sensitive catalogue reads."""

    return datetime.now(UTC)


class SqlAlchemyEventCatalogRepository:
    """Apply bounded filters to effective local event values only."""

    def __init__(self, engine: Engine, clock: Callable[[], datetime] = utc_now) -> None:
        self._engine = engine
        self._clock = clock

    def search(self, query: EventSearch) -> EventPage:
        """List nonhidden, nonpast, locally positioned events in one radius."""

        try:
            with self._engine.connect() as connection:
                reference_id, configured_radius = self._reference_settings(connection)
                applied_radius = query.max_distance_meters or configured_radius
                parameters = self._search_parameters(
                    query, reference_id, applied_radius, self._clock()
                )
                total = connection.execute(
                    text(f"WITH {_EFFECTIVE_CTES} SELECT count(*) {_VISIBLE_FROM}"),
                    parameters,
                ).scalar_one()
                rows = connection.execute(
                    text(
                        f"WITH {_EFFECTIVE_CTES} {_LIST_COLUMNS} "
                        f"{_VISIBLE_FROM} {_ORDER_BY} LIMIT :limit OFFSET :offset"
                    ),
                    parameters,
                ).mappings()
                items = tuple(self._summary(row) for row in rows)
        except (EventReferencePositionRequiredError, ValueError):
            raise
        except SQLAlchemyError as error:
            raise EventCatalogUnavailableError("cannot query local events") from error
        return EventPage(items, int(total), query.limit, query.offset, applied_radius)

    def get(self, event_id: UUID) -> EventDetail:
        """Read one nonhidden, nonpast fiche regardless of the active radius."""

        try:
            with self._engine.connect() as connection:
                row = (
                    connection.execute(
                        text(
                            f"""
                            WITH {_EFFECTIVE_CTES},
                            current_reference AS (
                                SELECT reference.point
                                FROM application_setting AS settings
                                JOIN reference_position AS reference
                                  ON reference.id = settings.current_reference_position_id
                                WHERE settings.singleton_key = 'primary'
                            )
                            SELECT event.id, event.source_title, event.source_description,
                                   event.source_types, event.organizer_name,
                                   event.declared_status, event.source_uri,
                                   event.last_observed_at, period_set.id AS period_set_id,
                                   period_set.layer AS period_layer,
                                   CASE WHEN times.is_ongoing THEN 'ONGOING'
                                        ELSE 'UPCOMING' END AS temporal_state,
                                   times.next_start_at,
                                   location.full_address,
                                   COALESCE(
                                       location.structured_address #>> '{{municipality_label}}',
                                       location.structured_address
                                         #>> '{{addresses,0,municipality}}'
                                   )
                                     AS municipality,
                                   CASE WHEN location.point IS NOT NULL
                                        AND reference.point IS NOT NULL
                                        THEN ST_Distance(location.point, reference.point)
                                        ELSE NULL END AS distance_meters,
                                   CASE WHEN location.point IS NOT NULL
                                        THEN ST_X(location.point::geometry)
                                        ELSE NULL END AS longitude,
                                   CASE WHEN location.point IS NOT NULL
                                        THEN ST_Y(location.point::geometry)
                                        ELSE NULL END AS latitude,
                                   COALESCE(contacts.has_contact, FALSE) AS has_contact
                            FROM event
                            JOIN opportunity ON opportunity.id = event.id
                              AND opportunity.kind = 'EVENT'
                              AND opportunity.hidden_at IS NULL
                            JOIN event_times AS times ON times.event_id = event.id
                            JOIN effective_period_set AS period_set
                              ON period_set.event_id = event.id
                            LEFT JOIN effective_location AS location
                              ON location.opportunity_id = event.id
                            LEFT JOIN effective_contacts AS contacts
                              ON contacts.opportunity_id = event.id
                            LEFT JOIN current_reference AS reference ON TRUE
                            WHERE event.id = :event_id
                              AND times.next_start_at IS NOT NULL
                            """
                        ),
                        {"event_id": event_id, "now": self._clock()},
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise EventNotFoundError
                periods = self._periods(connection, cast(UUID, row["period_set_id"]))
                contacts = self._contacts(connection, event_id)
                sources = self._sources(connection, event_id)
                return EventDetail(
                    summary=self._summary(row),
                    description=cast(str | None, row["source_description"]),
                    source_uri=cast(str | None, row["source_uri"]),
                    period_layer=cast(Literal["SOURCE", "USER"], row["period_layer"]),
                    periods=periods,
                    longitude=(float(row["longitude"]) if row["longitude"] is not None else None),
                    latitude=(float(row["latitude"]) if row["latitude"] is not None else None),
                    contacts=contacts,
                    sources=sources,
                )
        except EventNotFoundError:
            raise
        except SQLAlchemyError as error:
            raise EventCatalogUnavailableError("cannot read local event") from error

    @staticmethod
    def _reference_settings(connection: Connection) -> tuple[UUID, int]:
        row = connection.execute(
            text(
                """
                SELECT current_reference_position_id, search_radius_meters
                FROM application_setting WHERE singleton_key = 'primary'
                """
            )
        ).one_or_none()
        if row is None or not isinstance(row[0], UUID):
            raise EventReferencePositionRequiredError
        return row[0], int(row[1])

    @staticmethod
    def _like_pattern(value: str | None) -> str | None:
        if value is None:
            return None
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    @classmethod
    def _search_parameters(
        cls, query: EventSearch, reference_id: UUID, radius: int, now: datetime
    ) -> dict[str, object]:
        if not 1 <= radius <= 50_000:
            raise ValueError("event search radius must be between 1 and 50000 metres")
        if not 1 <= query.limit <= 100 or query.offset < 0:
            raise ValueError("event pagination is outside its accepted bounds")
        if query.date_from is not None and query.date_to is not None:
            if query.date_to < query.date_from:
                raise ValueError("event date range is reversed")
        return {
            "reference_position_id": reference_id,
            "radius_meters": radius,
            "now": now,
            "search_pattern": cls._like_pattern(query.text),
            "date_from": query.date_from,
            "date_to": query.date_to,
            "category": query.category,
            "organizer_pattern": cls._like_pattern(query.organizer),
            "has_contact": query.has_contact,
            "declared_status": query.declared_status,
            "sort": query.sort,
            "direction": query.direction,
            "limit": query.limit,
            "offset": query.offset,
        }

    @staticmethod
    def _summary(row: RowMapping) -> EventSummary:
        return EventSummary(
            id=cast(UUID, row["id"]),
            title=cast(str, row["source_title"]),
            types=tuple(cast(list[str], row["source_types"] or [])),
            organizer_name=cast(str | None, row["organizer_name"]),
            declared_status=cast(EventDeclaredStatus, row["declared_status"]),
            temporal_state=cast(EventTemporalState, row["temporal_state"]),
            next_start_at=cast(datetime, row["next_start_at"]),
            full_address=cast(str | None, row["full_address"]),
            municipality=cast(str | None, row["municipality"]),
            distance_meters=(
                float(row["distance_meters"]) if row["distance_meters"] is not None else None
            ),
            has_contact=cast(bool, row["has_contact"]),
            last_observed_at=cast(datetime, row["last_observed_at"]),
        )

    @staticmethod
    def _periods(connection: Connection, period_set_id: UUID) -> tuple[EventPeriod, ...]:
        rows = connection.execute(
            text(
                """
                SELECT start_date, COALESCE(end_date, start_date) AS end_date,
                       start_time, end_time, precision, source_path
                FROM event_period
                WHERE period_set_id = :period_set_id
                ORDER BY display_order
                """
            ),
            {"period_set_id": period_set_id},
        ).mappings()
        return tuple(
            EventPeriod(
                start_date=cast(date, row["start_date"]),
                end_date=cast(date, row["end_date"]),
                start_time=cast(time | None, row["start_time"]),
                end_time=cast(time | None, row["end_time"]),
                precision=cast(str, row["precision"]),
                source_path=cast(str, row["source_path"]),
            )
            for row in rows
        )

    @staticmethod
    def _contacts(connection: Connection, event_id: UUID) -> tuple[EventContact, ...]:
        rows = connection.execute(
            text(
                """
                SELECT contact.type, contact.display_value, contact.scope,
                       contact.label, contact.source_reference
                FROM contact_point AS contact
                WHERE contact.contact_set_id = (
                    SELECT contact_set.id FROM contact_set
                    WHERE contact_set.opportunity_id = :event_id
                      AND contact_set.is_current
                    ORDER BY CASE contact_set.layer WHEN 'USER' THEN 0 ELSE 1 END
                    LIMIT 1
                )
                ORDER BY contact.display_order, contact.type
                """
            ),
            {"event_id": event_id},
        ).mappings()
        return tuple(
            EventContact(
                type=cast(EventContactType, row["type"]),
                value=cast(str, row["display_value"]),
                scope=cast(EventContactScope, row["scope"]),
                label=cast(str | None, row["label"]),
                source_reference=cast(str | None, row["source_reference"]),
            )
            for row in rows
        )

    @staticmethod
    def _sources(connection: Connection, event_id: UUID) -> tuple[EventSource, ...]:
        rows = connection.execute(
            text(
                """
                SELECT source.code, source.name, source.authority, binding.state,
                       binding.first_observed_at, binding.last_observed_at,
                       observation.retrieved_at, observation.source_updated_at
                FROM source_binding AS binding
                JOIN data_source AS source ON source.code = binding.data_source_code
                JOIN source_observation AS observation
                  ON observation.id = binding.current_observation_id
                WHERE binding.opportunity_id = :event_id
                ORDER BY source.code
                """
            ),
            {"event_id": event_id},
        ).mappings()
        return tuple(
            EventSource(
                code=cast(str, row["code"]),
                name=cast(str, row["name"]),
                authority=cast(str, row["authority"]),
                state=cast(str, row["state"]),
                first_observed_at=cast(datetime, row["first_observed_at"]),
                last_observed_at=cast(datetime, row["last_observed_at"]),
                retrieved_at=cast(datetime, row["retrieved_at"]),
                source_updated_at=cast(datetime | None, row["source_updated_at"]),
            )
            for row in rows
        )
