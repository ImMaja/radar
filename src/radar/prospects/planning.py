"""Durable Sirene municipality planning before any provider request."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from radar.collections.contracts import ReservedCollection
from radar.providers.sirene import partition_municipalities
from radar.reference_data.contracts import MunicipalityReferenceBackend, MunicipalitySelection

SIRENE_CONTRACT_VERSION = "sirene-3.11-establishments-v1"


@dataclass(frozen=True)
class SireneMunicipalityBatch:
    """One stable disjoint batch of municipality codes."""

    id: UUID
    key: str
    order_number: int
    municipality_codes: tuple[str, ...]
    state: str


@dataclass(frozen=True)
class SireneCollectionPlan:
    """Immutable municipality selection and batches attached to one cycle."""

    cycle_id: UUID
    source_run_id: UUID
    dataset_release_id: UUID
    resource_identifier: str
    margin_meters: int
    municipality_count: int
    batches: tuple[SireneMunicipalityBatch, ...]
    newly_created: bool


class SirenePlanRepository(Protocol):
    """Persistence boundary for idempotent Sirene cycle planning."""

    def get(self, cycle_id: UUID) -> SireneCollectionPlan | None: ...

    def create(
        self,
        reservation: ReservedCollection,
        selection: MunicipalitySelection,
        batches: tuple[tuple[str, ...], ...],
        contract_version: str,
        now: datetime,
    ) -> SireneCollectionPlan: ...


class SirenePlanningError(RuntimeError):
    """The Sirene cycle cannot be planned without losing completeness."""


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


class SireneCollectionPlanningService:
    """Freeze a conservative selection into stable disjoint batches once."""

    def __init__(
        self,
        municipality_reference: MunicipalityReferenceBackend,
        repository: SirenePlanRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._municipality_reference = municipality_reference
        self._repository = repository
        self._clock = clock

    def plan(self, reservation: ReservedCollection) -> SireneCollectionPlan:
        """Create once, then reuse the exact same release, communes and batches."""

        if reservation.connector != "SIRENE":
            raise SirenePlanningError("only a Sirene cycle can use Sirene planning")
        existing = self._repository.get(reservation.cycle_id)
        if existing is not None:
            return existing

        selection = self._municipality_reference.select_candidates(
            reservation.longitude,
            reservation.latitude,
            reservation.collection_radius_meters,
        )
        codes = tuple(municipality.code for municipality in selection.municipalities)
        if not codes:
            raise SirenePlanningError("the collection circle selected no municipality")
        batches = partition_municipalities(codes)
        return self._repository.create(
            reservation,
            selection,
            batches,
            SIRENE_CONTRACT_VERSION,
            self._clock(),
        )
