"""Private HTTP contract for the local prospect catalogue."""

from datetime import date, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from radar.auth.contracts import AuthenticatedSession
from radar.prospects.catalog import (
    ProspectCatalogBackend,
    ProspectCatalogUnavailableError,
    ProspectContact,
    ProspectDetail,
    ProspectNotFoundError,
    ProspectPage,
    ProspectReferencePositionRequiredError,
    ProspectSearch,
    ProspectSource,
    ProspectSummary,
)
from radar.web.auth import current_session
from radar.web.errors import AUTH_ERROR_RESPONSES, ApiProblem, ErrorBody

router = APIRouter(prefix="/api/v1/prospects", tags=["prospects"])


class ProspectListParameters(BaseModel):
    """Explicitly allowed filters and pagination for the prospect list."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, min_length=1, max_length=200)
    max_distance_meters: int | None = Field(default=None, ge=1, le=50_000)
    organization_type: str | None = Field(default=None, min_length=1, max_length=64)
    activity_code: str | None = Field(default=None, min_length=1, max_length=16)
    employee_band: str | None = Field(default=None, min_length=1, max_length=8)
    has_email: bool = False
    has_phone: bool = False
    has_website: bool = False
    location: Literal["located", "to_verify"] = "located"
    sort: Literal["distance", "name"] = "distance"
    direction: Literal["asc", "desc"] = "asc"
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("q", "organization_type", "activity_code", "employee_band")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("filter is blank")
        return normalized


class ProspectAddressResponse(BaseModel):
    full_address: str | None
    street_number: str | None
    repetition_index: str | None
    street_type: str | None
    street_label: str | None
    address_complement: str | None
    postcode: str | None
    municipality: str | None
    municipality_code: str | None


class ProspectSummaryResponse(BaseModel):
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
    address: ProspectAddressResponse
    distance_meters: float | None
    location_status: Literal["located", "to_verify"]
    location_precision: str
    last_observed_at: datetime


class ProspectPageResponse(BaseModel):
    items: list[ProspectSummaryResponse]
    total: int
    limit: int
    offset: int
    applied_radius_meters: int


class ProspectSourceResponse(BaseModel):
    code: str
    name: str
    authority: str
    producer_name: str | None
    state: str
    first_observed_at: datetime
    last_observed_at: datetime
    retrieved_at: datetime
    source_updated_at: datetime | None


class ProspectContactResponse(BaseModel):
    type: Literal["EMAIL", "PHONE", "WEBSITE", "BOOKING_URL", "CONTACT_RELAY"]
    value: str
    scope: Literal["LOCAL", "CENTRAL", "UNKNOWN"]
    label: str | None
    source_reference: str | None


class ProspectDetailResponse(ProspectSummaryResponse):
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
    contacts: list[ProspectContactResponse]
    sources: list[ProspectSourceResponse]


PROSPECT_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ErrorBody},
    409: {"model": ErrorBody},
    503: {"model": ErrorBody},
}


def get_prospect_backend(request: Request) -> ProspectCatalogBackend:
    """Resolve the local prospect read model assembled by the application."""

    return cast(ProspectCatalogBackend, request.app.state.prospect_backend)


def _address_response(summary: ProspectSummary) -> ProspectAddressResponse:
    return ProspectAddressResponse(
        full_address=summary.address.full_address,
        street_number=summary.address.street_number,
        repetition_index=summary.address.repetition_index,
        street_type=summary.address.street_type,
        street_label=summary.address.street_label,
        address_complement=summary.address.address_complement,
        postcode=summary.address.postcode,
        municipality=summary.address.municipality,
        municipality_code=summary.address.municipality_code,
    )


def _summary_values(summary: ProspectSummary) -> dict[str, object]:
    return {
        "id": summary.id,
        "display_name": summary.display_name,
        "organization_type": summary.organization_type,
        "activity_code": summary.activity_code,
        "activity_nomenclature": summary.activity_nomenclature,
        "activity_label": summary.activity_label,
        "employee_band": summary.employee_band,
        "employee_year": summary.employee_year,
        "employee_scope": summary.employee_scope,
        "has_email": summary.has_email,
        "has_phone": summary.has_phone,
        "has_website": summary.has_website,
        "address": _address_response(summary),
        "distance_meters": summary.distance_meters,
        "location_status": summary.location_status,
        "location_precision": summary.location_precision,
        "last_observed_at": summary.last_observed_at,
    }


def _summary_response(summary: ProspectSummary) -> ProspectSummaryResponse:
    return ProspectSummaryResponse.model_validate(_summary_values(summary))


def _source_response(source: ProspectSource) -> ProspectSourceResponse:
    return ProspectSourceResponse(
        code=source.code,
        name=source.name,
        authority=source.authority,
        producer_name=source.producer_name,
        state=source.state,
        first_observed_at=source.first_observed_at,
        last_observed_at=source.last_observed_at,
        retrieved_at=source.retrieved_at,
        source_updated_at=source.source_updated_at,
    )


def _contact_response(contact: ProspectContact) -> ProspectContactResponse:
    return ProspectContactResponse(
        type=contact.type,
        value=contact.value,
        scope=contact.scope,
        label=contact.label,
        source_reference=contact.source_reference,
    )


def _page_response(page: ProspectPage) -> ProspectPageResponse:
    return ProspectPageResponse(
        items=[_summary_response(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        applied_radius_meters=page.applied_radius_meters,
    )


def _detail_response(detail: ProspectDetail) -> ProspectDetailResponse:
    return ProspectDetailResponse.model_validate(
        {
            **_summary_values(detail.summary),
            "description": detail.description,
            "siret": detail.siret,
            "siren": detail.siren,
            "legal_name": detail.legal_name,
            "usual_name": detail.usual_name,
            "legal_category": detail.legal_category,
            "is_head_office": detail.is_head_office,
            "eligibility": detail.eligibility,
            "eligibility_reason": detail.eligibility_reason,
            "established_on": detail.established_on,
            "current_period_started_on": detail.current_period_started_on,
            "longitude": detail.longitude,
            "latitude": detail.latitude,
            "location_origin": detail.location_origin,
            "location_quality_code": detail.location_quality_code,
            "location_match_score": detail.location_match_score,
            "first_observed_at": detail.first_observed_at,
            "contacts": [_contact_response(contact) for contact in detail.contacts],
            "sources": [_source_response(source) for source in detail.sources],
        }
    )


def _catalog_problem(error: ProspectCatalogUnavailableError) -> ApiProblem:
    return ApiProblem(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "prospect_catalog_unavailable",
        "Le catalogue local des prospects est momentanément indisponible.",
    )


@router.get("", response_model=ProspectPageResponse, responses=PROSPECT_ERROR_RESPONSES)
def list_prospects(
    parameters: Annotated[ProspectListParameters, Query()],
    _session: Annotated[AuthenticatedSession, Depends(current_session)],
    backend: Annotated[ProspectCatalogBackend, Depends(get_prospect_backend)],
) -> ProspectPageResponse:
    """Search only Radar's local data with bounded filters and pagination."""

    query = ProspectSearch(
        text=parameters.q,
        max_distance_meters=parameters.max_distance_meters,
        organization_type=(
            parameters.organization_type.upper() if parameters.organization_type else None
        ),
        activity_code=parameters.activity_code.upper() if parameters.activity_code else None,
        employee_band=parameters.employee_band.upper() if parameters.employee_band else None,
        has_email=parameters.has_email,
        has_phone=parameters.has_phone,
        has_website=parameters.has_website,
        location=parameters.location,
        sort=parameters.sort,
        direction=parameters.direction,
        limit=parameters.limit,
        offset=parameters.offset,
    )
    try:
        return _page_response(backend.search(query))
    except ProspectReferencePositionRequiredError as error:
        raise ApiProblem(
            status.HTTP_409_CONFLICT,
            "reference_position_required",
            "Confirmez une adresse de référence avant de consulter les prospects.",
        ) from error
    except ProspectCatalogUnavailableError as error:
        raise _catalog_problem(error) from error


@router.get(
    "/{prospect_id}",
    response_model=ProspectDetailResponse,
    responses=PROSPECT_ERROR_RESPONSES,
)
def read_prospect(
    prospect_id: UUID,
    _session: Annotated[AuthenticatedSession, Depends(current_session)],
    backend: Annotated[ProspectCatalogBackend, Depends(get_prospect_backend)],
) -> ProspectDetailResponse:
    """Read effective fiche details and their current provenance."""

    try:
        return _detail_response(backend.get(prospect_id))
    except ProspectNotFoundError as error:
        raise ApiProblem(
            status.HTTP_404_NOT_FOUND,
            "prospect_not_found",
            "Cette fiche prospect est introuvable.",
        ) from error
    except ProspectCatalogUnavailableError as error:
        raise _catalog_problem(error) from error
