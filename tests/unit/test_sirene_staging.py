"""Tests for deterministic Sirene candidate staging before geolocation."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from radar.collections.contracts import ReservedCollection
from radar.prospects.contracts import Activity, EstablishmentAddress, ProspectCandidate
from radar.prospects.planning import SireneMunicipalityBatch
from radar.prospects.staging import (
    SireneCandidatePageStager,
    SireneCandidateStagingError,
    StagedSireneCandidate,
    normalize_sirene_candidate,
)
from radar.providers.sirene import SirenePage

NOW = datetime(2026, 9, 21, 8, tzinfo=UTC)


def candidate(*, employee_band: str | None = "12") -> ProspectCandidate:
    return ProspectCandidate(
        siret="12345678901234",
        siren="123456789",
        is_head_office=False,
        establishment_names=("Atelier public",),
        legal_name="Société exemple",
        legal_usual_names=(),
        legal_category="5710",
        activity=Activity("10.71C", "NAFRev2"),
        employee_band=employee_band,
        employee_year=2024,
        address=EstablishmentAddress(
            address_identifier="ADDR-1",
            street_number="12",
            repetition_index=None,
            street_type="RUE",
            street_label="SAINT PIERRE",
            address_complement=None,
            postcode="40100",
            municipality_label="DAX",
            municipality_code="40088",
            coordinates=None,
        ),
        establishment_created_on="2020-01-02",
        current_period_started_on="2024-03-04",
        establishment_processed_at="2026-09-20T12:00:00",
        legal_unit_processed_at="2026-09-20T11:00:00",
    )


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[int, tuple[StagedSireneCandidate, ...], datetime]] = []

    def stage_page(
        self,
        _reservation: ReservedCollection,
        _batch: SireneMunicipalityBatch,
        page_number: int,
        candidates: tuple[StagedSireneCandidate, ...],
        now: datetime,
    ) -> None:
        self.calls.append((page_number, candidates, now))


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


def batch() -> SireneMunicipalityBatch:
    return SireneMunicipalityBatch(
        id=uuid4(),
        key="municipalities:0001:fixture",
        order_number=1,
        municipality_codes=("40088",),
        state="RUNNING",
    )


def test_normalization_is_stable_and_separates_identity_from_content() -> None:
    first = normalize_sirene_candidate(candidate(), 1)
    repeated = normalize_sirene_candidate(candidate(), 1)
    changed = normalize_sirene_candidate(candidate(employee_band="21"), 1)

    assert repeated == first
    assert changed.identifier_fingerprint == first.identifier_fingerprint
    assert changed.content_fingerprint != first.content_fingerprint
    assert first.payload["administrative_state"] == {
        "establishment": "ACTIVE",
        "legal_unit": "ACTIVE",
    }
    assert first.payload["diffusion_status"] == {
        "establishment": "FULL",
        "legal_unit": "FULL",
    }
    assert first.payload["address"] == {
        "address_identifier": "ADDR-1",
        "street_number": "12",
        "repetition_index": None,
        "street_type": "RUE",
        "street_label": "SAINT PIERRE",
        "address_complement": None,
        "postcode": "40100",
        "municipality_label": "DAX",
        "municipality_code": "40088",
        "coordinates": None,
    }


def test_page_stager_reconciles_counts_and_rejects_a_wrong_municipality() -> None:
    backend = RecordingBackend()
    stager = SireneCandidatePageStager(backend, clock=lambda: NOW)
    valid_page = SirenePage(
        number=1,
        announced_total=2,
        received_count=2,
        importable_candidates=(candidate(),),
        rejection_counts={"closed_establishment": 1},
        next_cursor_fingerprint="a" * 64,
        terminal=False,
    )
    stager.handle(reservation(), batch(), valid_page)

    assert len(backend.calls) == 1
    assert backend.calls[0][0] == 1
    assert backend.calls[0][1][0].item_rank == 1
    assert backend.calls[0][2] == NOW

    wrong_count = SirenePage(
        number=1,
        announced_total=2,
        received_count=2,
        importable_candidates=(candidate(),),
        rejection_counts={},
        next_cursor_fingerprint="b" * 64,
        terminal=False,
    )
    with pytest.raises(SireneCandidateStagingError, match="counts do not match"):
        stager.handle(reservation(), batch(), wrong_count)

    original = candidate()
    wrong_municipality_candidate = replace(
        original,
        address=replace(original.address, municipality_code="40192"),
    )
    wrong_municipality = SirenePage(
        number=1,
        announced_total=1,
        received_count=1,
        importable_candidates=(wrong_municipality_candidate,),
        rejection_counts={},
        next_cursor_fingerprint="c" * 64,
        terminal=False,
    )
    with pytest.raises(SireneCandidateStagingError, match="outside"):
        stager.handle(reservation(), batch(), wrong_municipality)
