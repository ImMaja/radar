"""Contract tests for bounded DATAtourisme event projection."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import pytest

from radar.collections.contracts import ReservedCollection
from radar.events.projection import (
    EventProjectionError,
    EventProjectionPage,
    EventProjectionService,
    EventProjectionSummary,
)
from radar.persistence.datatourisme_projection import _periods

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


class FakeBackend:
    def __init__(self) -> None:
        self.pages = (EventProjectionPage(uuid4(), 1), EventProjectionPage(uuid4(), 2))
        self.projected: list[EventProjectionPage] = []

    def pending_pages(self, _reservation: ReservedCollection) -> tuple[EventProjectionPage, ...]:
        return self.pages

    def project_page(
        self, _reservation: ReservedCollection, page: EventProjectionPage, _now: datetime
    ) -> None:
        self.projected.append(page)

    def summary(self, _reservation: ReservedCollection) -> EventProjectionSummary:
        return EventProjectionSummary(2, 1, 0, 1, 0, 0)


def reservation(
    connector: Literal["SIRENE", "DATATOURISME"] = "DATATOURISME",
) -> ReservedCollection:
    return ReservedCollection(
        job_id=uuid4(),
        cycle_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        max_attempts=3,
        connector=connector,
        longitude=-1.05,
        latitude=43.7,
        collection_radius_meters=50_000,
        last_safe_checkpoint=None,
    )


def test_service_projects_pending_pages_and_reconciles_decisions() -> None:
    backend = FakeBackend()
    summary = EventProjectionService(backend, clock=lambda: NOW).project(reservation())

    assert backend.projected == list(backend.pages)
    assert summary.created_count == 1


def test_service_rejects_another_connector_or_missing_decision() -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="DATAtourisme"):
        EventProjectionService(backend).project(reservation("SIRENE"))
    with pytest.raises(EventProjectionError, match="reconcile"):
        EventProjectionSummary(2, 1, 0, 0, 0, 0).validate()


def test_period_projection_rejects_malformed_or_missing_complete_sets() -> None:
    with pytest.raises(EventProjectionError, match="no validated period"):
        _periods({})
    with pytest.raises(EventProjectionError, match="malformed"):
        _periods({"validated_periods": [{"source_index": 1}]})
    with pytest.raises(EventProjectionError, match="source contract"):
        _periods(
            {
                "validated_periods": [
                    {
                        "source_index": 1,
                        "start_date": "2027-01-02",
                        "end_date": "2027-01-01",
                        "start_time": None,
                        "end_time": None,
                        "precision": "DATE_ONLY",
                        "interpretation_timezone": "Europe/Paris",
                    }
                ]
            }
        )
