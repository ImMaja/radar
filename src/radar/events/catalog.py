"""Typed local read model for visible event opportunities."""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal, Protocol
from uuid import UUID

EventSort = Literal["date", "distance"]
EventDirection = Literal["asc", "desc"]
EventTemporalState = Literal["UPCOMING", "ONGOING"]
EventDeclaredStatus = Literal["SCHEDULED", "POSTPONED", "CANCELLED", "UNKNOWN"]
EventContactType = Literal["EMAIL", "PHONE", "WEBSITE", "BOOKING_URL", "CONTACT_RELAY"]
EventContactScope = Literal["LOCAL", "CENTRAL", "UNKNOWN"]


@dataclass(frozen=True)
class EventSearch:
    """Local filters; a provider call is never part of a catalogue read."""

    text: str | None = None
    max_distance_meters: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    category: str | None = None
    organizer: str | None = None
    has_contact: bool = False
    declared_status: EventDeclaredStatus | None = None
    sort: EventSort = "date"
    direction: EventDirection = "asc"
    limit: int = 25
    offset: int = 0


@dataclass(frozen=True)
class EventSummary:
    """One visible event and its next relevant occurrence."""

    id: UUID
    title: str
    types: tuple[str, ...]
    organizer_name: str | None
    declared_status: EventDeclaredStatus
    temporal_state: EventTemporalState
    next_start_at: datetime
    full_address: str | None
    municipality: str | None
    distance_meters: float | None
    has_contact: bool
    last_observed_at: datetime


@dataclass(frozen=True)
class EventPage:
    """One bounded page and the exact radius used for its local query."""

    items: tuple[EventSummary, ...]
    total: int
    limit: int
    offset: int
    applied_radius_meters: int


@dataclass(frozen=True)
class EventPeriod:
    """One period from the effective SOURCE or USER calendar."""

    start_date: date
    end_date: date
    start_time: time | None
    end_time: time | None
    precision: str
    source_path: str


@dataclass(frozen=True)
class EventContact:
    """One effective professional contact with a non-inferred scope."""

    type: EventContactType
    value: str
    scope: EventContactScope
    label: str | None
    source_reference: str | None


@dataclass(frozen=True)
class EventSource:
    """Current source binding and observation freshness."""

    code: str
    name: str
    authority: str
    state: str
    first_observed_at: datetime
    last_observed_at: datetime
    retrieved_at: datetime
    source_updated_at: datetime | None


@dataclass(frozen=True)
class EventDetail:
    """Read-only event fiche without CRM or scoring fields not yet implemented."""

    summary: EventSummary
    description: str | None
    source_uri: str | None
    period_layer: Literal["SOURCE", "USER"]
    periods: tuple[EventPeriod, ...]
    longitude: float | None
    latitude: float | None
    contacts: tuple[EventContact, ...]
    sources: tuple[EventSource, ...]


class EventCatalogBackend(Protocol):
    """Web-facing reads from local PostgreSQL/PostGIS data only."""

    def search(self, query: EventSearch) -> EventPage: ...

    def get(self, event_id: UUID) -> EventDetail: ...


class EventNotFoundError(LookupError):
    """The event is absent or not visible in the ordinary catalogue."""


class EventReferencePositionRequiredError(RuntimeError):
    """A distance-filtered list needs a confirmed center."""


class EventCatalogUnavailableError(RuntimeError):
    """The local event catalogue cannot currently be queried."""


class UnavailableEventCatalogBackend:
    """Explicit placeholder for isolated web compositions."""

    def search(self, _query: EventSearch) -> EventPage:
        raise EventCatalogUnavailableError

    def get(self, _event_id: UUID) -> EventDetail:
        raise EventCatalogUnavailableError
