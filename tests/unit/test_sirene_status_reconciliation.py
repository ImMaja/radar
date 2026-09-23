"""Tests for targeted reconciliation of already-known Sirene establishments."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from radar.collections.contracts import (
    CollectionProgress,
    PermanentCollectionError,
    ReservedCollection,
    RetryableCollectionError,
)
from radar.prospects.status_reconciliation import (
    SireneKnownStatusPlan,
    SireneKnownStatusReconciliationService,
    SireneKnownStatusSummary,
)
from radar.providers.sirene import (
    SireneEstablishmentStatus,
    SireneStatusLookup,
    SireneTemporaryError,
)

NOW = datetime(2026, 9, 23, 12, tzinfo=UTC)


def reservation() -> ReservedCollection:
    return ReservedCollection(
        job_id=uuid4(),
        cycle_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        max_attempts=3,
        connector="SIRENE",
        longitude=-1.051952,
        latitude=43.70884,
        collection_radius_meters=50_000,
        last_safe_checkpoint=None,
    )


def status(siret: str, *, partial: bool = False) -> SireneEstablishmentStatus:
    return SireneEstablishmentStatus(
        siret=siret,
        siren=siret[:9],
        establishment_administrative_state="ACTIVE",
        legal_unit_administrative_state="ACTIVE",
        establishment_diffusion_status="PARTIAL" if partial else "FULL",
        legal_unit_diffusion_status="FULL",
    )


class FixtureBackend:
    def __init__(self, plan: SireneKnownStatusPlan) -> None:
        self.plan = plan
        self.lookups: list[SireneStatusLookup] = []
        self.failures: list[tuple[str, bool]] = []
        self.finish_calls = 0

    def prepare(
        self,
        _reservation: ReservedCollection,
        _now: datetime,
    ) -> SireneKnownStatusPlan:
        return self.plan

    def record(
        self,
        _reservation: ReservedCollection,
        lookup: SireneStatusLookup,
        _now: datetime,
    ) -> None:
        self.lookups.append(lookup)

    def record_failure(
        self,
        _reservation: ReservedCollection,
        code: str,
        *,
        transient: bool,
        now: datetime,
    ) -> None:
        del now
        self.failures.append((code, transient))

    def finish(
        self,
        _reservation: ReservedCollection,
        _now: datetime,
    ) -> SireneKnownStatusSummary:
        self.finish_calls += 1
        checked = self.plan.completed_count + sum(
            len(lookup.requested_sirets) for lookup in self.lookups
        )
        return SireneKnownStatusSummary(checked, checked, 0, 0, 0)


class FixtureReader:
    def __init__(self, *, partial: bool = False, temporary_failure: bool = False) -> None:
        self.partial = partial
        self.temporary_failure = temporary_failure
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def lookup_establishment_statuses(
        self,
        sirets: Sequence[str],
        at_date: str,
    ) -> SireneStatusLookup:
        requested = tuple(sirets)
        self.calls.append((requested, at_date))
        if self.temporary_failure:
            raise SireneTemporaryError("fixture unavailable")
        statuses = tuple(
            status(siret, partial=self.partial and index == 0)
            for index, siret in enumerate(requested)
        )
        return SireneStatusLookup(requested, statuses, ())


class FixtureReporter:
    def __init__(self) -> None:
        self.updates: list[tuple[CollectionProgress, dict[str, object] | None]] = []

    def update(
        self,
        progress: CollectionProgress,
        checkpoint: Mapping[str, object] | None = None,
    ) -> None:
        self.updates.append((progress, dict(checkpoint) if checkpoint is not None else None))


def test_reconciles_in_bounded_batches_and_reports_durable_progress() -> None:
    sirets = tuple(f"{index:014d}" for index in range(1, 1002))
    backend = FixtureBackend(SireneKnownStatusPlan("2026-09-23", 1003, 2, sirets))
    reader = FixtureReader()
    reporter = FixtureReporter()
    service = SireneKnownStatusReconciliationService(backend, reader, clock=lambda: NOW)

    summary = service.reconcile(reservation(), reporter)

    assert [len(call[0]) for call in reader.calls] == [1000, 1]
    assert all(call[1] == "2026-09-23" for call in reader.calls)
    assert len(backend.lookups) == 2
    assert summary.checked_count == 1003
    assert [update[0].processed for update in reporter.updates] == [2, 1002, 1003]
    assert backend.finish_calls == 1


def test_partial_diffusion_fails_closed_before_persisting_the_target() -> None:
    siret = "12345678901234"
    backend = FixtureBackend(SireneKnownStatusPlan("2026-09-23", 1, 0, (siret,)))
    service = SireneKnownStatusReconciliationService(
        backend,
        FixtureReader(partial=True),
        clock=lambda: NOW,
    )

    with pytest.raises(PermanentCollectionError) as captured:
        service.reconcile(reservation(), FixtureReporter())

    assert captured.value.error.code == "sirene_partial_diffusion_policy_required"
    assert backend.lookups == []
    assert backend.failures == [("sirene_partial_diffusion_policy_required", False)]
    assert backend.finish_calls == 0


def test_temporary_provider_failure_remains_retryable() -> None:
    siret = "12345678901234"
    backend = FixtureBackend(SireneKnownStatusPlan("2026-09-23", 1, 0, (siret,)))
    service = SireneKnownStatusReconciliationService(
        backend,
        FixtureReader(temporary_failure=True),
        clock=lambda: NOW,
    )

    with pytest.raises(RetryableCollectionError) as captured:
        service.reconcile(reservation(), FixtureReporter())

    assert captured.value.error.code == "sirene_known_status_temporary_error"
    assert backend.failures == [("sirene_known_status_temporary_error", True)]


def test_rejects_another_connector() -> None:
    backend = FixtureBackend(SireneKnownStatusPlan("2026-09-23", 0, 0, ()))
    service = SireneKnownStatusReconciliationService(backend, FixtureReader())

    with pytest.raises(ValueError, match="only a Sirene collection"):
        service.reconcile(
            replace(reservation(), connector="DATATOURISME"),
            FixtureReporter(),
        )
