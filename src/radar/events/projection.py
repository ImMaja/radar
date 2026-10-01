"""Project staged DATAtourisme observations into stable event opportunities."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from radar.collections.contracts import ReservedCollection


class EventProjectionError(RuntimeError):
    """A staged event cannot be projected without breaking its invariants."""


@dataclass(frozen=True)
class EventProjectionPage:
    """One provider page containing undecided candidates in the current attempt."""

    collection_batch_id: UUID
    page_number: int


@dataclass(frozen=True)
class EventProjectionSummary:
    """Reconciled decisions for every staged candidate in a collection cycle."""

    requested_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    rejected_count: int
    counted_only_count: int
    identity_conflict_count: int = 0

    def validate(self) -> None:
        """Ensure that no staged candidate disappeared from the projection."""

        counts = (
            self.requested_count,
            self.created_count,
            self.updated_count,
            self.unchanged_count,
            self.rejected_count,
            self.counted_only_count,
            self.identity_conflict_count,
        )
        if any(count < 0 for count in counts) or sum(counts[1:]) != self.requested_count:
            raise EventProjectionError("DATAtourisme event decisions do not reconcile")


class EventProjectionBackend(Protocol):
    """Persistence boundary for bounded, restart-safe event projection."""

    def pending_pages(self, reservation: ReservedCollection) -> tuple[EventProjectionPage, ...]: ...

    def project_page(
        self, reservation: ReservedCollection, page: EventProjectionPage, now: datetime
    ) -> None: ...

    def summary(self, reservation: ReservedCollection) -> EventProjectionSummary: ...


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


class EventProjectionService:
    """Resume pending DATAtourisme pages and reconcile their outcomes."""

    def __init__(
        self,
        backend: EventProjectionBackend,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._backend = backend
        self._clock = clock

    def project(self, reservation: ReservedCollection) -> EventProjectionSummary:
        """Project all pending pages from one active collection attempt."""

        if reservation.connector != "DATATOURISME":
            raise ValueError("only a DATAtourisme collection can project events")
        for page in self._backend.pending_pages(reservation):
            self._backend.project_page(reservation, page, self._clock())
        summary = self._backend.summary(reservation)
        summary.validate()
        return summary
