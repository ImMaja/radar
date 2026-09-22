"""Tests for bounded Sirene prospect-projection orchestration."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from radar.collections.contracts import ReservedCollection
from radar.prospects.projection import (
    SireneProjectionPage,
    SireneProspectProjectionError,
    SireneProspectProjectionService,
    SireneProspectProjectionSummary,
)

NOW = datetime(2026, 9, 22, 10, tzinfo=UTC)


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
    def __init__(self, summary: SireneProspectProjectionSummary) -> None:
        self.pages = (
            SireneProjectionPage(uuid4(), 1),
            SireneProjectionPage(uuid4(), 2),
        )
        self.result = summary
        self.projected: list[tuple[SireneProjectionPage, datetime]] = []
        self.summary_calls = 0

    def pending_pages(
        self,
        _reservation: ReservedCollection,
    ) -> tuple[SireneProjectionPage, ...]:
        return self.pages

    def project_page(
        self,
        _reservation: ReservedCollection,
        page: SireneProjectionPage,
        now: datetime,
    ) -> None:
        self.projected.append((page, now))

    def summary(
        self,
        _reservation: ReservedCollection,
    ) -> SireneProspectProjectionSummary:
        self.summary_calls += 1
        return self.result


def test_service_projects_pending_pages_then_reconciles() -> None:
    summary = SireneProspectProjectionSummary(
        requested_count=4,
        created_count=2,
        updated_count=0,
        unchanged_count=1,
        counted_only_count=1,
        location_unknown_count=1,
    )
    backend = FixtureBackend(summary)
    service = SireneProspectProjectionService(backend, clock=lambda: NOW)

    assert service.project(reservation()) == summary
    assert backend.projected == [(backend.pages[0], NOW), (backend.pages[1], NOW)]
    assert backend.summary_calls == 1


def test_service_rejects_invalid_counts_and_another_connector() -> None:
    invalid = SireneProspectProjectionSummary(
        requested_count=3,
        created_count=1,
        updated_count=0,
        unchanged_count=0,
        counted_only_count=1,
        location_unknown_count=0,
    )
    service = SireneProspectProjectionService(FixtureBackend(invalid), clock=lambda: NOW)

    with pytest.raises(SireneProspectProjectionError, match="do not reconcile"):
        service.project(reservation())
    with pytest.raises(ValueError, match="only a Sirene collection"):
        service.project(replace(reservation(), connector="DATATOURISME"))
