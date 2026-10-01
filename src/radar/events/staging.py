"""Normalize DATAtourisme candidates for durable provenance staging."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from radar.collections.contracts import ReservedCollection
from radar.events.contracts import EventCandidate
from radar.events.preparation import EventTemporalState, prepare_event_periods
from radar.providers.datatourisme import DatatourismePage

DATATOURISME_DATA_SOURCE_CODE = "DATATOURISME_API"
DATATOURISME_IDENTITY_AUTHORITY = "DATATOURISME"
DATATOURISME_IDENTITY_NAMESPACE = "DATATOURISME_UUID"
DATATOURISME_CANDIDATE_SCHEMA_VERSION = "datatourisme-event-candidate-v1"
DATATOURISME_ADAPTER_VERSION = "datatourisme-v1-events-v1"


@dataclass(frozen=True)
class StagedEventCandidate:
    """Stable event revision plus collection-time temporal diagnostics."""

    item_rank: int
    external_identifier: str
    identifier_fingerprint: str
    content_fingerprint: str
    source_uri: str
    source_updated_at: datetime | None
    payload: dict[str, object]
    validated_periods: tuple[dict[str, object], ...]
    temporal_state: EventTemporalState | None
    period_rejection_counts: dict[str, int]


class EventCandidateStagingBackend(Protocol):
    """Persistence boundary for one fully validated DATAtourisme page."""

    def stage_page(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        page: DatatourismePage,
        candidates: tuple[StagedEventCandidate, ...],
        now: datetime,
    ) -> None: ...


class EventCandidateStagingError(RuntimeError):
    """A DATAtourisme page cannot be staged without losing evidence."""


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


def _candidate_payload(candidate: EventCandidate) -> dict[str, object]:
    return {
        "uuid": candidate.external_identifier,
        "uri": candidate.source_uri,
        "producer_identifier": candidate.producer_identifier,
        "title": candidate.title,
        "types": list(candidate.types),
        "descriptions": [
            {"short": description.short, "full": description.full}
            for description in candidate.descriptions
        ],
        "locations": [
            {
                "longitude": location.longitude,
                "latitude": location.latitude,
                "addresses": [
                    {
                        "streets": list(address.streets),
                        "postcode": address.postcode,
                        "municipality": address.municipality,
                        "municipality_code": address.municipality_code,
                    }
                    for address in location.addresses
                ],
            }
            for location in candidate.locations
        ],
        "periods": [
            {
                "start_date": period.start_date,
                "end_date": period.end_date,
                "start_time": period.start_time,
                "end_time": period.end_time,
            }
            for period in candidate.periods
        ],
        "contacts": [
            {
                "role": contact.role,
                "legal_name": contact.legal_name,
                "phones": list(contact.phones),
                "websites": list(contact.websites),
            }
            for contact in candidate.contacts
        ],
        "source_parties": [
            {
                "role": party.role,
                "identifier": party.identifier,
                "legal_name": party.legal_name,
                "phones": list(party.phones),
                "websites": list(party.websites),
            }
            for party in candidate.source_parties
        ],
        "source_updated_at": candidate.source_updated_at,
        "aggregator_updated_at": candidate.aggregator_updated_at,
        "source_obsolete": candidate.source_obsolete,
    }


def _fingerprint_json(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _source_instant(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def normalize_event_candidate(
    candidate: EventCandidate,
    item_rank: int,
    now: datetime,
) -> StagedEventCandidate:
    """Build a minimized revision and deterministic collection diagnostics."""

    if item_rank < 1:
        raise ValueError("a staged DATAtourisme candidate rank must be positive")
    try:
        external_identifier = str(UUID(candidate.external_identifier))
    except ValueError as error:
        raise ValueError("a DATAtourisme candidate UUID is invalid") from error
    prepared = prepare_event_periods(candidate, now)
    payload = _candidate_payload(candidate)
    validated_periods: tuple[dict[str, object], ...] = tuple(
        {
            "source_index": period.source_index,
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
            "start_time": period.start_time.isoformat() if period.start_time else None,
            "end_time": period.end_time.isoformat() if period.end_time else None,
            "precision": period.precision,
            "interpretation_timezone": period.interpretation_timezone,
        }
        for period in prepared.periods
    )
    return StagedEventCandidate(
        item_rank=item_rank,
        external_identifier=external_identifier,
        identifier_fingerprint=hashlib.sha256(external_identifier.encode("ascii")).hexdigest(),
        content_fingerprint=_fingerprint_json(payload),
        source_uri=candidate.source_uri,
        source_updated_at=_source_instant(candidate.source_updated_at),
        payload=payload,
        validated_periods=validated_periods,
        temporal_state=prepared.temporal_state,
        period_rejection_counts=dict(prepared.rejection_counts),
    )


class EventCandidatePageStager:
    """Validate page accounting and stage every reusable event revision."""

    def __init__(
        self,
        backend: EventCandidateStagingBackend,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._backend = backend
        self._clock = clock

    def handle(
        self,
        reservation: ReservedCollection,
        batch_id: UUID,
        page: DatatourismePage,
    ) -> None:
        """Normalize one provider page before its durable acknowledgement."""

        if reservation.connector != "DATATOURISME":
            raise ValueError("only a DATAtourisme collection can stage event candidates")
        rejection_count = sum(page.rejection_counts.values())
        if any(count < 0 for count in page.rejection_counts.values()):
            raise EventCandidateStagingError(
                "a DATAtourisme page contains a negative rejection count"
            )
        if len(page.importable_candidates) + rejection_count != page.received_count:
            raise EventCandidateStagingError(
                "DATAtourisme candidate and rejection counts do not match the received page"
            )

        now = self._clock()
        seen_identifiers: set[str] = set()
        staged: list[StagedEventCandidate] = []
        for rank, candidate in enumerate(page.importable_candidates, start=1):
            normalized = normalize_event_candidate(candidate, rank, now)
            if normalized.external_identifier in seen_identifiers:
                raise EventCandidateStagingError("a DATAtourisme page contains a duplicate UUID")
            seen_identifiers.add(normalized.external_identifier)
            staged.append(normalized)

        self._backend.stage_page(reservation, batch_id, page, tuple(staged), now)
