"""Worker-facing DATAtourisme enumeration and projection orchestration."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from radar.collections.contracts import (
    CollectionProgress,
    PermanentCollectionError,
    ReservedCollection,
    RetryableCollectionError,
)
from radar.events.collection import DatatourismeCollectionExecutor, EventRunState
from radar.events.contracts import EventCandidate, EventLocationCandidate, EventPeriodCandidate
from radar.events.projection import EventProjectionSummary
from radar.providers.datatourisme import (
    DatatourismeCollectionSummary,
    DatatourismePage,
    DatatourismeTemporaryError,
)

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _reservation() -> ReservedCollection:
    return ReservedCollection(
        job_id=uuid4(),
        cycle_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        max_attempts=3,
        connector="DATATOURISME",
        longitude=-1.05,
        latitude=43.7,
        collection_radius_meters=50_000,
        last_safe_checkpoint=None,
    )


def _candidate() -> EventCandidate:
    return EventCandidate(
        external_identifier=str(uuid4()),
        source_uri="https://example.fr/event",
        producer_identifier=None,
        title="Fête",
        types=("Festival",),
        descriptions=(),
        locations=(EventLocationCandidate(-1.05, 43.7, ()),),
        periods=(EventPeriodCandidate("2027-01-01", None, None, None),),
        contacts=(),
        source_parties=(),
        source_updated_at=None,
        aggregator_updated_at=None,
        source_obsolete=None,
    )


PAGE = DatatourismePage(1, 1, 1, 1, (_candidate(),), {}, None, True)
SUMMARY = DatatourismeCollectionSummary(1, 1, 1, 1, 1, {})


class FakeBackend:
    def __init__(self, completed: bool = False) -> None:
        self.batch_id = uuid4()
        self.completed = completed
        self.recorded: list[int] = []
        self.failures: list[tuple[str, bool]] = []
        self.completed_count = 0

    def start_or_resume(self, _reservation: ReservedCollection, _now: datetime) -> EventRunState:
        return EventRunState(self.batch_id, SUMMARY if self.completed else None)

    def record_page(
        self,
        _reservation: ReservedCollection,
        _batch_id: UUID,
        page: DatatourismePage,
        _now: datetime,
    ) -> None:
        self.recorded.append(page.number)

    def complete(
        self,
        _reservation: ReservedCollection,
        _batch_id: UUID,
        _summary: DatatourismeCollectionSummary,
        _now: datetime,
    ) -> None:
        self.completed_count += 1

    def fail(
        self,
        _reservation: ReservedCollection,
        _batch_id: UUID,
        *,
        code: str,
        transient: bool,
        now: datetime,
    ) -> None:
        del now
        self.failures.append((code, transient))


class FakeReader:
    def __init__(self, temporary_failure: bool = False) -> None:
        self.calls = 0
        self.temporary_failure = temporary_failure

    def collect_events(
        self,
        _latitude: float,
        _longitude: float,
        _radius_meters: int,
        on_page: Callable[[DatatourismePage], None],
    ) -> DatatourismeCollectionSummary:
        self.calls += 1
        on_page(PAGE)
        if self.temporary_failure:
            raise DatatourismeTemporaryError("temporary")
        return SUMMARY


class FakeStager:
    def __init__(self) -> None:
        self.pages: list[int] = []

    def handle(
        self,
        _reservation: ReservedCollection,
        _batch_id: UUID,
        page: DatatourismePage,
    ) -> None:
        self.pages.append(page.number)


class FakeProjector:
    def __init__(self, summary: EventProjectionSummary | None = None) -> None:
        self.calls = 0
        self.summary = summary or EventProjectionSummary(1, 1, 0, 0, 0, 0)

    def project(self, _reservation: ReservedCollection) -> EventProjectionSummary:
        self.calls += 1
        return self.summary


class FakeReporter:
    def __init__(self) -> None:
        self.updates: list[tuple[CollectionProgress, Mapping[str, object] | None]] = []

    def update(
        self,
        progress: CollectionProgress,
        checkpoint: Mapping[str, object] | None = None,
    ) -> None:
        self.updates.append((progress, checkpoint))


def test_enumerates_stages_acknowledges_then_projects() -> None:
    backend = FakeBackend()
    reader = FakeReader()
    stager = FakeStager()
    projector = FakeProjector()
    reporter = FakeReporter()

    outcome = DatatourismeCollectionExecutor(
        backend, reader, stager, projector, clock=lambda: NOW
    ).collect(_reservation(), reporter)

    assert outcome.result == "SUCCEEDED"
    assert outcome.counters["event_created_count"] == 1
    assert outcome.explicit_limits == {"search_circle_complete": True}
    assert reader.calls == 1
    assert stager.pages == [1]
    assert backend.recorded == [1]
    assert backend.completed_count == 1
    assert projector.calls == 1
    assert reporter.updates[-1][0].stage == "datatourisme_complete"


def test_resumes_projection_without_calling_provider_after_complete_source() -> None:
    backend = FakeBackend(completed=True)
    reader = FakeReader()
    projector = FakeProjector()

    outcome = DatatourismeCollectionExecutor(
        backend, reader, FakeStager(), projector, clock=lambda: NOW
    ).collect(_reservation(), FakeReporter())

    assert outcome.result == "SUCCEEDED"
    assert reader.calls == 0
    assert backend.completed_count == 0
    assert projector.calls == 1
    assert outcome.counters["observations"] == 1


def test_temporary_failure_preserves_acknowledged_observations_for_retry() -> None:
    backend = FakeBackend()
    reporter = FakeReporter()

    with pytest.raises(RetryableCollectionError) as failure:
        DatatourismeCollectionExecutor(
            backend,
            FakeReader(temporary_failure=True),
            FakeStager(),
            FakeProjector(),
            clock=lambda: NOW,
        ).collect(_reservation(), reporter)

    assert failure.value.observations_preserved == 1
    assert backend.failures == [("datatourisme_temporary", True)]
    assert reporter.updates[-1][0].observations == 1


def test_rejects_wrong_connector_before_provider_io() -> None:
    current = _reservation()
    wrong = ReservedCollection(
        job_id=current.job_id,
        cycle_id=current.cycle_id,
        attempt_id=current.attempt_id,
        attempt_number=1,
        max_attempts=3,
        connector="SIRENE",
        longitude=current.longitude,
        latitude=current.latitude,
        collection_radius_meters=50_000,
        last_safe_checkpoint=None,
    )
    with pytest.raises(ValueError, match="DATAtourisme"):
        DatatourismeCollectionExecutor(
            FakeBackend(), FakeReader(), FakeStager(), FakeProjector()
        ).collect(wrong, FakeReporter())


def test_internal_projection_failure_is_permanent_and_not_marked_success() -> None:
    class BrokenProjector:
        def project(self, _reservation: ReservedCollection) -> EventProjectionSummary:
            from radar.events.projection import EventProjectionError

            raise EventProjectionError("broken")

    backend = FakeBackend()
    with pytest.raises(PermanentCollectionError) as failure:
        DatatourismeCollectionExecutor(
            backend, FakeReader(), FakeStager(), BrokenProjector(), clock=lambda: NOW
        ).collect(_reservation(), FakeReporter())
    assert failure.value.error.code == "datatourisme_projection"
    assert backend.completed_count == 1


def test_identity_conflict_returns_partial_without_publishing_coverage() -> None:
    outcome = DatatourismeCollectionExecutor(
        FakeBackend(),
        FakeReader(),
        FakeStager(),
        FakeProjector(EventProjectionSummary(1, 0, 0, 0, 0, 0, 1)),
        clock=lambda: NOW,
    ).collect(_reservation(), FakeReporter())

    assert outcome.result == "PARTIAL"
    assert outcome.error is not None
    assert outcome.error.code == "datatourisme_identity_conflict"
    assert outcome.counters["identity_conflict_count"] == 1
    assert outcome.explicit_limits == {}
