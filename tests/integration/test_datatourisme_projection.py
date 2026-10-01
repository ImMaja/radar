"""PostgreSQL projection of DATAtourisme events, periods and provenance."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from radar.events.contracts import EventCandidate, EventPeriodCandidate
from radar.events.projection import EventProjectionError, EventProjectionService
from radar.events.staging import EventCandidatePageStager
from radar.persistence.datatourisme_projection import SqlAlchemyEventProjectionRepository
from radar.persistence.datatourisme_staging import SqlAlchemyEventCandidateStagingRepository
from radar.providers.datatourisme import DatatourismePage

from .test_datatourisme_staging import NOW, candidate, seed_running_collection

pytestmark = pytest.mark.integration


def _page(number: int, candidates: tuple[EventCandidate, ...]) -> DatatourismePage:
    return DatatourismePage(
        number=number,
        announced_total=len(candidates),
        announced_total_pages=1,
        received_count=len(candidates),
        importable_candidates=candidates,
        rejection_counts={},
        next_link_fingerprint=None,
        terminal=True,
    )


def _finish_source(engine: Engine, batch_id: object, cycle_id: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE collection_batch SET state = 'SUCCEEDED' WHERE id = :batch_id"),
            {"batch_id": batch_id},
        )
        connection.execute(
            text(
                """
                UPDATE collection_source_run SET status = 'SUCCEEDED'
                WHERE collection_cycle_id = :cycle_id AND source = 'DATATOURISME_API'
                """
            ),
            {"cycle_id": cycle_id},
        )


def test_projection_creates_only_current_events_and_reconciles_retries(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    future = candidate(1)
    past = candidate(2, periods=(EventPeriodCandidate("2026-09-01", None, None, None),))
    outside = candidate(3, longitude=-2.2)
    invalid = candidate(4, periods=(EventPeriodCandidate("invalid", None, None, None),))
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    projector = EventProjectionService(
        SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
    )
    try:
        stager.handle(reservation, batch_id, _page(1, (future, past, outside, invalid)))
        with pytest.raises(EventProjectionError, match="completed source run"):
            projector.project(reservation)
        _finish_source(engine, batch_id, reservation.cycle_id)

        first = projector.project(reservation)
        second = projector.project(reservation)
        with engine.connect() as connection:
            events = (
                connection.execute(
                    text(
                        """
                    SELECT event.source_title, event.declared_status,
                           event.organizer_name, opportunity.hidden_at
                    FROM event JOIN opportunity ON opportunity.id = event.id
                    """
                    )
                )
                .mappings()
                .all()
            )
            periods = (
                connection.execute(text("SELECT start_date, source_path FROM event_period"))
                .mappings()
                .all()
            )
            sightings = connection.execute(
                text("SELECT count(*) FROM source_sighting")
            ).scalar_one()
            decisions = (
                connection.execute(
                    text(
                        """
                    SELECT decision FROM collection_item
                    WHERE collection_cycle_id = :cycle_id ORDER BY item_rank
                    """
                    ),
                    {"cycle_id": reservation.cycle_id},
                )
                .scalars()
                .all()
            )
    finally:
        engine.dispose()

    assert first == second
    assert (
        first.requested_count,
        first.created_count,
        first.rejected_count,
        first.counted_only_count,
    ) == (4, 1, 2, 1)
    assert decisions == ["CREATED", "REJECTED", "COUNTED_ONLY", "REJECTED"]
    assert len(events) == 1
    assert events[0]["source_title"] == "Événement 1"
    assert events[0]["declared_status"] == "UNKNOWN"
    assert events[0]["organizer_name"] is None
    assert periods[0]["source_path"] == "periods[0]"
    assert sightings == 1


def test_projection_updates_a_hidden_event_without_replacing_user_periods(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    projector = EventProjectionService(
        SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
    )
    try:
        stager.handle(reservation, batch_id, _page(1, (candidate(10),)))
        _finish_source(engine, batch_id, reservation.cycle_id)
        assert projector.project(reservation).created_count == 1
        user_set_id = uuid4()
        with engine.begin() as connection:
            event_id = connection.execute(text("SELECT id FROM event")).scalar_one()
            connection.execute(
                text(
                    """
                    UPDATE opportunity SET hidden_at = :now, hidden_reason = 'NOT_RELEVANT'
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO event_period_set (
                        id, event_id, layer, is_current, created_at
                    ) VALUES (:set_id, :event_id, 'USER', TRUE, :now)
                    """
                ),
                {"set_id": user_set_id, "event_id": event_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO event_period (
                        id, period_set_id, display_order, start_date, end_date,
                        interpretation_timezone, precision, source_path, created_at
                    ) VALUES (
                        :id, :set_id, 0, '2028-01-01', '2028-01-01',
                        'Europe/Paris', 'DATE_ONLY', 'user', :now
                    )
                    """
                ),
                {"id": uuid4(), "set_id": user_set_id, "now": NOW},
            )
            next_attempt_id = uuid4()
            connection.execute(
                text(
                    """
                    UPDATE collection_attempt SET finished_at = :now WHERE id = :attempt_id
                    """
                ),
                {"attempt_id": reservation.attempt_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO collection_attempt (
                        id, collection_job_id, attempt_number, worker_id,
                        started_at, heartbeat_at
                    ) VALUES (:id, :job_id, 2, 'test-worker', :now, :now)
                    """
                ),
                {"id": next_attempt_id, "job_id": reservation.job_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    UPDATE collection_job SET attempt_count = 2 WHERE id = :job_id
                    """
                ),
                {"job_id": reservation.job_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE collection_batch SET state = 'RUNNING', attempt_count = 2,
                        last_collection_attempt_id = :attempt_id
                    WHERE id = :batch_id
                    """
                ),
                {"attempt_id": next_attempt_id, "batch_id": batch_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE collection_source_run SET status = 'RUNNING'
                    WHERE collection_cycle_id = :cycle_id
                    """
                ),
                {"cycle_id": reservation.cycle_id},
            )
        retry = replace(reservation, attempt_id=next_attempt_id, attempt_number=2)
        changed = replace(
            candidate(10),
            title="Événement 10 corrigé",
            periods=(EventPeriodCandidate("2026-09-15", None, None, None),),
        )
        stager.handle(retry, batch_id, _page(1, (changed,)))
        _finish_source(engine, batch_id, retry.cycle_id)
        summary = projector.project(retry)
        with engine.connect() as connection:
            event = (
                connection.execute(
                    text(
                        """
                    SELECT event.id, event.source_title, opportunity.hidden_at
                    FROM event JOIN opportunity ON opportunity.id = event.id
                    """
                    )
                )
                .mappings()
                .one()
            )
            sets = (
                connection.execute(
                    text(
                        """
                    SELECT layer, is_current, retired_at
                    FROM event_period_set WHERE event_id = :event_id
                    ORDER BY layer, is_current
                    """
                    ),
                    {"event_id": event_id},
                )
                .mappings()
                .all()
            )
            binding_count = connection.execute(
                text("SELECT count(*) FROM source_binding")
            ).scalar_one()
    finally:
        engine.dispose()

    assert summary.updated_count == 1
    assert event["id"] == event_id
    assert event["source_title"] == "Événement 10 corrigé"
    assert event["hidden_at"] == NOW
    assert binding_count == 1
    assert [(row["layer"], row["is_current"]) for row in sets] == [
        ("SOURCE", False),
        ("SOURCE", True),
        ("USER", True),
    ]
    assert sets[0]["retired_at"] == NOW
