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
    SireneFallbackGeocodingFailure,
    SireneFallbackGeocodingRun,
    SireneFallbackGeocodingService,
    SireneFallbackGeocodingSummary,
    SireneFallbackGeocodingTarget,
    StagedSireneFallbackGeocoding,
    normalize_fallback_geocoding,
    normalize_geocoding_query_part,
)

NOW = datetime(2026, 9, 21, 14, tzinfo=UTC)


def reservation(*, attempt_number: int = 1, max_attempts: int = 3) -> ReservedCollection:
    return ReservedCollection(
        job_id=uuid4(),
        cycle_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=attempt_number,
        max_attempts=max_attempts,
        connector="SIRENE",
        longitude=-1.051952,
        latitude=43.70884,
        collection_radius_meters=50_000,
        last_safe_checkpoint=None,
    )


def target(
    address: str = "12 RUE SAINT PIERRE 40100 DAX",
    *,
    query_is_sufficient: bool = True,
) -> SireneFallbackGeocodingTarget:
    return SireneFallbackGeocodingTarget(
        collection_item_id=uuid4(),
        external_identity_id=uuid4(),
        input_address=address,
        expected_municipality_code="40088",
        query_is_sufficient=query_is_sufficient,
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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (None, ""),
        ("  RUE   SAINT PIERRE ", "RUE SAINT PIERRE"),
        ('"ABCDEFGHIJK"', "ABCDEFGHIJK"),
        ('LIEU "DIT"', 'LIEU "DIT"'),
        ('""', ""),
    ],
)
def test_normalizes_query_parts_without_changing_balanced_internal_quotes(
    source: object,
    expected: str,
) -> None:
    assert normalize_geocoding_query_part(source) == expected


class FixtureBackend:
    def __init__(self, targets: tuple[SireneFallbackGeocodingTarget, ...]) -> None:
        self.run = SireneFallbackGeocodingRun(id=uuid4(), status="RUNNING")
        self.targets = targets
        self.staged: list[StagedSireneFallbackGeocoding] = []
        self.failures: list[SireneFallbackGeocodingFailure] = []

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
        skipped = sum(item.outcome == "SKIPPED_INSUFFICIENT_ADDRESS" for item in self.staged)
        return SireneFallbackGeocodingSummary(
            requested_count=len(self.staged),
            matched_count=matched,
            usable_count=matched,
            to_verify_count=0,
            missing_count=missing,
            skipped_count=skipped,
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
        failure: SireneFallbackGeocodingFailure,
        now: datetime,
    ) -> None:
        assert now == NOW
        self.failures.append(failure)


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
        "provider_requested": True,
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

    progress: list[tuple[int, int]] = []
    summary = service.geocode_pending(
        reservation(), lambda done, total: progress.append((done, total))
    )

    assert summary.requested_count == 2
    assert summary.matched_count == 1
    assert summary.missing_count == 1
    assert [item.outcome for item in backend.staged] == ["MATCHED", "NOT_FOUND"]
    assert geocoder.queries == [targets[0].input_address, targets[1].input_address]
    assert progress == [(2, 2)]


def test_service_skips_an_insufficient_address_without_calling_the_provider() -> None:
    insufficient = target("X 40100 DAX", query_is_sufficient=False)
    backend = FixtureBackend((insufficient,))
    geocoder = SequencedGeocoder([])
    service = SireneFallbackGeocodingService(
        backend,
        geocoder,
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
        sleeper=lambda _seconds: None,
    )

    summary = service.geocode_pending(reservation())

    assert summary.requested_count == 1
    assert summary.missing_count == 1
    assert summary.skipped_count == 1
    assert geocoder.queries == []
    assert len(backend.staged) == 1
    staged = backend.staged[0]
    assert staged.outcome == "SKIPPED_INSUFFICIENT_ADDRESS"
    assert staged.provider_requested is False
    assert staged.payload["request"] == {
        "input_address": "X 40100 DAX",
        "expected_municipality_code": "40088",
        "provider_requested": False,
    }
    assert backend.failures == []


def test_service_records_a_transient_provider_failure_for_resume() -> None:
    backend = FixtureBackend((target(),))
    service = SireneFallbackGeocodingService(
        backend,
        SequencedGeocoder(
            [
                GeocodingUnavailableError(
                    "unavailable",
                    reason="rate_limited",
                    status_code=429,
                    retry_after_seconds=120,
                    attempts=1,
                )
            ]
        ),
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(SireneFallbackGeocodingError) as captured:
        service.geocode_pending(reservation())

    assert captured.value.transient is True
    assert captured.value.code == "sirene_fallback_geocoder_rate_limited"
    assert backend.failures == [
        SireneFallbackGeocodingFailure(
            code="geocoder_rate_limited",
            final=False,
            http_status_code=429,
            retry_after_seconds=120,
            attempts=1,
        )
    ]
    assert backend.staged == []


def test_service_treats_a_rejected_request_as_a_permanent_failure() -> None:
    backend = FixtureBackend((target(),))
    service = SireneFallbackGeocodingService(
        backend,
        SequencedGeocoder(
            [
                GeocodingUnavailableError(
                    "rejected",
                    reason="request_rejected",
                    status_code=400,
                )
            ]
        ),
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(SireneFallbackGeocodingError) as captured:
        service.geocode_pending(reservation())

    assert captured.value.transient is False
    assert captured.value.code == "sirene_fallback_geocoder_request_rejected"
    assert backend.failures == [
        SireneFallbackGeocodingFailure(
            code="geocoder_request_rejected",
            final=True,
            http_status_code=400,
            attempts=1,
        )
    ]


def test_service_marks_source_final_when_the_durable_retry_budget_is_exhausted() -> None:
    backend = FixtureBackend((target(),))
    service = SireneFallbackGeocodingService(
        backend,
        SequencedGeocoder(
            [
                GeocodingUnavailableError(
                    "unavailable",
                    reason="server_error",
                    status_code=503,
                    attempts=5,
                )
            ]
        ),
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(SireneFallbackGeocodingError) as captured:
        service.geocode_pending(reservation(attempt_number=3, max_attempts=3))

    assert captured.value.transient is True
    assert backend.failures == [
        SireneFallbackGeocodingFailure(
            code="geocoder_server_error",
            final=True,
            http_status_code=503,
            attempts=5,
        )
    ]
