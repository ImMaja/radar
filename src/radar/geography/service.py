"""Reference geography use cases independent from HTTP and SQLAlchemy."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from radar.geography.contracts import (
    Geocoder,
    GeographyRepository,
    GeographySettings,
    RadiusOutOfRangeError,
    ReferencePosition,
)

MIN_RADIUS_METERS = 1
MAX_RADIUS_METERS = 50_000


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


class GeographyService:
    """Coordinate geocoding, explicit confirmation and local settings."""

    def __init__(
        self,
        repository: GeographyRepository,
        geocoder: Geocoder,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._geocoder = geocoder
        self._clock = clock

    def geocode_reference(self, input_address: str) -> ReferencePosition:
        """Geocode one address and retain the proposed result for confirmation."""

        normalized_input = " ".join(input_address.split())
        candidate = self._geocoder.geocode(normalized_input)
        return self._repository.save_candidate(normalized_input, candidate, self._clock())

    def get_settings(self) -> GeographySettings:
        """Return current local geography without calling an external provider."""

        return self._repository.get_settings()

    def confirm_reference(self, candidate_id: UUID) -> GeographySettings:
        """Make one pending result the current immutable reference position."""

        return self._repository.confirm_candidate(candidate_id, self._clock())

    def update_radii(
        self,
        collection_radius_meters: int,
        search_radius_meters: int,
    ) -> GeographySettings:
        """Change local radii without geocoding or starting a collection."""

        if not MIN_RADIUS_METERS <= collection_radius_meters <= MAX_RADIUS_METERS:
            raise RadiusOutOfRangeError("collection radius is outside the MVP bounds")
        if not MIN_RADIUS_METERS <= search_radius_meters <= MAX_RADIUS_METERS:
            raise RadiusOutOfRangeError("search radius is outside the MVP bounds")
        return self._repository.update_radii(
            collection_radius_meters,
            search_radius_meters,
            self._clock(),
        )
