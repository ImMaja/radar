"""Sirene monthly geolocation staging contracts and deterministic normalization."""

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from radar.collections.contracts import ReservedCollection
from radar.providers.sirene_geolocation import (
    SireneGeolocationFile,
    SireneGeolocationFileError,
    SireneGeolocationRecord,
    SireneGeolocationScan,
    inspect_sirene_geolocation_file,
    scan_sirene_geolocation_file,
)

SIRENE_GEOLOCATION_DATA_SOURCE_CODE = "SIRENE_GEOLOCATION"
SIRENE_GEOLOCATION_DATASET_CODE = "sirene-geolocation-establishments"
SIRENE_GEOLOCATION_ADAPTER_VERSION = "sirene-geolocation-parquet-v1"
SIRENE_GEOLOCATION_SCHEMA_VERSION = "sirene-geolocation-position-v1"
SIRENE_GEOLOCATION_RULE_VERSION = "sirene-position-resolution-v1"


@dataclass(frozen=True)
class SireneGeolocationReleaseSource:
    """Non-secret provenance of one downloaded official monthly resource."""

    resource_identifier: str
    resource_url: str
    published_on: date | None
    retrieved_at: datetime
    license_name: str
    expected_sha1: str | None = None
    expected_size_bytes: int | None = None


@dataclass(frozen=True)
class SireneGeolocationTarget:
    """One current API candidate to match against the monthly file."""

    collection_item_id: UUID
    external_identity_id: UUID
    siret: str
    municipality_code: str


@dataclass(frozen=True)
class SireneGeolocationRelease:
    """Persisted release and source-run state used by one collection cycle."""

    id: UUID
    source_run_id: UUID
    status: str
    newly_created: bool


@dataclass(frozen=True)
class StagedSireneGeolocationPosition:
    """One minimized file observation attached to its current candidate item."""

    collection_item_id: UUID
    external_identity_id: UUID
    siret: str
    expected_municipality_code: str
    content_fingerprint: str
    payload: dict[str, object]
    lambert_x: float | None
    lambert_y: float | None
    longitude: float | None
    latitude: float | None
    source_crs: str | None
    source_municipality_code: str | None
    quality_code: str | None


class SireneGeolocationImportError(RuntimeError):
    """The monthly position import cannot complete without compromising provenance."""


class SireneGeolocationBackend(Protocol):
    """Persistence boundary for one restart-safe monthly file import."""

    def targets(
        self,
        reservation: ReservedCollection,
    ) -> tuple[SireneGeolocationTarget, ...]: ...

    def prepare_release(
        self,
        reservation: ReservedCollection,
        source: SireneGeolocationReleaseSource,
        file: SireneGeolocationFile,
        now: datetime,
    ) -> SireneGeolocationRelease: ...

    def stage_positions(
        self,
        reservation: ReservedCollection,
        release: SireneGeolocationRelease,
        positions: tuple[StagedSireneGeolocationPosition, ...],
        now: datetime,
    ) -> None: ...

    def complete_release(
        self,
        reservation: ReservedCollection,
        release: SireneGeolocationRelease,
        scan: SireneGeolocationScan,
        now: datetime,
    ) -> None: ...

    def completed_scan(
        self,
        reservation: ReservedCollection,
        release: SireneGeolocationRelease,
    ) -> SireneGeolocationScan: ...

    def fail_release(
        self,
        reservation: ReservedCollection,
        release: SireneGeolocationRelease,
        *,
        code: str,
        now: datetime,
    ) -> None: ...


def _finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def normalize_sirene_geolocation_record(
    target: SireneGeolocationTarget,
    record: SireneGeolocationRecord,
) -> StagedSireneGeolocationPosition:
    """Minimize one official row without interpreting another source's quality."""

    if target.siret != record.siret:
        raise SireneGeolocationImportError(
            "Sirene geolocation record does not match its target identity"
        )
    lambert_x = _finite(record.lambert_x)
    lambert_y = _finite(record.lambert_y)
    longitude = _finite(record.longitude)
    latitude = _finite(record.latitude)
    distance_precision = _finite(record.distance_precision_meters)
    payload: dict[str, object] = {
        "siret": record.siret,
        "position": {
            "lambert_x": lambert_x,
            "lambert_y": lambert_y,
            "epsg": record.epsg,
            "longitude": longitude,
            "latitude": latitude,
        },
        "quality": {
            "code": record.quality_code,
            "distance_precision_meters": distance_precision,
        },
        "source_municipality_code": record.municipality_code,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return StagedSireneGeolocationPosition(
        collection_item_id=target.collection_item_id,
        external_identity_id=target.external_identity_id,
        siret=record.siret,
        expected_municipality_code=target.municipality_code,
        content_fingerprint=hashlib.sha256(canonical).hexdigest(),
        payload=payload,
        lambert_x=lambert_x,
        lambert_y=lambert_y,
        longitude=longitude,
        latitude=latitude,
        source_crs=record.epsg,
        source_municipality_code=record.municipality_code,
        quality_code=record.quality_code,
    )


class SireneGeolocationImportService:
    """Inspect, match and persist one monthly file without publishing partial data."""

    def __init__(
        self,
        backend: SireneGeolocationBackend,
        clock: Callable[[], datetime],
    ) -> None:
        self._backend = backend
        self._clock = clock

    def import_file(
        self,
        reservation: ReservedCollection,
        path: Path,
        source: SireneGeolocationReleaseSource,
    ) -> SireneGeolocationScan:
        """Run or resume the deterministic file stage for one Sirene cycle."""

        self._validate_request(reservation, source)
        targets = self._backend.targets(reservation)
        try:
            file = inspect_sirene_geolocation_file(
                path,
                expected_sha1=source.expected_sha1,
                expected_size_bytes=source.expected_size_bytes,
            )
        except SireneGeolocationFileError as error:
            raise SireneGeolocationImportError(
                "Sirene geolocation file failed its validation"
            ) from error

        release = self._backend.prepare_release(
            reservation,
            source,
            file,
            self._clock(),
        )
        if release.status == "SUCCEEDED":
            return self._backend.completed_scan(reservation, release)
        if release.status != "RUNNING":
            raise SireneGeolocationImportError(
                "Sirene geolocation source run is not restartable"
            )

        targets_by_siret = {target.siret: target for target in targets}

        def stage(records: tuple[SireneGeolocationRecord, ...]) -> None:
            try:
                positions = tuple(
                    normalize_sirene_geolocation_record(
                        targets_by_siret[record.siret],
                        record,
                    )
                    for record in records
                )
            except KeyError as error:
                raise SireneGeolocationImportError(
                    "monthly file emitted an unrequested SIRET"
                ) from error
            self._backend.stage_positions(
                reservation,
                release,
                positions,
                self._clock(),
            )

        try:
            scan = scan_sirene_geolocation_file(
                path,
                tuple(targets_by_siret),
                stage,
                inspected_file=file,
            )
            self._backend.complete_release(
                reservation,
                release,
                scan,
                self._clock(),
            )
            return scan
        except Exception as error:
            self._backend.fail_release(
                reservation,
                release,
                code="sirene_geolocation_import_failed",
                now=self._clock(),
            )
            if isinstance(error, SireneGeolocationImportError):
                raise
            if isinstance(error, SireneGeolocationFileError):
                raise SireneGeolocationImportError(
                    "Sirene geolocation file could not be staged"
                ) from error
            raise SireneGeolocationImportError(
                "Sirene geolocation staging failed unexpectedly"
            ) from error

    @staticmethod
    def _validate_request(
        reservation: ReservedCollection,
        source: SireneGeolocationReleaseSource,
    ) -> None:
        if reservation.connector != "SIRENE":
            raise ValueError("only a Sirene collection can import Sirene geolocation")
        parsed_url = urlsplit(source.resource_url)
        if parsed_url.scheme != "https" or parsed_url.hostname is None:
            raise ValueError("Sirene geolocation resource URL must be absolute HTTPS")
        if not source.resource_identifier.strip():
            raise ValueError("Sirene geolocation resource identifier cannot be empty")
        if not source.license_name.strip():
            raise ValueError("Sirene geolocation license cannot be empty")
        if source.retrieved_at.tzinfo is None:
            raise ValueError("Sirene geolocation retrieval time must include a timezone")
