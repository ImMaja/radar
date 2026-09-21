"""Provider-neutral contracts for versioned municipality reference data."""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class MunicipalityBoundary:
    """One named municipality contour represented as WGS84 GeoJSON."""

    code: str
    official_name: str
    geometry_json: str


@dataclass(frozen=True)
class MunicipalityBoundaryFile:
    """Validated content and fingerprint of one local source file."""

    path: Path
    file_size_bytes: int
    sha256: str
    source_feature_count: int
    ignored_non_metropolitan_count: int
    geometry_counts: dict[str, int]
    boundaries: tuple[MunicipalityBoundary, ...]


@dataclass(frozen=True)
class MunicipalityReleaseSource:
    """Non-secret provenance supplied for an official downloaded resource."""

    resource_identifier: str
    resource_url: str
    published_on: date | None
    retrieved_at: datetime
    license_name: str
    expected_sha256: str | None = None
    expected_size_bytes: int | None = None


@dataclass(frozen=True)
class DatasetRelease:
    """Persisted version of a validated external reference dataset."""

    id: UUID
    dataset_code: str
    resource_identifier: str
    file_digest: str
    status: str
    boundary_count: int
    activated_at: datetime
    already_active: bool


@dataclass(frozen=True)
class CandidateMunicipality:
    """A municipality whose contour intersects the expanded collection circle."""

    code: str
    official_name: str


@dataclass(frozen=True)
class MunicipalitySelection:
    """Auditable municipality selection tied to one active dataset release."""

    dataset_release_id: UUID
    resource_identifier: str
    collection_radius_meters: int
    margin_meters: int
    municipalities: tuple[CandidateMunicipality, ...]


class MunicipalityReferenceRepository(Protocol):
    """Persistence boundary for immutable releases and spatial selection."""

    def activate(
        self,
        source: MunicipalityReleaseSource,
        parsed_file: MunicipalityBoundaryFile,
        now: datetime,
    ) -> DatasetRelease: ...

    def select_candidates(
        self,
        longitude: float,
        latitude: float,
        collection_radius_meters: int,
        margin_meters: int,
    ) -> MunicipalitySelection: ...


class MunicipalityReferenceBackend(Protocol):
    """Application-facing municipality selection independent from persistence."""

    def select_candidates(
        self,
        longitude: float,
        latitude: float,
        collection_radius_meters: int,
    ) -> MunicipalitySelection: ...


class MunicipalityReferenceError(RuntimeError):
    """Base class for controlled reference-data failures."""


class MunicipalityFileError(MunicipalityReferenceError):
    """The downloaded file is missing, unsafe, or violates its contract."""


class MunicipalityReferenceUnavailableError(MunicipalityReferenceError):
    """No validated active municipality release can answer a selection."""
