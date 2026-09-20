"""PostgreSQL integration tests for durable collection execution."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from radar.collections.contracts import (
    CollectionError,
    CollectionOutcome,
    CollectionProgress,
    ConnectorSpecification,
    PermanentCollectionError,
    ProgressReporter,
    ReservedCollection,
    RetryableCollectionError,
)
from radar.collections.worker import CollectionWorker
from radar.geography.contracts import GeocodedAddress, StructuredAddress
from radar.persistence.collections import SqlAlchemyCollectionRepository
from radar.persistence.geography import SqlAlchemyGeographyRepository

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
SPECIFICATION = ConnectorSpecification("test-v1", "a" * 64)


def confirm_position(database_url: str, *, longitude: float = -1.051952) -> None:
    engine = create_engine(database_url)
    repository = SqlAlchemyGeographyRepository(engine)
    try:
        candidate = repository.save_candidate(
            "12 rue Saint-Pierre 40100 Dax",
            GeocodedAddress(
                normalized_label="12 Rue Saint Pierre 40100 Dax",
                structured_address=StructuredAddress(
                    house_number="12",
                    street="Rue Saint Pierre",
                    postcode="40100",
                    city="Dax",
                    context="40, Landes, Nouvelle-Aquitaine",
                ),
                longitude=longitude,
                latitude=43.70884,
                municipality_code="40088",
                ban_id=None,
                result_type="housenumber",
                score=0.96,
                provider_name="Géoplateforme",
                provider_url="https://data.geopf.fr/geocodage/search",
            ),
            NOW,
        )
        repository.confirm_candidate(candidate.id, NOW)
    finally:
        engine.dispose()


@dataclass
class MutableClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


class SuccessfulExecutor:
    def collect(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> CollectionOutcome:
        assert reservation.collection_radius_meters == 50_000
        reporter.update(
            CollectionProgress("normalizing", processed=2, total=2, observations=2),
            {"page": 1},
        )
        return CollectionOutcome(
            "SUCCEEDED",
            {"processed": 2, "total": 2, "observations": 2},
            source_freshness={"test_dataset": "2026-09-20"},
        )


class PartialExecutor:
    def collect(
        self,
        _reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> CollectionOutcome:
        reporter.update(CollectionProgress("validating", processed=1, total=2, observations=1))
        return CollectionOutcome(
            "PARTIAL",
            {"processed": 1, "total": 2, "observations": 1},
            CollectionError("incomplete_pagination", "Une page manque.", transient=False),
        )


class RetryThenSuccessExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def collect(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> CollectionOutcome:
        self.calls += 1
        if self.calls == 1:
            reporter.update(CollectionProgress("downloading", processed=1, observations=1))
            raise RetryableCollectionError(
                "provider_unavailable",
                "La source est momentanément indisponible.",
                observations_preserved=1,
            )
        assert reservation.attempt_number == 2
        return CollectionOutcome("SUCCEEDED", {"processed": 2, "observations": 2})


class FailedExecutor:
    def collect(
        self,
        _reservation: ReservedCollection,
        _reporter: ProgressReporter,
    ) -> CollectionOutcome:
        raise PermanentCollectionError("invalid_contract", "Le contrat source est invalide.")


def test_fake_jobs_succeed_retry_fail_and_never_publish_partial_coverage(
    integration_database_url: str,
) -> None:
    confirm_position(integration_database_url, longitude=-1.05191)
    engine = create_engine(integration_database_url)
    repository = SqlAlchemyCollectionRepository(engine)
    clock = MutableClock(NOW + timedelta(minutes=1))
    try:
        first = repository.enqueue("SIRENE", "MANUAL", SPECIFICATION, NOW)
        duplicate = repository.enqueue("SIRENE", "MANUAL", SPECIFICATION, NOW)
        assert first.created is True
        assert duplicate.created is False
        assert duplicate.job.id == first.job.id

        success_worker = CollectionWorker(
            repository,
            {"SIRENE": SuccessfulExecutor()},
            "worker-success",
            clock=clock,
        )
        assert success_worker.run_once() is True
        sirene = repository.dashboard().connectors[0]
        assert sirene.latest_job is not None
        assert sirene.latest_job.id == first.job.id
        assert sirene.latest_job.state == "SUCCEEDED"
        assert sirene.coverage is not None
        assert sirene.coverage.search_circle_covered is True

        partial = repository.enqueue("DATATOURISME", "MANUAL", SPECIFICATION, clock.now)
        partial_worker = CollectionWorker(
            repository,
            {"DATATOURISME": PartialExecutor()},
            "worker-partial",
            clock=clock,
        )
        assert partial_worker.run_once() is True
        datatourisme = repository.dashboard().connectors[1]
        assert datatourisme.latest_job is not None
        assert datatourisme.latest_job.id == partial.job.id
        assert datatourisme.latest_job.state == "PARTIAL"
        assert datatourisme.coverage is None

        retry = repository.enqueue("SIRENE", "MANUAL", SPECIFICATION, clock.now)
        retry_executor = RetryThenSuccessExecutor()
        retry_worker = CollectionWorker(
            repository,
            {"SIRENE": retry_executor},
            "worker-retry",
            clock=clock,
        )
        assert retry_worker.run_once() is True
        retried_status = repository.dashboard().connectors[0]
        assert retried_status.active_job is not None
        assert retried_status.active_job.id == retry.job.id
        assert retried_status.active_job.state == "WAITING_RETRY"
        assert retried_status.active_job.available_at == clock.now + timedelta(minutes=30)

        clock.now += timedelta(minutes=31)
        assert retry_worker.run_once() is True
        retried_status = repository.dashboard().connectors[0]
        assert retried_status.latest_job is not None
        assert retried_status.latest_job.id == retry.job.id
        assert retried_status.latest_job.state == "SUCCEEDED"
        assert retried_status.latest_job.attempt_count == 2

        failed = repository.enqueue("DATATOURISME", "MANUAL", SPECIFICATION, clock.now)
        failed_worker = CollectionWorker(
            repository,
            {"DATATOURISME": FailedExecutor()},
            "worker-failed",
            clock=clock,
        )
        assert failed_worker.run_once() is True
        failed_status = repository.dashboard().connectors[1]
        assert failed_status.latest_job is not None
        assert failed_status.latest_job.id == failed.job.id
        assert failed_status.latest_job.state == "FAILED"
        assert failed_status.coverage is None

        rerun = repository.enqueue(
            "DATATOURISME",
            "MANUAL",
            SPECIFICATION,
            clock.now + timedelta(minutes=1),
        )
        assert rerun.created is True
        assert rerun.job.id != failed.job.id
        assert rerun.job.state == "WAITING"

        with engine.connect() as connection:
            coverage_results = connection.execute(
                text(
                    """
                    SELECT cycle.result
                    FROM connector_coverage AS coverage
                    JOIN collection_cycle AS cycle ON cycle.id = coverage.cycle_id
                    """
                )
            ).scalars()
            assert set(coverage_results) == {"SUCCEEDED"}
    finally:
        engine.dispose()


def test_expired_lease_is_visible_and_safely_reserved_again(
    integration_database_url: str,
) -> None:
    confirm_position(integration_database_url, longitude=-1.05231)
    engine = create_engine(integration_database_url)
    repository = SqlAlchemyCollectionRepository(engine)
    try:
        queued = repository.enqueue("SIRENE", "MANUAL", SPECIFICATION, NOW)
        first = repository.reserve_next(
            "worker-before-crash",
            ("SIRENE",),
            NOW,
            NOW + timedelta(minutes=5),
        )
        assert first is not None
        repository.heartbeat(
            first,
            "worker-before-crash",
            CollectionProgress("page", processed=1, observations=1),
            {"page": 1},
            NOW,
            NOW + timedelta(minutes=5),
        )

        recovered_at = NOW + timedelta(minutes=6)
        second = repository.reserve_next(
            "worker-after-crash",
            ("SIRENE",),
            recovered_at,
            recovered_at + timedelta(minutes=5),
        )
        assert second is not None
        assert second.job_id == queued.job.id
        assert second.attempt_number == 2
        assert second.last_safe_checkpoint == {"page": 1}
        repository.finish(
            second,
            "worker-after-crash",
            "PARTIAL",
            {"processed": 1, "observations": 1},
            CollectionError("stopped_for_test", "Test interrompu.", transient=False),
            {},
            {},
            recovered_at,
        )

        with engine.connect() as connection:
            attempts = connection.execute(
                text(
                    """
                    SELECT attempt_number, result
                    FROM collection_attempt
                    WHERE collection_job_id = :job_id
                    ORDER BY attempt_number
                    """
                ),
                {"job_id": queued.job.id},
            ).all()
        assert [tuple(attempt) for attempt in attempts] == [
            (1, "RETRYABLE_FAILURE"),
            (2, "PARTIAL"),
        ]
    finally:
        engine.dispose()
