"""Single-concurrency worker orchestration with persisted retries and leases."""

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from radar.collections.contracts import (
    CollectionError,
    CollectionExecutor,
    CollectionFinalResult,
    CollectionOutcome,
    CollectionProgress,
    CollectionRepository,
    Connector,
    PermanentCollectionError,
    ReservedCollection,
    RetryableCollectionError,
)

logger = logging.getLogger(__name__)
RETRY_DELAYS = (timedelta(minutes=30), timedelta(hours=4))


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


class _Reporter:
    def __init__(
        self,
        repository: CollectionRepository,
        reservation: ReservedCollection,
        worker_id: str,
        clock: Callable[[], datetime],
        lease_duration: timedelta,
    ) -> None:
        self._repository = repository
        self._reservation = reservation
        self._worker_id = worker_id
        self._clock = clock
        self._lease_duration = lease_duration

    def update(
        self,
        progress: CollectionProgress,
        checkpoint: Mapping[str, object] | None = None,
    ) -> None:
        """Persist progress and renew the lease at one safe adapter boundary."""

        now = self._clock()
        checkpoint_copy = dict(checkpoint) if checkpoint is not None else None
        self._repository.heartbeat(
            self._reservation,
            self._worker_id,
            progress,
            checkpoint_copy,
            now,
            now + self._lease_duration,
        )


class CollectionWorker:
    """Reserve at most one job and execute its provider adapter synchronously."""

    def __init__(
        self,
        repository: CollectionRepository,
        executors: Mapping[Connector, CollectionExecutor],
        worker_id: str,
        *,
        clock: Callable[[], datetime] = utc_now,
        lease_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        self._repository = repository
        self._executors = dict(executors)
        self._worker_id = worker_id
        self._clock = clock
        self._lease_duration = lease_duration

    def run_once(self) -> bool:
        """Execute one available supported job, returning whether one was reserved."""

        if not self._executors:
            return False
        now = self._clock()
        reservation = self._repository.reserve_next(
            self._worker_id,
            tuple(self._executors),
            now,
            now + self._lease_duration,
        )
        if reservation is None:
            return False

        reporter = _Reporter(
            self._repository,
            reservation,
            self._worker_id,
            self._clock,
            self._lease_duration,
        )
        try:
            outcome = self._executors[reservation.connector].collect(reservation, reporter)
        except RetryableCollectionError as error:
            self._handle_retryable(reservation, error)
        except PermanentCollectionError as error:
            self._finish_failure(
                reservation,
                error.error,
                error.observations_preserved,
            )
        except Exception as error:
            logger.error(
                "unexpected_collection_worker_error",
                extra={
                    "job_id": str(reservation.job_id),
                    "connector": reservation.connector,
                    "exception_type": type(error).__name__,
                },
            )
            self._finish_failure(
                reservation,
                CollectionError(
                    "unexpected_worker_error",
                    "Une erreur interne a interrompu la collecte.",
                    transient=False,
                ),
                0,
            )
        else:
            self._finish_outcome(reservation, outcome)
        return True

    def _handle_retryable(
        self,
        reservation: ReservedCollection,
        failure: RetryableCollectionError,
    ) -> None:
        now = self._clock()
        if reservation.attempt_number < reservation.max_attempts:
            delay_index = min(reservation.attempt_number - 1, len(RETRY_DELAYS) - 1)
            self._repository.defer_retry(
                reservation,
                self._worker_id,
                failure.error,
                now + RETRY_DELAYS[delay_index],
                now,
            )
            return
        self._finish_failure(
            reservation,
            failure.error,
            failure.observations_preserved,
            now=now,
        )

    def _finish_failure(
        self,
        reservation: ReservedCollection,
        error: CollectionError,
        observations_preserved: int,
        *,
        now: datetime | None = None,
    ) -> None:
        result: CollectionFinalResult = "PARTIAL" if observations_preserved > 0 else "FAILED"
        self._repository.finish(
            reservation,
            self._worker_id,
            result,
            {"observations": observations_preserved},
            error,
            {},
            {},
            now or self._clock(),
        )

    def _finish_outcome(
        self,
        reservation: ReservedCollection,
        outcome: CollectionOutcome,
    ) -> None:
        self._repository.finish(
            reservation,
            self._worker_id,
            outcome.result,
            outcome.counters,
            outcome.error,
            outcome.source_freshness,
            outcome.explicit_limits,
            self._clock(),
        )
