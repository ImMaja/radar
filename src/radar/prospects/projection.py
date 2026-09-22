"""Materialize resolved Sirene candidates as stable prospect opportunities."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from radar.collections.contracts import ReservedCollection


class SireneProspectProjectionError(RuntimeError):
    """Resolved candidates cannot be projected without losing an invariant."""


@dataclass(frozen=True)
class SireneProjectionPage:
    """One bounded provider page whose current occurrences still need a decision."""

    collection_batch_id: UUID
    page_number: int


@dataclass(frozen=True)
class SireneProspectProjectionSummary:
    """Cycle-level decisions after every current candidate has been projected."""

    requested_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    counted_only_count: int
    location_unknown_count: int

    def validate(self) -> None:
        """Reject counters that could hide an undecided or duplicated occurrence."""

        counts = (
            self.requested_count,
            self.created_count,
            self.updated_count,
            self.unchanged_count,
            self.counted_only_count,
            self.location_unknown_count,
        )
        if any(count < 0 for count in counts):
            raise SireneProspectProjectionError(
                "Sirene prospect-projection counters cannot be negative"
            )
        decided_count = (
            self.created_count + self.updated_count + self.unchanged_count + self.counted_only_count
        )
        if decided_count != self.requested_count:
            raise SireneProspectProjectionError(
                "Sirene prospect-projection counters do not reconcile"
            )
        retained_count = self.created_count + self.updated_count + self.unchanged_count
        if self.location_unknown_count > retained_count:
            raise SireneProspectProjectionError(
                "unknown locations exceed retained Sirene prospects"
            )


class SireneProspectProjectionBackend(Protocol):
    """Persistence boundary for bounded and restart-safe prospect projection."""

    def pending_pages(
        self,
        reservation: ReservedCollection,
    ) -> tuple[SireneProjectionPage, ...]: ...

    def project_page(
        self,
        reservation: ReservedCollection,
        page: SireneProjectionPage,
        now: datetime,
    ) -> None: ...

    def summary(
        self,
        reservation: ReservedCollection,
    ) -> SireneProspectProjectionSummary: ...


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


class SireneProspectProjectionService:
    """Project final candidates one provider page at a time."""

    def __init__(
        self,
        backend: SireneProspectProjectionBackend,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._backend = backend
        self._clock = clock

    def project(
        self,
        reservation: ReservedCollection,
    ) -> SireneProspectProjectionSummary:
        """Resume pending pages and reconcile all current candidate decisions."""

        if reservation.connector != "SIRENE":
            raise ValueError("only a Sirene collection can project Sirene prospects")
        for page in self._backend.pending_pages(reservation):
            self._backend.project_page(reservation, page, self._clock())
        summary = self._backend.summary(reservation)
        summary.validate()
        return summary
