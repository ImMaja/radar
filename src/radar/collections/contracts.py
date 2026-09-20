"""Typed collection values and boundaries independent from HTTP and SQLAlchemy."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

Connector = Literal["SIRENE", "DATATOURISME"]
CollectionTrigger = Literal["MANUAL", "SCHEDULED"]
CollectionJobState = Literal[
    "WAITING",
    "RUNNING",
    "WAITING_RETRY",
    "SUCCEEDED",
    "PARTIAL",
    "FAILED",
]
CollectionFinalResult = Literal["SUCCEEDED", "PARTIAL", "FAILED"]
JsonObject = dict[str, object]


@dataclass(frozen=True)
class CollectionError:
    """Non-sensitive failure safe to persist and display."""

    code: str
    message: str
    transient: bool

    def as_dict(self) -> JsonObject:
        return {"code": self.code, "message": self.message, "transient": self.transient}


@dataclass(frozen=True)
class CollectionProgress:
    """Small public progress snapshot updated at safe processing boundaries."""

    stage: str
    processed: int = 0
    total: int | None = None
    observations: int = 0

    def as_dict(self) -> JsonObject:
        values: JsonObject = {
            "stage": self.stage,
            "processed": self.processed,
            "observations": self.observations,
        }
        if self.total is not None:
            values["total"] = self.total
        return values


@dataclass(frozen=True)
class CollectionJob:
    """Public state of one durable collection job and its immutable zone."""

    id: UUID
    cycle_id: UUID
    connector: Connector
    trigger: CollectionTrigger
    state: CollectionJobState
    reference_label: str
    longitude: float
    latitude: float
    collection_radius_meters: int
    created_at: datetime
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    attempt_count: int
    max_attempts: int
    progress: CollectionProgress
    last_error: CollectionError | None


@dataclass(frozen=True)
class ConnectorCoverage:
    """Latest fully proven geographic coverage for one connector."""

    established_at: datetime
    longitude: float
    latitude: float
    collection_radius_meters: int
    search_circle_covered: bool


@dataclass(frozen=True)
class ConnectorCollectionStatus:
    """Latest observable collection state for one configured connector."""

    connector: Connector
    available: bool
    active_job: CollectionJob | None
    latest_job: CollectionJob | None
    last_success_at: datetime | None
    coverage: ConnectorCoverage | None


@dataclass(frozen=True)
class CollectionDashboard:
    """Collection supervision state shown by the private interface."""

    connectors: tuple[ConnectorCollectionStatus, ...]


@dataclass(frozen=True)
class EnqueuedCollection:
    """Result of idempotently requesting a collection."""

    job: CollectionJob
    created: bool


@dataclass(frozen=True)
class ConnectorSpecification:
    """Non-secret adapter identity captured in every new cycle."""

    adapter_version: str
    configuration_fingerprint: str


@dataclass(frozen=True)
class ReservedCollection:
    """One leased execution attempt and its immutable request snapshot."""

    job_id: UUID
    cycle_id: UUID
    attempt_id: UUID
    attempt_number: int
    max_attempts: int
    connector: Connector
    longitude: float
    latitude: float
    collection_radius_meters: int
    last_safe_checkpoint: JsonObject | None


@dataclass(frozen=True)
class CollectionOutcome:
    """Successful or useful partial outcome returned by a connector adapter."""

    result: Literal["SUCCEEDED", "PARTIAL"]
    counters: JsonObject = field(default_factory=dict)
    error: CollectionError | None = None
    source_freshness: JsonObject = field(default_factory=dict)
    explicit_limits: JsonObject = field(default_factory=dict)


class CollectionRepository(Protocol):
    """Persistence operations required by web use cases and the worker."""

    def enqueue(
        self,
        connector: Connector,
        trigger: CollectionTrigger,
        specification: ConnectorSpecification,
        now: datetime,
        scheduled_for: datetime | None = None,
    ) -> EnqueuedCollection: ...

    def dashboard(self) -> CollectionDashboard: ...

    def reserve_next(
        self,
        worker_id: str,
        connectors: tuple[Connector, ...],
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReservedCollection | None: ...

    def heartbeat(
        self,
        reservation: ReservedCollection,
        worker_id: str,
        progress: CollectionProgress,
        checkpoint: JsonObject | None,
        now: datetime,
        lease_expires_at: datetime,
    ) -> None: ...

    def defer_retry(
        self,
        reservation: ReservedCollection,
        worker_id: str,
        error: CollectionError,
        available_at: datetime,
        now: datetime,
    ) -> None: ...

    def finish(
        self,
        reservation: ReservedCollection,
        worker_id: str,
        result: CollectionFinalResult,
        counters: JsonObject,
        error: CollectionError | None,
        source_freshness: JsonObject,
        explicit_limits: JsonObject,
        now: datetime,
    ) -> None: ...


class CollectionBackend(Protocol):
    """Web-facing collection use cases."""

    def request_manual(self, connector: Connector) -> EnqueuedCollection: ...

    def dashboard(self) -> CollectionDashboard: ...


class ProgressReporter(Protocol):
    """Worker callback used by adapters at bounded, restart-safe points."""

    def update(
        self,
        progress: CollectionProgress,
        checkpoint: Mapping[str, object] | None = None,
    ) -> None: ...


class CollectionExecutor(Protocol):
    """Provider adapter operation executed outside the HTTP process."""

    def collect(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> CollectionOutcome: ...


class ReferencePositionRequiredError(RuntimeError):
    """Raised when a collection is requested without a confirmed center."""


class CollectionLeaseLostError(RuntimeError):
    """Raised when a worker no longer owns the job it is trying to mutate."""


class CollectionEngineUnavailableError(RuntimeError):
    """Raised only in isolated compositions that have no database backend."""


class ConnectorNotAvailableError(RuntimeError):
    """Raised while a provider adapter has not yet been registered in the worker."""


class RetryableCollectionError(RuntimeError):
    """A temporary adapter failure eligible for a persisted delayed retry."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        observations_preserved: int = 0,
    ) -> None:
        self.error = CollectionError(code, message, transient=True)
        self.observations_preserved = observations_preserved
        super().__init__(message)


class PermanentCollectionError(RuntimeError):
    """A non-retryable adapter failure with a safe public explanation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        observations_preserved: int = 0,
    ) -> None:
        self.error = CollectionError(code, message, transient=False)
        self.observations_preserved = observations_preserved
        super().__init__(message)
