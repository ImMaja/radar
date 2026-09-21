"""Sirene batch enumeration with durable page and retry boundaries."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Protocol

from radar.collections.contracts import (
    CollectionProgress,
    PermanentCollectionError,
    ProgressReporter,
    ReservedCollection,
    RetryableCollectionError,
)
from radar.prospects.planning import (
    SireneCollectionPlan,
    SireneCollectionPlanningService,
    SireneMunicipalityBatch,
)
from radar.providers.sirene import (
    SireneAuthenticationError,
    SireneBatchSummary,
    SireneContractError,
    SirenePage,
    SireneRequestError,
    SireneServiceInformation,
    SireneTemporaryError,
)


@dataclass(frozen=True)
class SireneSourceState:
    """Persisted source-run state and immutable API query date."""

    status: str
    query_date: str


@dataclass(frozen=True)
class SireneEnumerationResult:
    """Reconciled counts after every municipality batch reached its terminal page."""

    announced_total: int
    received_count: int
    unique_siret_count: int
    importable_count: int
    page_count: int
    batch_count: int
    rejection_counts: dict[str, int]
    source_metadata: dict[str, object]


class SireneReader(Protocol):
    """Read-only subset of the isolated Sirene provider adapter."""

    def service_information(self) -> SireneServiceInformation: ...

    def collect_batch(
        self,
        municipality_codes: tuple[str, ...],
        at_date: str,
        on_page: Callable[[SirenePage], None],
    ) -> SireneBatchSummary: ...


class SireneCandidatePageHandler(Protocol):
    """Idempotent candidate staging invoked before page acknowledgement."""

    def handle(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        page: SirenePage,
    ) -> None: ...


class SireneExecutionRepository(Protocol):
    """Durable batch/page lifecycle required by Sirene enumeration."""

    def source_state(self, plan: SireneCollectionPlan) -> SireneSourceState: ...

    def start_source(
        self,
        reservation: ReservedCollection,
        plan: SireneCollectionPlan,
        information: SireneServiceInformation,
        now: datetime,
    ) -> SireneSourceState: ...

    def start_batch(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        now: datetime,
    ) -> bool: ...

    def record_page(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        page: SirenePage,
        now: datetime,
    ) -> None: ...

    def complete_batch(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        summary: SireneBatchSummary,
        now: datetime,
    ) -> None: ...

    def fail_batch(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        *,
        code: str,
        message: str,
        transient: bool,
        now: datetime,
    ) -> None: ...

    def finish_source(
        self,
        reservation: ReservedCollection,
        plan: SireneCollectionPlan,
        now: datetime,
    ) -> SireneEnumerationResult: ...

    def completed_result(self, plan: SireneCollectionPlan) -> SireneEnumerationResult: ...


class SireneExecutionError(RuntimeError):
    """Persisted Sirene batch state is missing or internally inconsistent."""


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


class SireneBatchEnumerator:
    """Enumerate all planned batches while persisting every safe boundary."""

    def __init__(
        self,
        planner: SireneCollectionPlanningService,
        repository: SireneExecutionRepository,
        reader: SireneReader,
        page_handler: SireneCandidatePageHandler,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._planner = planner
        self._repository = repository
        self._reader = reader
        self._page_handler = page_handler
        self._clock = clock

    def enumerate(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> SireneEnumerationResult:
        """Run or resume every non-complete batch from its initial cursor."""

        plan = self._planner.plan(reservation)
        source = self._repository.source_state(plan)
        if source.status == "SUCCEEDED":
            return self._repository.completed_result(plan)
        if source.status == "PLANNED":
            information = self._service_information()
            if information.service_state.upper() not in {"UP", "OK"}:
                raise RetryableCollectionError(
                    "sirene_service_unavailable",
                    "Le service Sirene n'est pas annoncé comme disponible.",
                )
            source = self._repository.start_source(
                reservation,
                plan,
                information,
                self._clock(),
            )
        if source.status != "RUNNING":
            raise PermanentCollectionError(
                "sirene_source_not_runnable",
                "L'exécution Sirene n'est pas dans un état reprenable.",
            )

        completed_batches = sum(batch.state == "SUCCEEDED" for batch in plan.batches)
        reporter.update(
            CollectionProgress(
                "sirene_enumeration",
                processed=completed_batches,
                total=len(plan.batches),
            ),
            {"completed_batches": completed_batches},
        )
        for batch in plan.batches:
            if batch.state == "SUCCEEDED":
                continue
            if not self._repository.start_batch(reservation, batch, self._clock()):
                continue
            try:
                summary = self._reader.collect_batch(
                    batch.municipality_codes,
                    source.query_date,
                    partial(self._handle_page, reservation, batch),
                )
                self._repository.complete_batch(reservation, batch, summary, self._clock())
            except RetryableCollectionError as error:
                self._fail(reservation, batch, error.error.code, True)
                raise
            except PermanentCollectionError as error:
                self._fail(reservation, batch, error.error.code, False)
                raise
            except SireneTemporaryError as error:
                self._fail(reservation, batch, "sirene_temporary_error", True)
                raise RetryableCollectionError(
                    "sirene_temporary_error",
                    "Sirene est momentanément indisponible.",
                ) from error
            except SireneAuthenticationError as error:
                self._fail(reservation, batch, "sirene_authentication_error", False)
                raise PermanentCollectionError(
                    "sirene_authentication_error",
                    "La clé configurée ne permet pas d'accéder à Sirene.",
                ) from error
            except (SireneRequestError, SireneContractError) as error:
                self._fail(reservation, batch, "sirene_contract_error", False)
                raise PermanentCollectionError(
                    "sirene_contract_error",
                    "La réponse Sirene ne respecte pas le contrat attendu.",
                ) from error
            except Exception as error:
                self._fail(reservation, batch, "sirene_page_processing_error", False)
                raise PermanentCollectionError(
                    "sirene_page_processing_error",
                    "Une page Sirene n'a pas pu être enregistrée correctement.",
                ) from error

            completed_batches += 1
            reporter.update(
                CollectionProgress(
                    "sirene_enumeration",
                    processed=completed_batches,
                    total=len(plan.batches),
                ),
                {
                    "completed_batches": completed_batches,
                    "last_batch_key": batch.key,
                },
            )

        return self._repository.finish_source(reservation, plan, self._clock())

    def _service_information(self) -> SireneServiceInformation:
        try:
            return self._reader.service_information()
        except SireneTemporaryError as error:
            raise RetryableCollectionError(
                "sirene_temporary_error",
                "Sirene est momentanément indisponible.",
            ) from error
        except SireneAuthenticationError as error:
            raise PermanentCollectionError(
                "sirene_authentication_error",
                "La clé configurée ne permet pas d'accéder à Sirene.",
            ) from error
        except (SireneRequestError, SireneContractError) as error:
            raise PermanentCollectionError(
                "sirene_contract_error",
                "La réponse Sirene ne respecte pas le contrat attendu.",
            ) from error

    def _handle_page(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        page: SirenePage,
    ) -> None:
        self._page_handler.handle(reservation, batch, page)
        self._repository.record_page(reservation, batch, page, self._clock())

    def _fail(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        code: str,
        transient: bool,
    ) -> None:
        self._repository.fail_batch(
            reservation,
            batch,
            code=code,
            message="Le lot Sirene a été interrompu.",
            transient=transient,
            now=self._clock(),
        )
