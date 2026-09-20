"""Use cases for validated municipality releases and conservative selection."""

import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from radar.providers.administrative_boundaries import read_municipality_file
from radar.reference_data.contracts import (
    DatasetRelease,
    MunicipalityReferenceRepository,
    MunicipalityReleaseSource,
    MunicipalitySelection,
)

MUNICIPALITY_SELECTION_MARGIN_METERS = 1_000
MIN_COLLECTION_RADIUS_METERS = 1
MAX_COLLECTION_RADIUS_METERS = 50_000


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


class MunicipalityReferenceService:
    """Validate local reference files before handing them to persistence."""

    def __init__(
        self,
        repository: MunicipalityReferenceRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def import_file(
        self,
        path: Path,
        source: MunicipalityReleaseSource,
    ) -> DatasetRelease:
        """Validate and atomically activate a downloaded municipality release."""

        parsed_url = urlsplit(source.resource_url)
        if parsed_url.scheme != "https" or parsed_url.hostname is None:
            raise ValueError("municipality resource URL must be an absolute HTTPS URL")
        if not source.resource_identifier.strip():
            raise ValueError("municipality resource identifier cannot be empty")
        if not source.license_name.strip():
            raise ValueError("municipality dataset license cannot be empty")
        if source.retrieved_at.tzinfo is None:
            raise ValueError("municipality retrieval time must include a timezone")

        parsed_file = read_municipality_file(
            path,
            expected_sha256=source.expected_sha256,
            expected_size_bytes=source.expected_size_bytes,
        )
        return self._repository.activate(source, parsed_file, self._clock())

    def select_candidates(
        self,
        longitude: float,
        latitude: float,
        collection_radius_meters: int,
    ) -> MunicipalitySelection:
        """Return contours intersecting the collection circle expanded by 1 km."""

        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("longitude must be a finite WGS84 coordinate")
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("latitude must be a finite WGS84 coordinate")
        if (
            not MIN_COLLECTION_RADIUS_METERS
            <= collection_radius_meters
            <= MAX_COLLECTION_RADIUS_METERS
        ):
            raise ValueError("collection radius is outside the MVP bounds")
        return self._repository.select_candidates(
            longitude,
            latitude,
            collection_radius_meters,
            MUNICIPALITY_SELECTION_MARGIN_METERS,
        )
