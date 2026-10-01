"""Private HTTP contract for the local event catalogue."""

from datetime import date, datetime, time
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from radar.auth.contracts import AuthenticatedSession
from radar.events.catalog import (
    EventCatalogBackend,
    EventCatalogUnavailableError,
    EventContact,
    EventDetail,
    EventNotFoundError,
    EventPage,
    EventPeriod,
    EventReferencePositionRequiredError,
    EventSearch,
    EventSource,
    EventSummary,
)
from radar.web.auth import current_session
from radar.web.errors import AUTH_ERROR_RESPONSES, ApiProblem, ErrorBody

router = APIRouter(prefix="/api/v1/events", tags=["events"])


class EventListParameters(BaseModel):
    """Bounded local filters; scoring waits for the scoring milestone."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, min_length=1, max_length=200)
    max_distance_meters: int | None = Field(default=None, ge=1, le=50_000)
    date_from: date | None = None
    date_to: date | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    organizer: str | None = Field(default=None, min_length=1, max_length=200)
    has_contact: bool = False
    declared_status: Literal["SCHEDULED", "POSTPONED", "CANCELLED", "UNKNOWN"] | None = None
    sort: Literal["date", "distance"] = "date"
    direction: Literal["asc", "desc"] = "asc"
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("q", "category", "organizer")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("filter is blank")
        return normalized

    @model_validator(mode="after")
    def require_ordered_dates(self) -> "EventListParameters":
        if self.date_from is not None and self.date_to is not None:
            if self.date_to < self.date_from:
                raise ValueError("date_to cannot precede date_from")
        return self


class EventSummaryResponse(BaseModel):
    id: UUID
    title: str
    types: list[str]
    organizer_name: str | None
    declared_status: Literal["SCHEDULED", "POSTPONED", "CANCELLED", "UNKNOWN"]
    temporal_state: Literal["UPCOMING", "ONGOING"]
    next_start_at: datetime
    full_address: str | None
    municipality: str | None
    distance_meters: float | None
    has_contact: bool
    last_observed_at: datetime


class EventPageResponse(BaseModel):
    items: list[EventSummaryResponse]
    total: int
    limit: int
    offset: int
    applied_radius_meters: int


class EventPeriodResponse(BaseModel):
    start_date: date
    end_date: date
    start_time: time | None
    end_time: time | None
    precision: str
    source_path: str


class EventContactResponse(BaseModel):
    type: Literal["EMAIL", "PHONE", "WEBSITE", "BOOKING_URL", "CONTACT_RELAY"]
    value: str
    scope: Literal["LOCAL", "CENTRAL", "UNKNOWN"]
    label: str | None
    source_reference: str | None


class EventSourcePartyResponse(BaseModel):
    role: Literal["CREATOR", "PUBLISHER", "OWNER"]
    identifier: str | None
    legal_name: str | None


class EventSourceResponse(BaseModel):
    code: str
    name: str
    authority: str
    state: str
    first_observed_at: datetime
    last_observed_at: datetime
    retrieved_at: datetime
    source_updated_at: datetime | None
    license_name: str | None
    parties: list[EventSourcePartyResponse]


class EventDetailResponse(EventSummaryResponse):
    description: str | None
    source_uri: str | None
    period_layer: Literal["SOURCE", "USER"]
    periods: list[EventPeriodResponse]
    longitude: float | None
    latitude: float | None
    contacts: list[EventContactResponse]
    sources: list[EventSourceResponse]


EVENT_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ErrorBody},
    409: {"model": ErrorBody},
    503: {"model": ErrorBody},
}


def get_event_backend(request: Request) -> EventCatalogBackend:
    """Resolve the private local event read model."""

    return cast(EventCatalogBackend, request.app.state.event_backend)


def _summary_values(summary: EventSummary) -> dict[str, object]:
    return {
        "id": summary.id,
        "title": summary.title,
        "types": list(summary.types),
        "organizer_name": summary.organizer_name,
        "declared_status": summary.declared_status,
        "temporal_state": summary.temporal_state,
        "next_start_at": summary.next_start_at,
        "full_address": summary.full_address,
        "municipality": summary.municipality,
        "distance_meters": summary.distance_meters,
        "has_contact": summary.has_contact,
        "last_observed_at": summary.last_observed_at,
    }


def _page_response(page: EventPage) -> EventPageResponse:
    return EventPageResponse(
        items=[EventSummaryResponse.model_validate(_summary_values(item)) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        applied_radius_meters=page.applied_radius_meters,
    )


def _period_response(period: EventPeriod) -> EventPeriodResponse:
    return EventPeriodResponse(
        start_date=period.start_date,
        end_date=period.end_date,
        start_time=period.start_time,
        end_time=period.end_time,
        precision=period.precision,
        source_path=period.source_path,
    )


def _contact_response(contact: EventContact) -> EventContactResponse:
    return EventContactResponse(
        type=contact.type,
        value=contact.value,
        scope=contact.scope,
        label=contact.label,
        source_reference=contact.source_reference,
    )


def _source_response(source: EventSource) -> EventSourceResponse:
    return EventSourceResponse(
        code=source.code,
        name=source.name,
        authority=source.authority,
        state=source.state,
        first_observed_at=source.first_observed_at,
        last_observed_at=source.last_observed_at,
        retrieved_at=source.retrieved_at,
        source_updated_at=source.source_updated_at,
        license_name=source.license_name,
        parties=[
            EventSourcePartyResponse(
                role=party.role, identifier=party.identifier, legal_name=party.legal_name
            )
            for party in source.parties
        ],
    )


def _detail_response(detail: EventDetail) -> EventDetailResponse:
    return EventDetailResponse.model_validate(
        {
            **_summary_values(detail.summary),
            "description": detail.description,
            "source_uri": detail.source_uri,
            "period_layer": detail.period_layer,
            "periods": [_period_response(period) for period in detail.periods],
            "longitude": detail.longitude,
            "latitude": detail.latitude,
            "contacts": [_contact_response(contact) for contact in detail.contacts],
            "sources": [_source_response(source) for source in detail.sources],
        }
    )


def _catalog_problem(error: EventCatalogUnavailableError) -> ApiProblem:
    del error
    return ApiProblem(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "event_catalog_unavailable",
        "Le catalogue local des événements est momentanément indisponible.",
    )


@router.get("", response_model=EventPageResponse, responses=EVENT_ERROR_RESPONSES)
def list_events(
    parameters: Annotated[EventListParameters, Query()],
    _session: Annotated[AuthenticatedSession, Depends(current_session)],
    backend: Annotated[EventCatalogBackend, Depends(get_event_backend)],
) -> EventPageResponse:
    """Search only locally stored, ordinary visible events."""

    query = EventSearch(
        text=parameters.q,
        max_distance_meters=parameters.max_distance_meters,
        date_from=parameters.date_from,
        date_to=parameters.date_to,
        category=parameters.category,
        organizer=parameters.organizer,
        has_contact=parameters.has_contact,
        declared_status=parameters.declared_status,
        sort=parameters.sort,
        direction=parameters.direction,
        limit=parameters.limit,
        offset=parameters.offset,
    )
    try:
        return _page_response(backend.search(query))
    except EventReferencePositionRequiredError as error:
        raise ApiProblem(
            status.HTTP_409_CONFLICT,
            "reference_position_required",
            "Confirmez une adresse de référence avant de consulter les événements.",
        ) from error
    except EventCatalogUnavailableError as error:
        raise _catalog_problem(error) from error


@router.get("/{event_id}", response_model=EventDetailResponse, responses=EVENT_ERROR_RESPONSES)
def read_event(
    event_id: UUID,
    _session: Annotated[AuthenticatedSession, Depends(current_session)],
    backend: Annotated[EventCatalogBackend, Depends(get_event_backend)],
) -> EventDetailResponse:
    """Read one visible event with its effective periods and provenance."""

    try:
        return _detail_response(backend.get(event_id))
    except EventNotFoundError as error:
        raise ApiProblem(
            status.HTTP_404_NOT_FOUND,
            "event_not_found",
            "Cette fiche événement est introuvable.",
        ) from error
    except EventCatalogUnavailableError as error:
        raise _catalog_problem(error) from error
