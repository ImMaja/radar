"""Deterministic selection of one effective position for each Sirene candidate."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from radar.collections.contracts import ReservedCollection

SIRENE_POSITION_RESOLUTION_RULE_VERSION = "sirene-position-selection-v1"


class SirenePositionResolutionError(RuntimeError):
    """Candidate positions cannot be reconciled without losing completeness."""


@dataclass(frozen=True)
class SirenePositionResolutionSummary:
    """Reconciled counts for one deterministic position-selection pass."""

    requested_count: int
    api_selected_count: int
    file_selected_count: int
    geocoder_selected_count: int
    geocoding_required_count: int
    unresolved_count: int
    divergent_count: int

    def validate(self) -> None:
        """Reject impossible counters before a pipeline can publish them."""

        counts = (
            self.requested_count,
            self.api_selected_count,
            self.file_selected_count,
            self.geocoder_selected_count,
            self.geocoding_required_count,
            self.unresolved_count,
            self.divergent_count,
        )
        if any(count < 0 for count in counts):
            raise SirenePositionResolutionError(
                "Sirene position-resolution counters cannot be negative"
            )
        classified_count = (
            self.api_selected_count
            + self.file_selected_count
            + self.geocoder_selected_count
            + self.geocoding_required_count
            + self.unresolved_count
        )
        if classified_count != self.requested_count:
            raise SirenePositionResolutionError(
                "Sirene position-resolution counters do not reconcile"
            )
        if self.divergent_count > self.requested_count:
            raise SirenePositionResolutionError(
                "Sirene position divergence count exceeds the candidate count"
            )


class SirenePositionResolutionBackend(Protocol):
    """Persistence boundary for deterministic candidate-position selection."""

    def resolve_positions(
        self,
        reservation: ReservedCollection,
        now: datetime,
    ) -> SirenePositionResolutionSummary: ...


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


class SirenePositionResolutionService:
    """Select API, then file, while leaving uncertain cases for geocoding."""

    def __init__(
        self,
        backend: SirenePositionResolutionBackend,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._backend = backend
        self._clock = clock

    def resolve(
        self,
        reservation: ReservedCollection,
    ) -> SirenePositionResolutionSummary:
        """Resolve the current successful API attempt after file reconciliation."""

        if reservation.connector != "SIRENE":
            raise ValueError("only a Sirene collection can resolve Sirene positions")
        summary = self._backend.resolve_positions(reservation, self._clock())
        summary.validate()
        return summary
