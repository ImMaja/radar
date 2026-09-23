"""Reconcile already-known SIRET absent from a complete active selection."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from radar.collections.contracts import (
    CollectionProgress,
    PermanentCollectionError,
    ProgressReporter,
    ReservedCollection,
    RetryableCollectionError,
)
from radar.providers.sirene import (
    MAX_STATUS_SIRETS_PER_BATCH,
    SireneAuthenticationError,
    SireneContractError,
    SireneRequestError,
    SireneStatusLookup,
    SireneTemporaryError,
)


class SireneKnownStatusError(RuntimeError):
    """Known-establishment state cannot be reconciled without losing evidence."""


@dataclass(frozen=True)
class SireneKnownStatusPlan:
    """Frozen query date and currently pending known SIRET."""

    query_date: str
    total_count: int
    completed_count: int
    pending_sirets: tuple[str, ...]


@dataclass(frozen=True)
class SireneKnownStatusSummary:
    """Final outcomes for all known SIRET absent from the active selection."""

    checked_count: int
    active_count: int
    closed_count: int
    ceased_count: int
    not_found_count: int

    def validate(self) -> None:
        """Ensure every targeted SIRET has one explicit outcome."""

        counts = (
            self.checked_count,
            self.active_count,
            self.closed_count,
            self.ceased_count,
            self.not_found_count,
        )
        if any(count < 0 for count in counts):
            raise SireneKnownStatusError("Sirene known-status counters cannot be negative")
        if sum(counts[1:]) != self.checked_count:
            raise SireneKnownStatusError("Sirene known-status counters do not reconcile")


class SireneKnownStatusReader(Protocol):
    """Read current public states for a bounded exact SIRET list."""

    def lookup_establishment_statuses(
        self,
        sirets: Sequence[str],
        at_date: str,
    ) -> SireneStatusLookup: ...


class SireneKnownStatusBackend(Protocol):
    """Persist restart-safe checks and explicit state transitions."""

    def prepare(
        self,
        reservation: ReservedCollection,
        now: datetime,
    ) -> SireneKnownStatusPlan: ...

    def record(
        self,
        reservation: ReservedCollection,
        lookup: SireneStatusLookup,
        now: datetime,
    ) -> None: ...

    def record_failure(
        self,
        reservation: ReservedCollection,
        code: str,
        *,
        transient: bool,
        now: datetime,
    ) -> None: ...

    def finish(
        self,
        reservation: ReservedCollection,
        now: datetime,
    ) -> SireneKnownStatusSummary: ...


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


def _chunks(values: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        values[index : index + MAX_STATUS_SIRETS_PER_BATCH]
        for index in range(0, len(values), MAX_STATUS_SIRETS_PER_BATCH)
    )


class SireneKnownStatusReconciliationService:
    """Check absent known SIRET only after the active enumeration is complete."""

    def __init__(
        self,
        backend: SireneKnownStatusBackend,
        reader: SireneKnownStatusReader,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._backend = backend
        self._reader = reader
        self._clock = clock

    def reconcile(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> SireneKnownStatusSummary:
        """Resume targeted checks and apply only explicit full-diffusion states."""

        if reservation.connector != "SIRENE":
            raise ValueError("only a Sirene collection can reconcile known SIRET")
        plan = self._backend.prepare(reservation, self._clock())
        completed = plan.completed_count
        reporter.update(
            CollectionProgress(
                "sirene_known_status",
                processed=completed,
                total=plan.total_count,
            ),
            {"checked_known_sirets": completed},
        )
        for sirets in _chunks(plan.pending_sirets):
            try:
                lookup = self._reader.lookup_establishment_statuses(sirets, plan.query_date)
            except SireneTemporaryError as error:
                self._backend.record_failure(
                    reservation,
                    "sirene_known_status_temporary_error",
                    transient=True,
                    now=self._clock(),
                )
                raise RetryableCollectionError(
                    "sirene_known_status_temporary_error",
                    "Sirene est momentanément indisponible pendant le contrôle des fiches connues.",
                    observations_preserved=completed,
                ) from error
            except SireneAuthenticationError as error:
                self._fail_permanently(
                    reservation,
                    "sirene_known_status_authentication_error",
                )
                raise PermanentCollectionError(
                    "sirene_known_status_authentication_error",
                    "La clé configurée ne permet pas le contrôle des fiches Sirene connues.",
                    observations_preserved=completed,
                ) from error
            except (SireneRequestError, SireneContractError) as error:
                self._fail_permanently(reservation, "sirene_known_status_contract_error")
                raise PermanentCollectionError(
                    "sirene_known_status_contract_error",
                    "La réponse Sirene ciblée ne respecte pas le contrat attendu.",
                    observations_preserved=completed,
                ) from error

            if any(status.has_partial_diffusion for status in lookup.statuses):
                self._fail_permanently(
                    reservation,
                    "sirene_partial_diffusion_policy_required",
                )
                raise PermanentCollectionError(
                    "sirene_partial_diffusion_policy_required",
                    "Une diffusion partielle exige la politique de purge validée avant publication.",
                    observations_preserved=completed,
                )
            self._backend.record(reservation, lookup, self._clock())
            completed += len(lookup.requested_sirets)
            reporter.update(
                CollectionProgress(
                    "sirene_known_status",
                    processed=completed,
                    total=plan.total_count,
                ),
                {"checked_known_sirets": completed},
            )

        summary = self._backend.finish(reservation, self._clock())
        summary.validate()
        return summary

    def _fail_permanently(self, reservation: ReservedCollection, code: str) -> None:
        self._backend.record_failure(
            reservation,
            code,
            transient=False,
            now=self._clock(),
        )
