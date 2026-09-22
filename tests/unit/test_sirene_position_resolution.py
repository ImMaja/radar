"""Tests for deterministic Sirene candidate-position resolution."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from radar.collections.contracts import ReservedCollection
from radar.prospects.position_resolution import (
    SirenePositionResolutionError,
    SirenePositionResolutionService,
    SirenePositionResolutionSummary,
)

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


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


class FixtureBackend:
    def __init__(self, summary: SirenePositionResolutionSummary) -> None:
        self.summary = summary
        self.calls: list[tuple[ReservedCollection, datetime]] = []

    def resolve_positions(
        self,
        current: ReservedCollection,
        now: datetime,
    ) -> SirenePositionResolutionSummary:
        self.calls.append((current, now))
        return self.summary


def test_service_returns_reconciled_resolution_counts() -> None:
    summary = SirenePositionResolutionSummary(
        requested_count=4,
        api_selected_count=2,
        file_selected_count=1,
        geocoder_selected_count=0,
        geocoding_required_count=1,
        unresolved_count=0,
        divergent_count=1,
    )
    backend = FixtureBackend(summary)
    service = SirenePositionResolutionService(backend, clock=lambda: NOW)
    current = reservation()

    assert service.resolve(current) == summary
    assert backend.calls == [(current, NOW)]


def test_service_rejects_invalid_counters_and_another_connector() -> None:
    invalid = SirenePositionResolutionSummary(
        requested_count=3,
        api_selected_count=1,
        file_selected_count=1,
        geocoder_selected_count=0,
        geocoding_required_count=0,
        unresolved_count=0,
        divergent_count=0,
    )
    service = SirenePositionResolutionService(FixtureBackend(invalid), clock=lambda: NOW)

    with pytest.raises(SirenePositionResolutionError, match="do not reconcile"):
        service.resolve(reservation())
    with pytest.raises(ValueError, match="only a Sirene collection"):
        service.resolve(replace(reservation(), connector="DATATOURISME"))
