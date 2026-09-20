"""Private HTTP contract for the reference address and local radii."""

import logging
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field, field_validator

from radar.auth.contracts import AuthenticatedSession, AuthenticationBackend
from radar.config import Settings
from radar.geography.contracts import (
    AddressNotFoundError,
    AddressOutsideMetropolitanFranceError,
    GeocodingContractError,
    GeocodingUnavailableError,
    GeographyBackend,
    GeographySettings,
    RadiusOutOfRangeError,
    ReferenceCandidateNotFoundError,
    ReferencePosition,
    StructuredAddress,
)
from radar.web.auth import (
    current_session,
    get_authentication_backend,
    get_settings,
    require_csrf,
)
from radar.web.errors import AUTH_ERROR_RESPONSES, ApiProblem, ErrorBody

router = APIRouter(prefix="/api/v1/settings/geography", tags=["geography settings"])
logger = logging.getLogger(__name__)


class GeocodeRequest(BaseModel):
    """User-entered address to resolve through the official geocoder."""

    address: str = Field(min_length=3, max_length=300)

    @field_validator("address")
    @classmethod
    def reject_blank_address(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("address is blank")
        return normalized


class ConfirmReferenceRequest(BaseModel):
    """Identifier of the provider result explicitly checked by the user."""

    candidate_id: UUID


class UpdateRadiiRequest(BaseModel):
    """Independent collection and local-search radii in metres."""

    collection_radius_meters: int = Field(ge=1, le=50_000)
    search_radius_meters: int = Field(ge=1, le=50_000)


class StructuredAddressResponse(BaseModel):
    house_number: str | None
    street: str | None
    postcode: str | None
    city: str | None
    context: str | None


class ReferencePositionResponse(BaseModel):
    id: UUID
    input_address: str
    normalized_label: str
    structured_address: StructuredAddressResponse
    longitude: float
    latitude: float
    municipality_code: str
    ban_id: str | None
    result_type: str | None
    score: float | None
    provider_name: str
    provider_url: str
    geocoded_at: datetime
    confirmed_at: datetime | None


class GeographySettingsResponse(BaseModel):
    reference_position: ReferencePositionResponse | None
    collection_radius_meters: int
    search_radius_meters: int
    updated_at: datetime


GEOGRAPHY_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ErrorBody},
    502: {"model": ErrorBody},
    503: {"model": ErrorBody},
}


def get_geography_backend(request: Request) -> GeographyBackend:
    """Resolve reference-geography use cases assembled by the application."""

    return cast(GeographyBackend, request.app.state.geography_backend)


def _structured_response(address: StructuredAddress) -> StructuredAddressResponse:
    return StructuredAddressResponse(
        house_number=address.house_number,
        street=address.street,
        postcode=address.postcode,
        city=address.city,
        context=address.context,
    )


def _reference_response(position: ReferencePosition) -> ReferencePositionResponse:
    return ReferencePositionResponse(
        id=position.id,
        input_address=position.input_address,
        normalized_label=position.normalized_label,
        structured_address=_structured_response(position.structured_address),
        longitude=position.longitude,
        latitude=position.latitude,
        municipality_code=position.municipality_code,
        ban_id=position.ban_id,
        result_type=position.result_type,
        score=position.score,
        provider_name=position.provider_name,
        provider_url=position.provider_url,
        geocoded_at=position.geocoded_at,
        confirmed_at=position.confirmed_at,
    )


def _settings_response(settings: GeographySettings) -> GeographySettingsResponse:
    return GeographySettingsResponse(
        reference_position=(
            _reference_response(settings.reference_position)
            if settings.reference_position is not None
            else None
        ),
        collection_radius_meters=settings.collection_radius_meters,
        search_radius_meters=settings.search_radius_meters,
        updated_at=settings.updated_at,
    )


@router.get(
    "",
    response_model=GeographySettingsResponse,
    responses=GEOGRAPHY_ERROR_RESPONSES,
)
def read_geography_settings(
    _session: Annotated[AuthenticatedSession, Depends(current_session)],
    backend: Annotated[GeographyBackend, Depends(get_geography_backend)],
) -> GeographySettingsResponse:
    """Read current position and radii without any external call."""

    return _settings_response(backend.get_settings())


@router.post(
    "/geocodings",
    response_model=ReferencePositionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=GEOGRAPHY_ERROR_RESPONSES,
)
def geocode_reference_address(
    payload: GeocodeRequest,
    request: Request,
    session: Annotated[AuthenticatedSession, Depends(current_session)],
    authentication: Annotated[AuthenticationBackend, Depends(get_authentication_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
    backend: Annotated[GeographyBackend, Depends(get_geography_backend)],
) -> ReferencePositionResponse:
    """Propose one metropolitan address result without selecting it yet."""

    require_csrf(request, session, authentication, settings)
    try:
        return _reference_response(backend.geocode_reference(payload.address))
    except AddressNotFoundError as error:
        raise ApiProblem(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "address_not_found",
            "Aucune adresse correspondante n'a été trouvée.",
        ) from error
    except AddressOutsideMetropolitanFranceError as error:
        raise ApiProblem(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "address_outside_metropolitan_france",
            "L'adresse doit être située en France métropolitaine.",
        ) from error
    except GeocodingUnavailableError as error:
        logger.warning("reference_geocoding_unavailable")
        raise ApiProblem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "geocoding_unavailable",
            "Le service de géocodage est momentanément indisponible.",
        ) from error
    except GeocodingContractError as error:
        logger.error("reference_geocoding_contract_changed")
        raise ApiProblem(
            status.HTTP_502_BAD_GATEWAY,
            "geocoding_contract_error",
            "La réponse du service de géocodage est inexploitable.",
        ) from error


@router.post(
    "/reference-position",
    response_model=GeographySettingsResponse,
    responses=GEOGRAPHY_ERROR_RESPONSES,
)
def confirm_reference_position(
    payload: ConfirmReferenceRequest,
    request: Request,
    session: Annotated[AuthenticatedSession, Depends(current_session)],
    authentication: Annotated[AuthenticationBackend, Depends(get_authentication_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
    backend: Annotated[GeographyBackend, Depends(get_geography_backend)],
) -> GeographySettingsResponse:
    """Confirm a displayed candidate without starting a collection."""

    require_csrf(request, session, authentication, settings)
    try:
        return _settings_response(backend.confirm_reference(payload.candidate_id))
    except ReferenceCandidateNotFoundError as error:
        raise ApiProblem(
            status.HTTP_404_NOT_FOUND,
            "reference_candidate_not_found",
            "Cette proposition d'adresse n'est plus disponible.",
        ) from error


@router.patch(
    "/radii",
    response_model=GeographySettingsResponse,
    responses=GEOGRAPHY_ERROR_RESPONSES,
)
def update_radii(
    payload: UpdateRadiiRequest,
    request: Request,
    session: Annotated[AuthenticatedSession, Depends(current_session)],
    authentication: Annotated[AuthenticationBackend, Depends(get_authentication_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
    backend: Annotated[GeographyBackend, Depends(get_geography_backend)],
) -> GeographySettingsResponse:
    """Change local radii without an external call or a collection."""

    require_csrf(request, session, authentication, settings)
    try:
        updated = backend.update_radii(
            payload.collection_radius_meters,
            payload.search_radius_meters,
        )
    except RadiusOutOfRangeError as error:
        raise ApiProblem(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "radius_out_of_range",
            "Les rayons doivent être compris entre 1 mètre et 50 kilomètres.",
        ) from error
    return _settings_response(updated)
