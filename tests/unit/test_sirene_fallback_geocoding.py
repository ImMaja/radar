"""Tests for durable Sirene fallback-geocoding orchestration."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from radar.collections.contracts import ReservedCollection
from radar.geography.contracts import (
    AddressNotFoundError,
    GeocodedAddress,
    GeocodingUnavailableError,
    StructuredAddress,
)
from radar.prospects.fallback_geocoding import (
    SireneFallbackGeocodingError,
    SireneFallbackGeocodingRun,
    SireneFallbackGeocodingService,
    SireneFallbackGeocodingSummary,
    SireneFallbackGeocodingTarget,
    StagedSireneFallbackGeocoding,
    normalize_fallback_geocoding,
)

NOW = datetime(2026, 9, 21, 14, tzinfo=UTC)


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


def target(address: str = "12 RUE SAINT PIERRE 40100 DAX") -> SireneFallbackGeocodingTarget:
    return SireneFallbackGeocodingTarget(
        collection_item_id=uuid4(),
        external_identity_id=uuid4(),
        input_address=address,
        expected_municipality_code="40088",
    )


def result() -> GeocodedAddress:
    return GeocodedAddress(
        normalized_label="12 Rue Saint Pierre 40100 Dax",
        structured_address=StructuredAddress(
            house_number="12",
            street="Rue Saint Pierre",
            postcode="40100",
            city="Dax",
            context="40, Landes, Nouvelle-Aquitaine",
        ),
        longitude=-1.051952,
        latitude=43.70884,
        municipality_code="40088",
        ban_id="40088_1750_00012",
        result_type="housenumber",
        score=0.9653,
        provider_name="Géoplateforme",
        provider_url="https://data.geopf.fr/geocodage/search",
    )


class FixtureBackend:
    def __init__(self, targets: tuple[SireneFallbackGeocodingTarget, ...]) -> None:
        self.run = SireneFallbackGeocodingRun(id=uuid4(), status="RUNNING")
        self.targets = targets
        self.staged: list[StagedSireneFallbackGeocoding] = []
        self.failures: list[tuple[str, bool]] = []

    def prepare_run(
        self,
        _reservation: ReservedCollection,
        _now: datetime,
    ) -> SireneFallbackGeocodingRun:
        return self.run

    def pending_targets(
        self,
        _reservation: ReservedCollection,
        _run: SireneFallbackGeocodingRun,
    ) -> tuple[SireneFallbackGeocodingTarget, ...]:
        return self.targets

    def stage_outcome(
        self,
        _reservation: ReservedCollection,
        _run: SireneFallbackGeocodingRun,
        outcome: StagedSireneFallbackGeocoding,
        _now: datetime,
    ) -> None:
        self.staged.append(outcome)

    def complete_run(
        self,
        _reservation: ReservedCollection,
        _run: SireneFallbackGeocodingRun,
        _now: datetime,
    ) -> SireneFallbackGeocodingSummary:
        matched = sum(item.outcome == "MATCHED" for item in self.staged)
        missing = len(self.staged) - matched
        return SireneFallbackGeocodingSummary(
            requested_count=len(self.staged),
            matched_count=matched,
            usable_count=matched,
            to_verify_count=0,
            missing_count=missing,
        )

    def completed_summary(
        self,
        _reservation: ReservedCollection,
        _run: SireneFallbackGeocodingRun,
    ) -> SireneFallbackGeocodingSummary:
        raise AssertionError("the fixture run is not already complete")

    def record_failure(
        self,
        _reservation: ReservedCollection,
        _run: SireneFallbackGeocodingRun,
        *,
        code: str,
        final: bool,
        now: datetime,
    ) -> None:
        assert now == NOW
        self.failures.append((code, final))


class SequencedGeocoder:
    def __init__(self, outcomes: list[GeocodedAddress | Exception]) -> None:
        self.outcomes = outcomes
        self.queries: list[str] = []

    def geocode(self, input_address: str) -> GeocodedAddress:
        self.queries.append(input_address)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_normalization_is_stable_and_keeps_provider_evidence_separate() -> None:
    current_target = target()
    first = normalize_fallback_geocoding(current_target, "MATCHED", result())
    repeated = normalize_fallback_geocoding(current_target, "MATCHED", result())

    assert first == repeated
    assert first.payload["request"] == {
        "input_address": "12 RUE SAINT PIERRE 40100 DAX",
        "expected_municipality_code": "40088",
    }
    assert first.payload["result"]["score"] == 0.9653  # type: ignore[index]
    assert first.result_type == "housenumber"


def test_service_persists_success_and_not_found_without_hiding_either() -> None:
    targets = (target(), target("40100 DAX"))
    backend = FixtureBackend(targets)
    geocoder = SequencedGeocoder([result(), AddressNotFoundError("not found")])
    service = SireneFallbackGeocodingService(
        backend,
        geocoder,
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
        sleeper=lambda _seconds: None,
    )

    summary = service.geocode_pending(reservation())

    assert summary.requested_count == 2
    assert summary.matched_count == 1
    assert summary.missing_count == 1
    assert [item.outcome for item in backend.staged] == ["MATCHED", "NOT_FOUND"]
    assert geocoder.queries == [targets[0].input_address, targets[1].input_address]


def test_service_records_a_transient_provider_failure_for_resume() -> None:
    backend = FixtureBackend((target(),))
    service = SireneFallbackGeocodingService(
        backend,
        SequencedGeocoder([GeocodingUnavailableError("unavailable")]),
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(SireneFallbackGeocodingError) as captured:
        service.geocode_pending(reservation())

    assert captured.value.transient is True
    assert backend.failures == [("geocoder_unavailable", False)]
    assert backend.staged == []
