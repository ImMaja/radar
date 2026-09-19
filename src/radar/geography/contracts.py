"""Typed boundaries and values for Radar's reference geography."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
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


class GeocodingUnavailableError(RuntimeError):
    """Raised when the external geocoder cannot answer safely."""


class GeocodingContractError(RuntimeError):
    """Raised when the provider response no longer matches its contract."""


class ReferenceCandidateNotFoundError(LookupError):
    """Raised when an unconfirmed candidate cannot be selected."""


class RadiusOutOfRangeError(ValueError):
    """Raised when a local radius is outside the MVP bounds."""
