"""Durable DATAtourisme page evidence and whole-enumeration retry."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from radar.events.collection import EventExecutionError
from radar.events.projection import EventProjectionService
from radar.events.staging import EventCandidatePageStager
from radar.persistence.datatourisme_execution import SqlAlchemyEventExecutionRepository
from radar.persistence.datatourisme_projection import SqlAlchemyEventProjectionRepository
from radar.persistence.datatourisme_staging import SqlAlchemyEventCandidateStagingRepository
from radar.providers.datatourisme import DatatourismeCollectionSummary, DatatourismePage

from .test_datatourisme_staging import NOW, candidate, seed_running_collection

pytestmark = pytest.mark.integration


def test_restarts_the_whole_enumeration_and_reuses_the_same_event_revision(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE collection_source_run
                SET status = 'PLANNED', started_at = NULL
                WHERE collection_cycle_id = :cycle_id
                """
            ),
            {"cycle_id": reservation.cycle_id},
        )
        connection.execute(
            text(
                """
                UPDATE collection_batch
                SET state = 'WAITING', last_collection_attempt_id = NULL,
                    attempt_count = 0, started_at = NULL
                WHERE id = :batch_id
                """
            ),
            {"batch_id": batch_id},
        )
    repository = SqlAlchemyEventExecutionRepository(engine)
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    page = DatatourismePage(1, 1, 1, 1, (candidate(51),), {}, None, True)
    summary = DatatourismeCollectionSummary(1, 1, 1, 1, 1, {})
    try:
        state = repository.start_or_resume(reservation, NOW)
        assert state.batch_id == batch_id
        assert state.completed_summary is None
        with pytest.raises(EventExecutionError, match="incomplete"):
            repository.complete(reservation, batch_id, summary, NOW)
        stager.handle(reservation, batch_id, page)
        repository.record_page(reservation, batch_id, page, NOW)
        repository.fail(reservation, batch_id, code="temporary", transient=True, now=NOW)

        next_attempt_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE collection_attempt SET finished_at = :now WHERE id = :id"),
                {"id": reservation.attempt_id, "now": NOW},
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
                text("UPDATE collection_job SET attempt_count = 2 WHERE id = :id"),
                {"id": reservation.job_id},
            )
        retry = replace(reservation, attempt_id=next_attempt_id, attempt_number=2)
        retry_state = repository.start_or_resume(retry, NOW)
        assert retry_state.batch_id == batch_id
        stager.handle(retry, batch_id, page)
        repository.record_page(retry, batch_id, page, NOW)
        repository.complete(retry, batch_id, summary, NOW)
        projection_attempt_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE collection_attempt SET finished_at = :now WHERE id = :id"),
                {"id": retry.attempt_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO collection_attempt (
                        id, collection_job_id, attempt_number, worker_id,
                        started_at, heartbeat_at
                    ) VALUES (:id, :job_id, 3, 'test-worker', :now, :now)
                    """
                ),
                {"id": projection_attempt_id, "job_id": reservation.job_id, "now": NOW},
            )
            connection.execute(
                text("UPDATE collection_job SET attempt_count = 3 WHERE id = :id"),
                {"id": reservation.job_id},
            )
        projection_attempt = replace(
            reservation, attempt_id=projection_attempt_id, attempt_number=3
        )
        completed = repository.start_or_resume(projection_attempt, NOW)
        assert completed.completed_summary == summary
        projected = EventProjectionService(
            SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
        ).project(projection_attempt)
        with engine.connect() as connection:
            counts = (
                connection.execute(
                    text(
                        """
                    SELECT
                        (SELECT count(*) FROM collection_page) AS pages,
                        (SELECT count(*) FROM source_observation
                         WHERE data_source_code = 'DATATOURISME_API') AS observations,
                        (SELECT count(*) FROM collection_item) AS items,
                        (SELECT count(*) FROM event) AS events,
                        (SELECT request_count FROM collection_source_run
                         WHERE collection_cycle_id = :cycle_id) AS requests,
                        (SELECT retry_count FROM collection_source_run
                         WHERE collection_cycle_id = :cycle_id) AS retries
                    """
                    ),
                    {"cycle_id": reservation.cycle_id},
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()

    assert projected.created_count == 1
    assert counts == {
        "pages": 2,
        "observations": 1,
        "items": 2,
        "events": 1,
        "requests": 2,
        "retries": 1,
    }


def test_empty_provider_page_completes_with_zero_announced_pages(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    repository = SqlAlchemyEventExecutionRepository(engine)
    page = DatatourismePage(1, 0, 0, 0, (), {}, None, True)
    summary = DatatourismeCollectionSummary(0, 0, 0, 0, 1, {})
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE collection_batch SET state = 'WAITING',
                        last_collection_attempt_id = NULL, attempt_count = 0
                    WHERE id = :batch_id
                    """
                ),
                {"batch_id": batch_id},
            )
        repository.start_or_resume(reservation, NOW)
        repository.record_page(reservation, batch_id, page, NOW)
        repository.complete(reservation, batch_id, summary, NOW)
        assert repository.start_or_resume(reservation, NOW).completed_summary == summary
    finally:
        engine.dispose()


def test_rejects_an_unreconciled_page_before_recording_success(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    repository = SqlAlchemyEventExecutionRepository(engine)
    try:
        with pytest.raises(EventExecutionError, match="candidate counts"):
            repository.record_page(
                reservation,
                batch_id,
                DatatourismePage(1, 1, 1, 1, (), {}, None, True),
                NOW,
            )
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM collection_page")).scalar_one() == 0
            )
    finally:
        engine.dispose()
