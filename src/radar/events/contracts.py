"""Provider-independent event candidates produced by external adapters."""

from dataclasses import dataclass
from typing import Literal

EventContactRole = Literal["GENERAL", "BOOKING"]
EventSourcePartyRole = Literal["CREATOR", "PUBLISHER", "OWNER"]


@dataclass(frozen=True)
class EventAddressCandidate:
    """Published address attached to an event location."""

    streets: tuple[str, ...]
    postcode: str | None
    municipality: str | None
    municipality_code: str | None


@dataclass(frozen=True)
class EventLocationCandidate:
    """Published location without trusting the provider's distance filter."""

    longitude: float | None
    latitude: float | None
    addresses: tuple[EventAddressCandidate, ...]


@dataclass(frozen=True)
class EventPeriodCandidate:
    """One source period whose temporal validity is decided locally later."""

    start_date: str | None
    end_date: str | None
    start_time: str | None
    end_time: str | None


@dataclass(frozen=True)
class EventDescriptionCandidate:
    """French descriptions published for one source object."""

    short: str | None
    full: str | None


@dataclass(frozen=True)
class EventContactCandidate:
    """Professional contact relay without an inferred organizer relationship."""

    role: EventContactRole
    legal_name: str | None
    phones: tuple[str, ...]
    websites: tuple[str, ...]


@dataclass(frozen=True)
class EventSourcePartyCandidate:
    """Source production party retained as provenance, never as organizer."""

    role: EventSourcePartyRole
    identifier: str | None
    legal_name: str | None
    phones: tuple[str, ...]
    websites: tuple[str, ...]


@dataclass(frozen=True)
class EventCandidate:
    """Normalized public event data independent from DATAtourisme's JSON shape."""

    external_identifier: str
    source_uri: str
    producer_identifier: str | None
    title: str
    types: tuple[str, ...]
    descriptions: tuple[EventDescriptionCandidate, ...]
    locations: tuple[EventLocationCandidate, ...]
    periods: tuple[EventPeriodCandidate, ...]
    contacts: tuple[EventContactCandidate, ...]
    source_parties: tuple[EventSourcePartyCandidate, ...]
    source_updated_at: str | None
    aggregator_updated_at: str | None
    source_obsolete: bool | None
