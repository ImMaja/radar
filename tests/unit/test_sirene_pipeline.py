"""Tests for the end-to-end Sirene stage composition."""

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from radar.collections.contracts import (
    CollectionProgress,
    ProgressReporter,
    ReservedCollection,
    RetryableCollectionError,
)
from radar.prospects.fallback_geocoding import (
    SireneFallbackGeocodingError,
    SireneFallbackGeocodingSummary,
)
from radar.prospects.geolocation import SireneGeolocationReleaseSource
from radar.prospects.position_resolution import SirenePositionResolutionSummary
from radar.prospects.projection import SireneProspectProjectionSummary
from radar.prospects.sirene_collection import SireneEnumerationResult
from radar.prospects.sirene_pipeline import SireneProspectCollectionExecutor
from radar.prospects.status_reconciliation import SireneKnownStatusSummary
from radar.providers.sirene_geolocation import SireneGeolocationScan

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def reservation() -> ReservedCollection:
    return ReservedCollection(
        job_id=uuid4(),
        cycle_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        max_attempts=3,
        connector="SIRENE",
        longitude=-1.051952,
        latitude=43.70884,
        collection_radius_meters=50_000,
        last_safe_checkpoint=None,
    )


class FixtureReporter:
    def __init__(self) -> None:
        self.updates: list[tuple[CollectionProgress, dict[str, object] | None]] = []

    def update(
        self,
        progress: CollectionProgress,
        checkpoint: Mapping[str, object] | None = None,
    ) -> None:
        self.updates.append((progress, dict(checkpoint) if checkpoint is not None else None))


class FixtureEnumerator:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def enumerate(
        self,
        _reservation: ReservedCollection,
        _reporter: ProgressReporter,
    ) -> SireneEnumerationResult:
        self._calls.append("enumerate")
        return SireneEnumerationResult(
            announced_total=3,
            received_count=3,
            unique_siret_count=3,
            importable_count=2,
            page_count=2,
            batch_count=1,
            rejection_counts={"CLOSED": 1},
            source_metadata={
                "freshness": [
                    {"collection": "StockEtablissement", "last_availability": "2026-09-23"}
                ]
            },
        )


class FixtureGeolocationImporter:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def import_file(
        self,
        _reservation: ReservedCollection,
        _path: Path,
        _source: SireneGeolocationReleaseSource,
    ) -> SireneGeolocationScan:
        self._calls.append("geolocation")
        return SireneGeolocationScan(
            file_size_bytes=100,
            sha1="a" * 40,
            sha256="b" * 64,
            source_row_count=10,
            requested_siret_count=2,
            matched_siret_count=1,
            missing_siret_count=1,
            emitted_batch_count=1,
            columns=("SIRET",),
        )


class FixturePositionResolver:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self._count = 0

    def resolve(self, _reservation: ReservedCollection) -> SirenePositionResolutionSummary:
        self._count += 1
        self._calls.append(f"resolve-{self._count}")
        if self._count == 1:
            return SirenePositionResolutionSummary(2, 1, 0, 0, 1, 0, 0)
        return SirenePositionResolutionSummary(2, 1, 0, 1, 0, 0, 0)


class FixtureFallbackGeocoder:
    def __init__(self, calls: list[str], *, transient_failure: bool = False) -> None:
        self._calls = calls
        self._transient_failure = transient_failure

    def geocode_pending(
        self,
        _reservation: ReservedCollection,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> SireneFallbackGeocodingSummary:
        self._calls.append("geocode")
        if self._transient_failure:
            raise SireneFallbackGeocodingError(
                "temporary failure",
                transient=True,
                code="sirene_fallback_geocoder_server_error",
            )
        if on_progress is not None:
            on_progress(1, 1)
        return SireneFallbackGeocodingSummary(1, 1, 1, 0, 0)


class FixtureProjector:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def project(self, _reservation: ReservedCollection) -> SireneProspectProjectionSummary:
        self._calls.append("project")
        return SireneProspectProjectionSummary(2, 1, 0, 0, 1, 0)


class FixtureStatusReconciler:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def reconcile(
        self,
        _reservation: ReservedCollection,
        _reporter: ProgressReporter,
    ) -> SireneKnownStatusSummary:
        self._calls.append("statuses")
        return SireneKnownStatusSummary(1, 0, 0, 0, 1, 0)


def source() -> SireneGeolocationReleaseSource:
    return SireneGeolocationReleaseSource(
        resource_identifier="sirene-geolocation-2026-09",
        resource_url="https://example.data.gouv.fr/geolocation.parquet",
        published_on=date(2026, 9, 1),
        retrieved_at=NOW,
        license_name="Licence Ouverte 2.0",
    )


def executor(
    calls: list[str],
    *,
    transient_geocoder_failure: bool = False,
) -> SireneProspectCollectionExecutor:
    return SireneProspectCollectionExecutor(
        FixtureEnumerator(calls),
        FixtureGeolocationImporter(calls),
        Path("sirene-geolocation.parquet"),
        source(),
        FixturePositionResolver(calls),
        FixtureFallbackGeocoder(calls, transient_failure=transient_geocoder_failure),
        FixtureProjector(calls),
        FixtureStatusReconciler(calls),
    )


def test_composes_every_stage_and_returns_reconciled_coverage() -> None:
    calls: list[str] = []
    reporter = FixtureReporter()

    outcome = executor(calls).collect(reservation(), reporter)

    assert calls == [
        "enumerate",
        "geolocation",
        "resolve-1",
        "geocode",
        "resolve-2",
        "project",
        "statuses",
    ]
    assert outcome.result == "SUCCEEDED"
    assert outcome.counters["observations"] == 2
    assert outcome.counters["prospect_created_count"] == 1
    assert outcome.counters["outside_radius_count"] == 1
    assert outcome.counters["known_status_restricted_count"] == 1
    assert outcome.source_freshness["sirene_geolocation"] == "sirene-geolocation-2026-09"
    assert outcome.explicit_limits == {
        "search_circle_complete": True,
        "location_unknown_count": 0,
    }
    assert [progress.stage for progress, _ in reporter.updates] == [
        "sirene_geolocation",
        "sirene_position_resolution",
        "sirene_fallback_geocoding",
        "sirene_fallback_geocoding",
        "sirene_projection",
        "sirene_known_status",
        "sirene_complete",
    ]
    fallback_progress = [
        progress
        for progress, _ in reporter.updates
        if progress.stage == "sirene_fallback_geocoding"
    ]
    assert [(progress.processed, progress.total) for progress in fallback_progress] == [
        (0, 1),
        (1, 1),
    ]


def test_maps_temporary_fallback_failure_to_a_retryable_collection() -> None:
    calls: list[str] = []

    with pytest.raises(RetryableCollectionError) as captured:
        executor(calls, transient_geocoder_failure=True).collect(
            reservation(),
            FixtureReporter(),
        )

    assert captured.value.error.code == "sirene_fallback_geocoder_server_error"
    assert captured.value.observations_preserved == 2
    assert calls == ["enumerate", "geolocation", "resolve-1", "geocode"]
