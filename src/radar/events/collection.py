"""Durable DATAtourisme enumeration before source event projection."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from radar.collections.contracts import (
    CollectionError,
    CollectionOutcome,
    CollectionProgress,
    PermanentCollectionError,
    ProgressReporter,
    ReservedCollection,
    RetryableCollectionError,
)
from radar.events.projection import EventProjectionError, EventProjectionSummary
from radar.events.staging import EventCandidateStagingError
from radar.providers.datatourisme import (
    DatatourismeAuthenticationError,
    DatatourismeCollectionSummary,
    DatatourismeContractError,
    DatatourismePage,
    DatatourismeRequestError,
    DatatourismeTemporaryError,
)


class EventExecutionError(RuntimeError):
    """Durable DATAtourisme page evidence is incomplete or inconsistent."""


@dataclass(frozen=True)
class EventRunState:
    """One logical source batch, complete or running in this attempt."""

    batch_id: UUID
    completed_summary: DatatourismeCollectionSummary | None = None


class EventExecutionBackend(Protocol):
    """Persist one restartable geographic enumeration and its page evidence."""

    def start_or_resume(self, reservation: ReservedCollection, now: datetime) -> EventRunState: ...

    def record_page(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        page: DatatourismePage,
        now: datetime,
    ) -> None: ...

    def complete(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        summary: DatatourismeCollectionSummary,
        now: datetime,
    ) -> None: ...

    def fail(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        *,
        code: str,
        transient: bool,
        now: datetime,
    ) -> None: ...


class EventReader(Protocol):
    """Read-only subset of the DATAtourisme provider adapter."""

    def collect_events(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        on_page: Callable[[DatatourismePage], None],
    ) -> DatatourismeCollectionSummary: ...


class EventPageStager(Protocol):
    """Normalize and stage one complete provider page before acknowledgement."""

    def handle(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        page: DatatourismePage,
    ) -> None: ...


class EventProjector(Protocol):
    """Project every current, staged event after complete enumeration."""

    def project(self, reservation: ReservedCollection) -> EventProjectionSummary: ...


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


class DatatourismeCollectionExecutor:
    """Compose a restart-from-page-one enumeration with bounded projection."""

    def __init__(
        self,
        backend: EventExecutionBackend,
        reader: EventReader,
        stager: EventPageStager,
        projector: EventProjector,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._backend = backend
        self._reader = reader
        self._stager = stager
        self._projector = projector
        self._clock = clock

    def collect(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> CollectionOutcome:
        """Publish success only after page totals and projection reconcile."""

        if reservation.connector != "DATATOURISME":
            raise ValueError("only a DATAtourisme collection can use this executor")
        try:
            state = self._backend.start_or_resume(reservation, self._clock())
        except EventExecutionError as error:
            raise PermanentCollectionError(
                "datatourisme_execution_failed",
                "La collecte DATAtourisme n'a pas pu être préparée.",
            ) from error

        summary = state.completed_summary
        preserved = reservation.observations_preserved
        if summary is None:
            processed = 0
            attempt_importable = 0
            reporter.update(CollectionProgress("datatourisme_enumeration", 0, None, preserved))

            def stage_page(page: DatatourismePage) -> None:
                nonlocal processed, preserved, attempt_importable
                self._stager.handle(reservation, state.batch_id, page)
                attempt_importable += len(page.importable_candidates)
                preserved = max(preserved, attempt_importable)
                self._backend.record_page(reservation, state.batch_id, page, self._clock())
                processed += page.received_count
                reporter.update(
                    CollectionProgress(
                        "datatourisme_enumeration",
                        processed,
                        page.announced_total,
                        preserved,
                    ),
                    {"completed_page": page.number},
                )

            try:
                summary = self._reader.collect_events(
                    reservation.latitude,
                    reservation.longitude,
                    reservation.collection_radius_meters,
                    stage_page,
                )
                self._backend.complete(reservation, state.batch_id, summary, self._clock())
            except DatatourismeTemporaryError as error:
                self._fail(reservation, state.batch_id, "datatourisme_temporary", True)
                raise RetryableCollectionError(
                    "datatourisme_temporary",
                    "DATAtourisme est momentanément indisponible.",
                    observations_preserved=preserved,
                ) from error
            except DatatourismeAuthenticationError as error:
                self._fail(reservation, state.batch_id, "datatourisme_authentication", False)
                raise PermanentCollectionError(
                    "datatourisme_authentication",
                    "La clé DATAtourisme a été refusée.",
                    observations_preserved=preserved,
                ) from error
            except (DatatourismeRequestError, DatatourismeContractError) as error:
                self._fail(reservation, state.batch_id, "datatourisme_contract", False)
                raise PermanentCollectionError(
                    "datatourisme_contract",
                    "La réponse DATAtourisme ne respecte pas le contrat attendu.",
                    observations_preserved=preserved,
                ) from error
            except (EventCandidateStagingError, EventExecutionError) as error:
                self._fail(reservation, state.batch_id, "datatourisme_persistence", False)
                raise PermanentCollectionError(
                    "datatourisme_persistence",
                    "Les pages DATAtourisme n'ont pas pu être réconciliées.",
                    observations_preserved=preserved,
                ) from error

        assert summary is not None
        preserved = max(preserved, summary.importable_count)
        reporter.update(
            CollectionProgress(
                "datatourisme_projection",
                0,
                summary.importable_count,
                preserved,
            ),
            {"completed_stage": "datatourisme_enumeration"},
        )
        try:
            projection = self._projector.project(reservation)
        except EventProjectionError as error:
            raise PermanentCollectionError(
                "datatourisme_projection",
                "Les événements DATAtourisme n'ont pas pu être projetés.",
                observations_preserved=preserved,
            ) from error
        has_conflicts = projection.identity_conflict_count > 0
        reporter.update(
            CollectionProgress(
                "datatourisme_partial" if has_conflicts else "datatourisme_complete",
                summary.received_count,
                summary.announced_total,
                preserved,
            ),
            {"completed_stage": "datatourisme_projection"},
        )
        return CollectionOutcome(
            "PARTIAL" if has_conflicts else "SUCCEEDED",
            {
                "processed": summary.received_count,
                "total": summary.announced_total,
                "observations": preserved,
                "unique_uuid_count": summary.unique_uuid_count,
                "importable_count": summary.importable_count,
                "page_count": summary.page_count,
                "rejection_counts": summary.rejection_counts,
                "event_created_count": projection.created_count,
                "event_updated_count": projection.updated_count,
                "event_unchanged_count": projection.unchanged_count,
                "event_rejected_count": projection.rejected_count,
                "identity_conflict_count": projection.identity_conflict_count,
                "outside_radius_count": projection.counted_only_count,
            },
            error=(
                CollectionError(
                    "datatourisme_identity_conflict",
                    "Des identifiants DATAtourisme contradictoires ont été mis en quarantaine.",
                    False,
                )
                if has_conflicts
                else None
            ),
            explicit_limits={"search_circle_complete": True} if not has_conflicts else {},
        )

    def _fail(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        code: str,
        transient: bool,
    ) -> None:
        try:
            self._backend.fail(
                reservation,
                batch_id,
                code=code,
                transient=transient,
                now=self._clock(),
            )
        except EventExecutionError as error:
            raise PermanentCollectionError(
                "datatourisme_failure_recording",
                "L'échec de la collecte DATAtourisme n'a pas pu être enregistré.",
            ) from error
