"""Tests for durable DATAtourisme candidate preparation."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from radar.collections.contracts import Connector, ReservedCollection
from radar.events.contracts import (
    EventCandidate,
    EventDescriptionCandidate,
    EventLocationCandidate,
    EventPeriodCandidate,
)
from radar.events.staging import (
    EventCandidatePageStager,
    EventCandidateStagingError,
    StagedEventCandidate,
    normalize_event_candidate,
)
from radar.providers.datatourisme import DatatourismePage

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
IDENTIFIER = "5c92ef83-51c2-4dad-adfd-105d56320b41"


def reservation(connector: Connector = "DATATOURISME") -> ReservedCollection:
    return ReservedCollection(
        job_id=uuid4(),
        cycle_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        max_attempts=3,
        connector=connector,
        longitude=-1.051952,
        latitude=43.70884,
        collection_radius_meters=50_000,
        last_safe_checkpoint=None,
    )


def candidate(identifier: str = IDENTIFIER) -> EventCandidate:
    return EventCandidate(
        external_identifier=identifier,
        source_uri=f"https://data.datatourisme.fr/{identifier}",
        producer_identifier="source-1",
        title="Fête locale",
        types=("EntertainmentAndEvent", "Festival"),
        descriptions=(EventDescriptionCandidate("Résumé", "Description"),),
        locations=(EventLocationCandidate(-1.051952, 43.70884, ()),),
        periods=(
            EventPeriodCandidate("2026-09-01", "2026-09-02", None, None),
            EventPeriodCandidate("2027-07-12", "2027-07-13", "10:00", "23:00"),
            EventPeriodCandidate("invalid", None, None, None),
        ),
        contacts=(),
        source_parties=(),
        source_updated_at="2026-09-29T12:00:00+00:00",
        aggregator_updated_at="2026-09-29T13:00:00+00:00",
        source_obsolete=None,
    )


def page(*candidates: EventCandidate, received_count: int | None = None) -> DatatourismePage:
    return DatatourismePage(
        number=1,
        announced_total=len(candidates),
        announced_total_pages=1,
        received_count=received_count if received_count is not None else len(candidates),
        importable_candidates=tuple(candidates),
        rejection_counts={},
        next_link_fingerprint=None,
        terminal=True,
    )


class FixtureBackend:
    def __init__(self) -> None:
        self.calls: list[
            tuple[
                ReservedCollection,
                UUID,
                DatatourismePage,
                tuple[StagedEventCandidate, ...],
                datetime,
            ]
        ] = []

    def stage_page(
        self,
        current: ReservedCollection,
        batch_id: UUID,
        current_page: DatatourismePage,
        candidates: tuple[StagedEventCandidate, ...],
        now: datetime,
    ) -> None:
        self.calls.append((current, batch_id, current_page, candidates, now))


def test_normalizes_identity_revision_periods_and_source_freshness() -> None:
    staged = normalize_event_candidate(candidate(), 1, NOW)

    assert staged.external_identifier == IDENTIFIER
    assert len(staged.identifier_fingerprint) == 64
    assert len(staged.content_fingerprint) == 64
    assert staged.source_updated_at == datetime(2026, 9, 29, 12, tzinfo=UTC)
    assert staged.temporal_state == "UPCOMING"
    assert len(staged.validated_periods) == 2
    assert staged.validated_periods[1] == {
        "source_index": 2,
        "start_date": "2027-07-12",
        "end_date": "2027-07-13",
        "start_time": "10:00:00",
        "end_time": "23:00:00",
        "precision": "DATE_AND_TIME",
        "interpretation_timezone": "Europe/Paris",
    }
    assert staged.period_rejection_counts == {"missing_or_invalid_start_date": 1}
    assert staged.payload["title"] == "Fête locale"


def test_revision_fingerprint_is_stable_and_changes_with_source_content() -> None:
    first = normalize_event_candidate(candidate(), 1, NOW)
    repeated = normalize_event_candidate(candidate(), 8, NOW)
    changed = normalize_event_candidate(replace(candidate(), title="Autre titre"), 1, NOW)

    assert repeated.identifier_fingerprint == first.identifier_fingerprint
    assert repeated.content_fingerprint == first.content_fingerprint
    assert changed.identifier_fingerprint == first.identifier_fingerprint
    assert changed.content_fingerprint != first.content_fingerprint


def test_invalid_or_naive_source_timestamp_remains_only_in_the_payload() -> None:
    invalid = normalize_event_candidate(
        replace(candidate(), source_updated_at="not-an-instant"), 1, NOW
    )
    naive = normalize_event_candidate(
        replace(candidate(), source_updated_at="2026-09-29T12:00:00"), 1, NOW
    )

    assert invalid.source_updated_at is None
    assert invalid.payload["source_updated_at"] == "not-an-instant"
    assert naive.source_updated_at is None


def test_page_stager_forwards_one_normalized_atomic_page() -> None:
    backend = FixtureBackend()
    stager = EventCandidatePageStager(backend, clock=lambda: NOW)
    current = reservation()
    batch_id = uuid4()
    current_page = page(candidate())

    stager.handle(current, batch_id, current_page)

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call[0] == current
    assert call[1] == batch_id
    assert call[2] == current_page
    assert call[3][0].item_rank == 1
    assert call[4] == NOW


def test_page_stager_reconciles_counts_and_rejects_duplicate_uuid() -> None:
    stager = EventCandidatePageStager(FixtureBackend(), clock=lambda: NOW)

    with pytest.raises(EventCandidateStagingError, match="do not match"):
        stager.handle(reservation(), uuid4(), page(candidate(), received_count=2))
    with pytest.raises(EventCandidateStagingError, match="duplicate UUID"):
        stager.handle(reservation(), uuid4(), page(candidate(), candidate()))


def test_page_stager_rejects_wrong_connector_and_invalid_uuid() -> None:
    stager = EventCandidatePageStager(FixtureBackend(), clock=lambda: NOW)

    with pytest.raises(ValueError, match="only a DATAtourisme"):
        stager.handle(reservation("SIRENE"), uuid4(), page(candidate()))
    with pytest.raises(ValueError, match="UUID is invalid"):
        stager.handle(reservation(), uuid4(), page(candidate("invalid")))
