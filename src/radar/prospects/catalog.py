"""Typed read model for Radar's local prospect catalogue."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

ProspectLocationFilter = Literal["located", "to_verify"]
ProspectSort = Literal["distance", "name"]
SortDirection = Literal["asc", "desc"]
ProspectContactType = Literal["EMAIL", "PHONE", "WEBSITE", "BOOKING_URL", "CONTACT_RELAY"]
ProspectContactScope = Literal["LOCAL", "CENTRAL", "UNKNOWN"]


@dataclass(frozen=True)
class ProspectSearch:
    """Validated local filters applied without contacting a provider."""

    text: str | None = None
    max_distance_meters: int | None = None
    organization_type: str | None = None
    activity_code: str | None = None
    employee_band: str | None = None
    has_email: bool = False
    has_phone: bool = False
    has_website: bool = False
    location: ProspectLocationFilter = "located"
    sort: ProspectSort = "distance"
    direction: SortDirection = "asc"
    limit: int = 25
    offset: int = 0


@dataclass(frozen=True)
class ProspectAddress:
    """Effective public address fields useful to the private interface."""

    full_address: str | None
    street_number: str | None
    repetition_index: str | None
    street_type: str | None
    street_label: str | None
    address_complement: str | None
    postcode: str | None
    municipality: str | None
    municipality_code: str | None


@dataclass(frozen=True)
class ProspectSummary:
    """Bounded list projection for one visible and prospectable fiche."""

    id: UUID
    display_name: str
    organization_type: str
    activity_code: str | None
    activity_nomenclature: str | None
    activity_label: str | None
    employee_band: str | None
    employee_year: int | None
    employee_scope: str
    has_email: bool
    has_phone: bool
    has_website: bool
    address: ProspectAddress
    distance_meters: float | None
    location_status: ProspectLocationFilter
    location_precision: str
    last_observed_at: datetime


@dataclass(frozen=True)
class ProspectPage:
    """One deterministic page and the radius actually used by the query."""

    items: tuple[ProspectSummary, ...]
    total: int
    limit: int
    offset: int
    applied_radius_meters: int


@dataclass(frozen=True)
class ProspectSource:
    """Non-secret provenance and freshness for a prospect source binding."""

    code: str
    name: str
    authority: str
    producer_name: str | None
    state: str
    first_observed_at: datetime
    last_observed_at: datetime
    retrieved_at: datetime
    source_updated_at: datetime | None


@dataclass(frozen=True)
class ProspectContact:
    """One effective professional contact with its known scope and provenance hint."""

    type: ProspectContactType
    value: str
    scope: ProspectContactScope
    label: str | None
    source_reference: str | None


@dataclass(frozen=True)
class ProspectDetail:
    """Detailed effective values for one prospect fiche."""

    summary: ProspectSummary
    description: str | None
    siret: str | None
    siren: str | None
    legal_name: str | None
    usual_name: str | None
    legal_category: str | None
    is_head_office: bool | None
    eligibility: str
    eligibility_reason: str
    established_on: date | None
    current_period_started_on: date | None
    longitude: float | None
    latitude: float | None
    location_origin: str
    location_quality_code: str | None
    location_match_score: float | None
    first_observed_at: datetime
    contacts: tuple[ProspectContact, ...]
    sources: tuple[ProspectSource, ...]


class ProspectCatalogBackend(Protocol):
    """Web-facing local prospect catalogue operations."""

    def search(self, query: ProspectSearch) -> ProspectPage: ...

    def get(self, prospect_id: UUID) -> ProspectDetail: ...


class ProspectNotFoundError(LookupError):
    """Raised when no readable prospect has the requested identifier."""


class ProspectReferencePositionRequiredError(RuntimeError):
    """Raised when distance-based catalogue reads have no confirmed center."""


class ProspectCatalogUnavailableError(RuntimeError):
    """Raised when the local catalogue cannot currently be queried."""


class UnavailableProspectCatalogBackend:
    """Explicit placeholder used only by isolated application compositions."""

    def search(self, _query: ProspectSearch) -> ProspectPage:
        raise ProspectCatalogUnavailableError

    def get(self, _prospect_id: UUID) -> ProspectDetail:
        raise ProspectCatalogUnavailableError
