"""Normalize and stage reusable Sirene candidates before geographic resolution."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from radar.collections.contracts import ReservedCollection
from radar.prospects.contracts import ProspectCandidate
from radar.prospects.planning import SireneMunicipalityBatch
from radar.providers.sirene import SirenePage

SIRENE_DATA_SOURCE_CODE = "SIRENE_API"
SIRENE_IDENTITY_AUTHORITY = "INSEE"
SIRENE_IDENTITY_NAMESPACE = "SIRET"
SIRENE_CANDIDATE_SCHEMA_VERSION = "sirene-candidate-v1"
SIRENE_ADAPTER_VERSION = "sirene-3.11-establishments-v1"


@dataclass(frozen=True)
class StagedSireneCandidate:
    """Deterministic normalized proof awaiting exact geographic classification."""

    item_rank: int
    siret: str
    identifier_fingerprint: str
    content_fingerprint: str
    payload: dict[str, object]
    municipality_code: str
    lambert_x: float | None
    lambert_y: float | None
    coordinate_crs: str | None


class SireneCandidateStagingBackend(Protocol):
    """Persistence boundary for one fully validated candidate page."""

    def stage_page(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        page_number: int,
        candidates: tuple[StagedSireneCandidate, ...],
        now: datetime,
    ) -> None: ...


class SireneCandidateStagingError(RuntimeError):
    """A page cannot be staged without losing identity or provenance."""


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


def _candidate_payload(candidate: ProspectCandidate) -> dict[str, object]:
    coordinates = candidate.address.coordinates
    activity = candidate.activity
    return {
        "siret": candidate.siret,
        "siren": candidate.siren,
        "is_head_office": candidate.is_head_office,
        "establishment_names": list(candidate.establishment_names),
        "legal_name": candidate.legal_name,
        "legal_usual_names": list(candidate.legal_usual_names),
        "legal_category": candidate.legal_category,
        "activity": (
            {"code": activity.code, "nomenclature": activity.nomenclature}
            if activity is not None
            else None
        ),
        "employee_band": candidate.employee_band,
        "employee_year": candidate.employee_year,
        "address": {
            "address_identifier": candidate.address.address_identifier,
            "street_number": candidate.address.street_number,
            "repetition_index": candidate.address.repetition_index,
            "street_type": candidate.address.street_type,
            "street_label": candidate.address.street_label,
            "address_complement": candidate.address.address_complement,
            "postcode": candidate.address.postcode,
            "municipality_label": candidate.address.municipality_label,
            "municipality_code": candidate.address.municipality_code,
            "coordinates": (
                {"x": coordinates.x, "y": coordinates.y, "crs": coordinates.crs}
                if coordinates is not None
                else None
            ),
        },
        "administrative_state": {
            "establishment": "ACTIVE",
            "legal_unit": "ACTIVE",
        },
        "diffusion_status": {
            "establishment": "FULL",
            "legal_unit": "FULL",
        },
        "establishment_created_on": candidate.establishment_created_on,
        "current_period_started_on": candidate.current_period_started_on,
        "establishment_processed_at": candidate.establishment_processed_at,
        "legal_unit_processed_at": candidate.legal_unit_processed_at,
    }


def _fingerprint_json(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def normalize_sirene_candidate(
    candidate: ProspectCandidate,
    item_rank: int,
) -> StagedSireneCandidate:
    """Build the minimized stable payload and its ordinary technical fingerprints."""

    if item_rank < 1:
        raise ValueError("a staged Sirene candidate rank must be positive")
    payload = _candidate_payload(candidate)
    coordinates = candidate.address.coordinates
    return StagedSireneCandidate(
        item_rank=item_rank,
        siret=candidate.siret,
        identifier_fingerprint=hashlib.sha256(candidate.siret.encode("ascii")).hexdigest(),
        content_fingerprint=_fingerprint_json(payload),
        payload=payload,
        municipality_code=candidate.address.municipality_code,
        lambert_x=coordinates.x if coordinates is not None else None,
        lambert_y=coordinates.y if coordinates is not None else None,
        coordinate_crs=coordinates.crs if coordinates is not None else None,
    )


class SireneCandidatePageStager:
    """Validate page accounting then persist only reusable public candidates."""

    def __init__(
        self,
        backend: SireneCandidateStagingBackend,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._backend = backend
        self._clock = clock

    def handle(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        page: SirenePage,
    ) -> None:
        rejection_count = sum(page.rejection_counts.values())
        if any(count < 0 for count in page.rejection_counts.values()):
            raise SireneCandidateStagingError("a Sirene rejection count is negative")
        if len(page.importable_candidates) + rejection_count != page.received_count:
            raise SireneCandidateStagingError(
                "Sirene candidate and rejection counts do not match the received page"
            )
        if page.terminal and page.importable_candidates:
            raise SireneCandidateStagingError("a terminal Sirene page contains candidates")

        seen_sirets: set[str] = set()
        staged: list[StagedSireneCandidate] = []
        requested_codes = frozenset(batch.municipality_codes)
        for rank, candidate in enumerate(page.importable_candidates, start=1):
            if candidate.siret in seen_sirets:
                raise SireneCandidateStagingError("a Sirene page contains duplicate SIRET")
            if candidate.address.municipality_code not in requested_codes:
                raise SireneCandidateStagingError(
                    "a Sirene candidate is outside the persisted municipality batch"
                )
            seen_sirets.add(candidate.siret)
            staged.append(normalize_sirene_candidate(candidate, rank))

        self._backend.stage_page(
            reservation,
            batch,
            page.number,
            tuple(staged),
            self._clock(),
        )
