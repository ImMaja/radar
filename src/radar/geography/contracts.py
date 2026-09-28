"""Typed boundaries and values for Radar's reference geography."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True)
class StructuredAddress:
    """Useful structured fields returned by the address provider."""

    house_number: str | None
    street: str | None
    postcode: str | None
    city: str | None
    context: str | None

    def as_dict(self) -> dict[str, str]:
        """Return only known values for JSON persistence."""

        values = {
            "house_number": self.house_number,
            "street": self.street,
            "postcode": self.postcode,
            "city": self.city,
            "context": self.context,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True)
class GeocodedAddress:
    """Provider-neutral result selected from one geocoding response."""

    normalized_label: str
    structured_address: StructuredAddress
    longitude: float
    latitude: float
    municipality_code: str
    ban_id: str | None
    result_type: str | None
    score: float | None
    provider_name: str
    provider_url: str


@dataclass(frozen=True)
class ReferencePosition:
    """One immutable geocoding result, pending or confirmed."""

    id: UUID
    input_address: str
    normalized_label: str
    structured_address: StructuredAddress
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


@dataclass(frozen=True)
class GeographySettings:
    """Current reference position and independently adjustable radii."""

    reference_position: ReferencePosition | None
    collection_radius_meters: int
    search_radius_meters: int
    updated_at: datetime


class Geocoder(Protocol):
    """External address provider boundary."""

    def geocode(self, input_address: str) -> GeocodedAddress: ...


class GeographyRepository(Protocol):
    """Persistence boundary for reference positions and radius settings."""

    def save_candidate(
        self,
        input_address: str,
        candidate: GeocodedAddress,
        now: datetime,
    ) -> ReferencePosition: ...

    def get_settings(self) -> GeographySettings: ...

    def confirm_candidate(self, candidate_id: UUID, now: datetime) -> GeographySettings: ...

    def update_radii(
        self,
        collection_radius_meters: int,
        search_radius_meters: int,
        now: datetime,
    ) -> GeographySettings: ...


class GeographyBackend(Protocol):
    """Web-facing geography use cases."""

    def geocode_reference(self, input_address: str) -> ReferencePosition: ...

    def get_settings(self) -> GeographySettings: ...

    def confirm_reference(self, candidate_id: UUID) -> GeographySettings: ...

    def update_radii(
        self,
        collection_radius_meters: int,
        search_radius_meters: int,
    ) -> GeographySettings: ...


class AddressNotFoundError(ValueError):
    """Raised when the provider has no usable address result."""


class AddressOutsideMetropolitanFranceError(ValueError):
    """Raised when results exist but none is in metropolitan France."""


GeocodingFailureReason = Literal[
    "unknown",
    "network",
    "rate_limited",
    "temporary_http",
    "server_error",
    "request_rejected",
]


class GeocodingUnavailableError(RuntimeError):
    """Raised with non-sensitive diagnostics when the geocoder cannot answer safely."""

    def __init__(
        self,
        message: str,
        *,
        reason: GeocodingFailureReason = "unknown",
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
        attempts: int = 1,
    ) -> None:
        if status_code is not None and not 100 <= status_code <= 599:
            raise ValueError("geocoding failure status code is invalid")
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("geocoding failure retry delay cannot be negative")
        if attempts < 1:
            raise ValueError("geocoding failure attempt count must be positive")
        self.reason = reason
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.attempts = attempts
        super().__init__(message)


class GeocodingContractError(RuntimeError):
    """Raised when the provider response no longer matches its contract."""


class ReferenceCandidateNotFoundError(LookupError):
    """Raised when an unconfirmed candidate cannot be selected."""


class RadiusOutOfRangeError(ValueError):
    """Raised when a local radius is outside the MVP bounds."""
