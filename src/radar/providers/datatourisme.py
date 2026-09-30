"""Strict read-only adapter for the DATAtourisme v1 event API."""

import hashlib
import math
import random
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import UUID

import httpx2 as httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from radar.events.contracts import (
    EventAddressCandidate,
    EventCandidate,
    EventContactCandidate,
    EventContactRole,
    EventDescriptionCandidate,
    EventLocationCandidate,
    EventPeriodCandidate,
    EventSourcePartyCandidate,
    EventSourcePartyRole,
)

DATATOURISME_ORIGIN = "https://api.datatourisme.fr"
EVENT_PATH = "/v1/entertainmentAndEvent"
EVENT_URL = f"{DATATOURISME_ORIGIN}{EVENT_PATH}"
API_KEY_HEADER = "X-API-Key"
PAGE_SIZE = 100
MAX_RESPONSE_BYTES = 25_000_000
MIN_REQUEST_INTERVAL_SECONDS = 0.2
MAX_HTTP_ATTEMPTS = 4
MAX_IN_PROCESS_RETRY_SECONDS = 60
MAX_RECORDED_RETRY_AFTER_SECONDS = 86_400

EVENT_FIELDS: tuple[str, ...] = (
    "uuid",
    "uri",
    "identifier",
    "label",
    "type",
    "isLocatedAt",
    "hasDescription",
    "takesPlaceAt",
    "hasContact",
    "hasBookingContact",
    "hasBeenCreatedBy",
    "hasBeenPublishedBy",
    "isOwnedBy",
    "lastUpdate",
    "lastUpdateDatatourisme",
    "isObsolete",
)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100_000)]


class DatatourismeAdapterError(RuntimeError):
    """Base class for controlled failures that never include the API key."""


class DatatourismeRequestError(DatatourismeAdapterError):
    """The request or pagination link is invalid and must not be retried unchanged."""


class DatatourismeAuthenticationError(DatatourismeAdapterError):
    """The configured API key cannot access DATAtourisme."""


class DatatourismeTemporaryError(DatatourismeAdapterError):
    """The provider or network is temporarily unavailable."""

    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class DatatourismeContractError(DatatourismeAdapterError):
    """The provider response no longer satisfies the validated contract."""


class _DatatourismeModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _LocalizedText(_DatatourismeModel):
    french: LongText | None = Field(default=None, alias="@fr")


class _AddressCity(_DatatourismeModel):
    insee: ShortText | None = None


class _Address(_DatatourismeModel):
    streets: list[ShortText] = Field(default_factory=list, alias="streetAddress", max_length=20)
    postcode: ShortText | None = Field(default=None, alias="postalCode")
    municipality: ShortText | None = Field(default=None, alias="addressLocality")
    city: _AddressCity | None = Field(default=None, alias="hasAddressCity")


class _GeoPoint(_DatatourismeModel):
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)


class _Location(_DatatourismeModel):
    geo: _GeoPoint | None = None
    addresses: list[_Address] = Field(default_factory=list, alias="address", max_length=20)


class _Period(_DatatourismeModel):
    start_date: ShortText | None = Field(default=None, alias="startDate")
    end_date: ShortText | None = Field(default=None, alias="endDate")
    start_time: ShortText | None = Field(default=None, alias="startTime")
    end_time: ShortText | None = Field(default=None, alias="endTime")


class _Description(_DatatourismeModel):
    short: _LocalizedText | None = Field(default=None, alias="shortDescription")
    full: _LocalizedText | None = Field(default=None, alias="description")

    @field_validator("short", "full", mode="before")
    @classmethod
    def empty_list_is_missing(cls, value: object) -> object:
        """Accept only the provider's observed empty-list representation of absence."""

        return None if value == [] else value


class _Contact(_DatatourismeModel):
    legal_name: ShortText | None = Field(default=None, alias="legalName")
    phones: list[ShortText] = Field(default_factory=list, alias="telephone", max_length=50)
    websites: list[ShortText] = Field(default_factory=list, alias="homepage", max_length=50)


class _SourceParty(_Contact):
    identifier: ShortText | None = None


class _EventObject(_DatatourismeModel):
    uuid: UUID
    uri: ShortText = Field(min_length=1)
    identifier: ShortText | None = None
    label: _LocalizedText
    types: list[ShortText] = Field(default_factory=list, alias="type", max_length=100)
    locations: list[_Location] = Field(default_factory=list, alias="isLocatedAt", max_length=20)
    descriptions: list[_Description] = Field(
        default_factory=list,
        alias="hasDescription",
        max_length=20,
    )
    periods: list[_Period] = Field(default_factory=list, alias="takesPlaceAt", max_length=10_000)
    contacts: list[_Contact] = Field(default_factory=list, alias="hasContact", max_length=100)
    booking_contacts: list[_Contact] = Field(
        default_factory=list,
        alias="hasBookingContact",
        max_length=100,
    )
    creator: _SourceParty | None = Field(default=None, alias="hasBeenCreatedBy")
    publishers: list[_SourceParty] = Field(
        default_factory=list,
        alias="hasBeenPublishedBy",
        max_length=100,
    )
    owners: list[_SourceParty] = Field(default_factory=list, alias="isOwnedBy", max_length=100)
    source_updated_at: ShortText | None = Field(default=None, alias="lastUpdate")
    aggregator_updated_at: ShortText | None = Field(
        default=None,
        alias="lastUpdateDatatourisme",
    )
    obsolete: bool | None = Field(default=None, alias="isObsolete")


class _Metadata(_DatatourismeModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=PAGE_SIZE)
    total_pages: int = Field(ge=0)
    next: str | None = Field(default=None, max_length=100_000)


class _EventResponse(_DatatourismeModel):
    objects: list[_EventObject] = Field(max_length=PAGE_SIZE)
    meta: _Metadata


@dataclass(frozen=True)
class DatatourismePage:
    """One validated page without raw payload or executable navigation link."""

    number: int
    announced_total: int
    announced_total_pages: int
    received_count: int
    importable_candidates: tuple[EventCandidate, ...]
    rejection_counts: dict[str, int]
    next_link_fingerprint: str | None
    terminal: bool


@dataclass(frozen=True)
class DatatourismeCollectionSummary:
    """Completeness evidence for one geographic event enumeration."""

    announced_total: int
    received_count: int
    unique_uuid_count: int
    importable_count: int
    page_count: int
    rejection_counts: dict[str, int]


@dataclass(frozen=True)
class _SafePaginationRequest:
    url: str
    params: tuple[tuple[str, str], ...]
    fingerprint: str


def _parse_retry_after(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    if len(value) > 5:
        return MAX_RECORDED_RETRY_AFTER_SECONDS
    return min(int(value), MAX_RECORDED_RETRY_AFTER_SECONDS)


def _non_empty(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(value for value in values if value)


def _contact(contact: _Contact, role: EventContactRole) -> EventContactCandidate:
    return EventContactCandidate(
        role,
        contact.legal_name,
        _non_empty(contact.phones),
        _non_empty(contact.websites),
    )


def _party(party: _SourceParty, role: EventSourcePartyRole) -> EventSourcePartyCandidate:
    return EventSourcePartyCandidate(
        role,
        party.identifier,
        party.legal_name,
        _non_empty(party.phones),
        _non_empty(party.websites),
    )


def _normalize_candidate(item: _EventObject) -> tuple[EventCandidate | None, str | None]:
    title = item.label.french
    if title is None or not title:
        return None, "missing_french_title"

    source_parties: list[EventSourcePartyCandidate] = []
    if item.creator is not None:
        source_parties.append(_party(item.creator, "CREATOR"))
    source_parties.extend(_party(publisher, "PUBLISHER") for publisher in item.publishers)
    source_parties.extend(_party(owner, "OWNER") for owner in item.owners)

    return (
        EventCandidate(
            external_identifier=str(item.uuid),
            source_uri=item.uri,
            producer_identifier=item.identifier,
            title=title,
            types=_non_empty(item.types),
            descriptions=tuple(
                EventDescriptionCandidate(
                    description.short.french if description.short is not None else None,
                    description.full.french if description.full is not None else None,
                )
                for description in item.descriptions
            ),
            locations=tuple(
                EventLocationCandidate(
                    location.geo.longitude if location.geo is not None else None,
                    location.geo.latitude if location.geo is not None else None,
                    tuple(
                        EventAddressCandidate(
                            _non_empty(address.streets),
                            address.postcode,
                            address.municipality,
                            address.city.insee if address.city is not None else None,
                        )
                        for address in location.addresses
                    ),
                )
                for location in item.locations
            ),
            periods=tuple(
                EventPeriodCandidate(
                    period.start_date,
                    period.end_date,
                    period.start_time,
                    period.end_time,
                )
                for period in item.periods
            ),
            contacts=tuple(_contact(contact, "GENERAL") for contact in item.contacts)
            + tuple(_contact(contact, "BOOKING") for contact in item.booking_contacts),
            source_parties=tuple(source_parties),
            source_updated_at=item.source_updated_at,
            aggregator_updated_at=item.aggregator_updated_at,
            source_obsolete=item.obsolete,
        ),
        None,
    )


def _safe_pagination_request(
    value: str,
    invariant_params: Mapping[str, str],
) -> _SafePaginationRequest:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise DatatourismeContractError("the DATAtourisme next link is invalid") from error

    if parsed.fragment or parsed.username is not None or parsed.password is not None:
        raise DatatourismeContractError("the DATAtourisme next link is unsafe")
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != "https" or parsed.hostname != "api.datatourisme.fr":
            raise DatatourismeContractError("the DATAtourisme next link changed origin")
        if port not in {None, 443}:
            raise DatatourismeContractError("the DATAtourisme next link uses an unexpected port")
    if parsed.path != EVENT_PATH:
        raise DatatourismeContractError("the DATAtourisme next link changed path")

    params = tuple(
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if name.lower() != "api_key"
    )
    if not params:
        raise DatatourismeContractError("the DATAtourisme next link has no query")
    values_by_name: dict[str, list[str]] = {}
    for name, parameter_value in params:
        values_by_name.setdefault(name, []).append(parameter_value)
    allowed_names = set(invariant_params) | {"crs"}
    if set(values_by_name) != allowed_names:
        raise DatatourismeContractError("the DATAtourisme next link changed query parameters")
    if len(values_by_name["crs"]) != 1 or not values_by_name["crs"][0]:
        raise DatatourismeContractError("the DATAtourisme next link has no cursor")
    for name, expected_value in invariant_params.items():
        if values_by_name.get(name) != [expected_value]:
            raise DatatourismeContractError(
                "the DATAtourisme next link changed collection parameters"
            )
    canonical = f"{EVENT_URL}?{urlencode(params)}"
    return _SafePaginationRequest(
        EVENT_URL,
        params,
        hashlib.sha256(canonical.encode()).hexdigest(),
    )


class DatatourismeClient:
    """Read and validate a complete DATAtourisme event enumeration."""

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = lambda: random.uniform(0, 0.25),
    ) -> None:
        if not api_key:
            raise ValueError("the DATAtourisme API key cannot be empty")
        self._owns_client = client is None
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._jitter = jitter
        self._next_request_at = 0.0
        self._request_headers = {
            API_KEY_HEADER: api_key,
            "Accept": "application/json",
            "User-Agent": "Radar/0.1 (private food-truck opportunity application)",
        }
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=10, read=60, write=30, pool=10),
            follow_redirects=False,
        )

    def collect_events(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        on_page: Callable[[DatatourismePage], None],
    ) -> DatatourismeCollectionSummary:
        """Follow safe `next` links and reconcile all provider counts and UUIDs."""

        self._validate_circle(latitude, longitude, radius_meters)
        invariant_params = {
            "geo_distance": f"{latitude:.6f},{longitude:.6f},{radius_meters}m",
            "page_size": str(PAGE_SIZE),
            "lang": "fr",
            "fields": ",".join(EVENT_FIELDS),
        }
        request = _SafePaginationRequest(
            EVENT_URL,
            tuple(invariant_params.items()),
            "initial",
        )
        seen_links: set[str] = set()
        seen_uuids: set[UUID] = set()
        announced_total: int | None = None
        announced_total_pages: int | None = None
        received_count = 0
        importable_count = 0
        page_count = 0
        rejection_counts: Counter[str] = Counter()

        while True:
            response = self._get(request.url, request.params)
            payload = self._page_payload(response)
            page_count += 1
            metadata = payload.meta
            if metadata.page != page_count:
                raise DatatourismeContractError("DATAtourisme returned an unexpected page number")
            if metadata.page_size != PAGE_SIZE:
                raise DatatourismeContractError("DATAtourisme changed the effective page size")
            expected_pages = math.ceil(metadata.total / metadata.page_size)
            if metadata.total_pages != expected_pages:
                raise DatatourismeContractError("DATAtourisme returned inconsistent page totals")
            if announced_total is None:
                announced_total = metadata.total
                announced_total_pages = metadata.total_pages
            elif metadata.total != announced_total or metadata.total_pages != announced_total_pages:
                raise DatatourismeContractError(
                    "the announced DATAtourisme totals changed during pagination"
                )

            page_rejections: Counter[str] = Counter()
            candidates: list[EventCandidate] = []
            for item in payload.objects:
                if item.uuid in seen_uuids:
                    raise DatatourismeContractError(
                        "DATAtourisme returned a duplicate UUID in one collection"
                    )
                seen_uuids.add(item.uuid)
                candidate, rejection = _normalize_candidate(item)
                if candidate is not None:
                    candidates.append(candidate)
                elif rejection is not None:
                    page_rejections[rejection] += 1

            received_count += len(payload.objects)
            importable_count += len(candidates)
            rejection_counts.update(page_rejections)
            next_request = (
                _safe_pagination_request(metadata.next, invariant_params)
                if metadata.next is not None
                else None
            )
            if next_request is not None and next_request.fingerprint in seen_links:
                raise DatatourismeContractError(
                    "the DATAtourisme next link looped before the final page"
                )
            terminal = next_request is None
            on_page(
                DatatourismePage(
                    number=page_count,
                    announced_total=metadata.total,
                    announced_total_pages=metadata.total_pages,
                    received_count=len(payload.objects),
                    importable_candidates=tuple(candidates),
                    rejection_counts=dict(page_rejections),
                    next_link_fingerprint=(
                        next_request.fingerprint if next_request is not None else None
                    ),
                    terminal=terminal,
                )
            )

            if terminal:
                if page_count != metadata.total_pages and not (
                    metadata.total == 0 and page_count == 1 and metadata.total_pages == 0
                ):
                    raise DatatourismeContractError(
                        "DATAtourisme ended before the announced final page"
                    )
                if received_count != metadata.total or len(seen_uuids) != metadata.total:
                    raise DatatourismeContractError("the terminal DATAtourisme count is incomplete")
                break

            assert next_request is not None
            if metadata.page >= metadata.total_pages:
                raise DatatourismeContractError(
                    "DATAtourisme returned a next link after the announced final page"
                )
            seen_links.add(next_request.fingerprint)
            request = next_request

        assert announced_total is not None
        return DatatourismeCollectionSummary(
            announced_total,
            received_count,
            len(seen_uuids),
            importable_count,
            page_count,
            dict(rejection_counts),
        )

    @staticmethod
    def _validate_circle(latitude: float, longitude: float, radius_meters: int) -> None:
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("the DATAtourisme latitude is invalid")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("the DATAtourisme longitude is invalid")
        if not 1 <= radius_meters <= 50_000:
            raise ValueError("the DATAtourisme radius must be between 1 and 50,000 meters")

    def _page_payload(self, response: httpx.Response) -> _EventResponse:
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise DatatourismeContractError("the DATAtourisme response is unexpectedly large")
        try:
            return _EventResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise DatatourismeContractError("the DATAtourisme event schema changed") from error

    def _get(
        self,
        url: str,
        params: tuple[tuple[str, str], ...],
    ) -> httpx.Response:
        last_temporary_error: DatatourismeTemporaryError | None = None
        for attempt in range(MAX_HTTP_ATTEMPTS):
            self._wait_for_rate_limit()
            try:
                response = self._client.get(url, params=params, headers=self._request_headers)
            except httpx.HTTPError:
                last_temporary_error = DatatourismeTemporaryError("the DATAtourisme request failed")
            else:
                if response.status_code in {401, 403}:
                    raise DatatourismeAuthenticationError(
                        "DATAtourisme rejected the configured API key"
                    )
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    retry_seconds = _parse_retry_after(response.headers.get("Retry-After"))
                    last_temporary_error = DatatourismeTemporaryError(
                        f"DATAtourisme returned HTTP {response.status_code}",
                        retry_after_seconds=retry_seconds,
                    )
                elif response.status_code != 200:
                    raise DatatourismeRequestError(
                        f"DATAtourisme returned HTTP {response.status_code}"
                    )
                else:
                    return response

            assert last_temporary_error is not None
            retry_after_seconds = last_temporary_error.retry_after_seconds
            if attempt == MAX_HTTP_ATTEMPTS - 1 or (
                retry_after_seconds is not None
                and retry_after_seconds > MAX_IN_PROCESS_RETRY_SECONDS
            ):
                raise last_temporary_error
            backoff = 2**attempt + self._jitter()
            self._sleeper(max(backoff, float(retry_after_seconds or 0)))

        raise AssertionError("the bounded DATAtourisme retry loop did not terminate")

    def _wait_for_rate_limit(self) -> None:
        remaining = self._next_request_at - self._monotonic()
        if remaining > 0:
            self._sleeper(remaining)
        self._next_request_at = self._monotonic() + MIN_REQUEST_INTERVAL_SECONDS

    def close(self) -> None:
        """Close only the HTTP client created by this adapter."""

        if self._owns_client:
            self._client.close()
