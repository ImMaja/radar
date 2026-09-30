"""Durable Géoplateforme fallback for unresolved Sirene candidate addresses."""

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from radar.collections.contracts import ReservedCollection
from radar.geography.contracts import (
    AddressNotFoundError,
    AddressOutsideMetropolitanFranceError,
    GeocodedAddress,
    Geocoder,
    GeocodingContractError,
    GeocodingFailureReason,
    GeocodingUnavailableError,
)

GEOPLATFORM_DATA_SOURCE_CODE = "GEOPLATFORM_GEOCODER"
GEOPLATFORM_ADAPTER_VERSION = "geoplatform-address-v3"
GEOPLATFORM_SCHEMA_VERSION = "sirene-fallback-geocoding-v2"
GEOPLATFORM_POSITION_RULE_VERSION = "sirene-geoplatform-position-v2"
MIN_REQUEST_INTERVAL_SECONDS = 0.05
PROGRESS_REPORT_INTERVAL = 100

_MUNICIPALITY_CODE = re.compile(r"^(?:[0-9]{5}|2[AB][0-9]{3})$")
GeocodingOutcome = Literal[
    "MATCHED",
    "NOT_FOUND",
    "SKIPPED_INSUFFICIENT_ADDRESS",
    "OUTSIDE_METROPOLITAN_FRANCE",
]
FallbackFailureCode = Literal[
    "geocoder_unavailable",
    "geocoder_network_error",
    "geocoder_rate_limited",
    "geocoder_temporary_http_error",
    "geocoder_server_error",
    "geocoder_request_rejected",
    "geocoder_contract_changed",
]

_FAILURE_CODE_BY_REASON: dict[GeocodingFailureReason, FallbackFailureCode] = {
    "unknown": "geocoder_unavailable",
    "network": "geocoder_network_error",
    "rate_limited": "geocoder_rate_limited",
    "temporary_http": "geocoder_temporary_http_error",
    "server_error": "geocoder_server_error",
    "request_rejected": "geocoder_request_rejected",
}


class SireneFallbackGeocodingError(RuntimeError):
    """The fallback geocoding stage cannot safely complete or reconcile."""

    def __init__(
        self,
        message: str,
        *,
        transient: bool,
        code: str = "sirene_fallback_geocoding_failed",
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.code = code


@dataclass(frozen=True)
class SireneFallbackGeocodingRun:
    """Durable source-run identity for one resumable fallback pass."""

    id: UUID
    status: str


@dataclass(frozen=True)
class SireneFallbackGeocodingFailure:
    """Non-sensitive provider diagnostics safe to persist and display."""

    code: FallbackFailureCode
    final: bool
    http_status_code: int | None = None
    retry_after_seconds: int | None = None
    attempts: int | None = None

    def __post_init__(self) -> None:
        if self.http_status_code is not None and not 100 <= self.http_status_code <= 599:
            raise ValueError("fallback failure HTTP status code is invalid")
        if self.retry_after_seconds is not None and self.retry_after_seconds < 0:
            raise ValueError("fallback failure retry delay cannot be negative")
        if self.attempts is not None and self.attempts < 1:
            raise ValueError("fallback failure attempt count must be positive")


@dataclass(frozen=True)
class SireneFallbackGeocodingTarget:
    """One public establishment address still requiring a provider lookup."""

    collection_item_id: UUID
    external_identity_id: UUID
    input_address: str
    expected_municipality_code: str
    query_is_sufficient: bool


@dataclass(frozen=True)
class StagedSireneFallbackGeocoding:
    """Normalized provider outcome before independent PostGIS assessment."""

    target: SireneFallbackGeocodingTarget
    outcome: GeocodingOutcome
    provider_requested: bool
    content_fingerprint: str
    payload: dict[str, object]
    longitude: float | None
    latitude: float | None
    municipality_code: str | None
    result_type: str | None
    score: float | None
    provider_name: str | None
    provider_url: str | None


@dataclass(frozen=True)
class SireneFallbackGeocodingSummary:
    """Reconciled counters for one completed fallback source run."""

    requested_count: int
    matched_count: int
    usable_count: int
    to_verify_count: int
    missing_count: int
    skipped_count: int = 0

    def validate(self) -> None:
        """Reject counters that could hide a skipped or duplicated address."""

        counts = (
            self.requested_count,
            self.matched_count,
            self.usable_count,
            self.to_verify_count,
            self.missing_count,
            self.skipped_count,
        )
        if any(count < 0 for count in counts):
            raise SireneFallbackGeocodingError(
                "fallback geocoding counters cannot be negative",
                transient=False,
            )
        if self.usable_count + self.to_verify_count + self.missing_count != self.requested_count:
            raise SireneFallbackGeocodingError(
                "fallback geocoding counters do not reconcile",
                transient=False,
            )
        if self.matched_count != self.usable_count + self.to_verify_count:
            raise SireneFallbackGeocodingError(
                "fallback geocoding matched count is inconsistent",
                transient=False,
            )
        if self.skipped_count > self.missing_count:
            raise SireneFallbackGeocodingError(
                "fallback geocoding skipped count exceeds missing outcomes",
                transient=False,
            )


class SireneFallbackGeocodingBackend(Protocol):
    """Persistence boundary for restart-safe fallback geocoding."""

    def prepare_run(
        self,
        reservation: ReservedCollection,
        now: datetime,
    ) -> SireneFallbackGeocodingRun: ...

    def pending_targets(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
    ) -> tuple[SireneFallbackGeocodingTarget, ...]: ...

    def stage_outcome(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
        outcome: StagedSireneFallbackGeocoding,
        now: datetime,
    ) -> None: ...

    def complete_run(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
        now: datetime,
    ) -> SireneFallbackGeocodingSummary: ...

    def completed_summary(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
    ) -> SireneFallbackGeocodingSummary: ...

    def record_failure(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
        *,
        failure: SireneFallbackGeocodingFailure,
        now: datetime,
    ) -> None: ...


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


def normalize_geocoding_query_part(value: object) -> str:
    """Normalize one public address component without changing its source value."""

    normalized = " ".join(value.split()) if isinstance(value, str) else ""
    if len(normalized) >= 2 and normalized.startswith('"') and normalized.endswith('"'):
        return normalized[1:-1].strip()
    return normalized


def normalize_fallback_geocoding(
    target: SireneFallbackGeocodingTarget,
    outcome: GeocodingOutcome,
    result: GeocodedAddress | None,
) -> StagedSireneFallbackGeocoding:
    """Build deterministic evidence for one provider lookup or local skip."""

    if not target.input_address.strip():
        raise ValueError("fallback geocoding address cannot be empty")
    if _MUNICIPALITY_CODE.fullmatch(target.expected_municipality_code) is None:
        raise ValueError("fallback geocoding target has an invalid municipality code")
    if outcome == "MATCHED" and result is None:
        raise ValueError("a matched fallback geocoding outcome requires a result")
    if outcome != "MATCHED" and result is not None:
        raise ValueError("an unsuccessful fallback geocoding outcome cannot contain a result")

    normalized_result: dict[str, object] | None = None
    if result is not None:
        if not math.isfinite(result.longitude) or not math.isfinite(result.latitude):
            raise ValueError("fallback geocoding result coordinates must be finite")
        if result.score is not None and not 0 <= result.score <= 1:
            raise ValueError("fallback geocoding result score is outside the expected range")
        normalized_result = {
            "normalized_label": result.normalized_label,
            "structured_address": result.structured_address.as_dict(),
            "longitude": result.longitude,
            "latitude": result.latitude,
            "municipality_code": result.municipality_code,
            "ban_id": result.ban_id,
            "result_type": result.result_type,
            "score": result.score,
            "provider_name": result.provider_name,
            "provider_url": result.provider_url,
        }
    payload: dict[str, object] = {
        "request": {
            "input_address": target.input_address,
            "expected_municipality_code": target.expected_municipality_code,
            "provider_requested": outcome != "SKIPPED_INSUFFICIENT_ADDRESS",
        },
        "outcome": outcome,
        "result": normalized_result,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return StagedSireneFallbackGeocoding(
        target=target,
        outcome=outcome,
        provider_requested=outcome != "SKIPPED_INSUFFICIENT_ADDRESS",
        content_fingerprint=hashlib.sha256(canonical).hexdigest(),
        payload=payload,
        longitude=result.longitude if result is not None else None,
        latitude=result.latitude if result is not None else None,
        municipality_code=result.municipality_code if result is not None else None,
        result_type=result.result_type if result is not None else None,
        score=result.score if result is not None else None,
        provider_name=result.provider_name if result is not None else None,
        provider_url=result.provider_url if result is not None else None,
    )


class SireneFallbackGeocodingService:
    """Geocode only unresolved Sirene addresses with durable per-item checkpoints."""

    def __init__(
        self,
        backend: SireneFallbackGeocodingBackend,
        geocoder: Geocoder,
        *,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._backend = backend
        self._geocoder = geocoder
        self._clock = clock
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._next_request_at = 0.0

    def geocode_pending(
        self,
        reservation: ReservedCollection,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> SireneFallbackGeocodingSummary:
        """Resume unresolved addresses and complete only after full reconciliation."""

        if reservation.connector != "SIRENE":
            raise ValueError("only a Sirene collection can run fallback geocoding")
        run = self._backend.prepare_run(reservation, self._clock())
        if run.status == "SUCCEEDED":
            summary = self._backend.completed_summary(reservation, run)
            summary.validate()
            return summary
        if run.status != "RUNNING":
            raise SireneFallbackGeocodingError(
                "fallback geocoding source run is not restartable",
                transient=False,
            )

        targets = self._backend.pending_targets(reservation, run)
        total = len(targets)
        for processed, target in enumerate(targets, start=1):
            if not target.query_is_sufficient:
                staged = normalize_fallback_geocoding(
                    target,
                    "SKIPPED_INSUFFICIENT_ADDRESS",
                    None,
                )
                self._backend.stage_outcome(
                    reservation,
                    run,
                    staged,
                    self._clock(),
                )
                if on_progress is not None and (
                    processed % PROGRESS_REPORT_INTERVAL == 0 or processed == total
                ):
                    on_progress(processed, total)
                continue

            self._wait_for_rate_limit()
            try:
                result = self._geocoder.geocode(target.input_address)
                staged = normalize_fallback_geocoding(target, "MATCHED", result)
            except AddressNotFoundError:
                staged = normalize_fallback_geocoding(target, "NOT_FOUND", None)
            except AddressOutsideMetropolitanFranceError:
                staged = normalize_fallback_geocoding(
                    target,
                    "OUTSIDE_METROPOLITAN_FRANCE",
                    None,
                )
            except GeocodingUnavailableError as error:
                failure_code = _FAILURE_CODE_BY_REASON[error.reason]
                request_rejected = error.reason == "request_rejected"
                final = request_rejected or (reservation.attempt_number >= reservation.max_attempts)
                self._record_failure(
                    reservation,
                    run,
                    SireneFallbackGeocodingFailure(
                        code=failure_code,
                        final=final,
                        http_status_code=error.status_code,
                        retry_after_seconds=error.retry_after_seconds,
                        attempts=error.attempts,
                    ),
                )
                raise SireneFallbackGeocodingError(
                    (
                        "the fallback geocoder rejected the request"
                        if request_rejected
                        else "the fallback geocoder is temporarily unavailable"
                    ),
                    transient=not request_rejected,
                    code=f"sirene_fallback_{failure_code}",
                ) from error
            except GeocodingContractError as error:
                self._record_failure(
                    reservation,
                    run,
                    SireneFallbackGeocodingFailure(
                        code="geocoder_contract_changed",
                        final=True,
                    ),
                )
                raise SireneFallbackGeocodingError(
                    "the fallback geocoder contract changed",
                    transient=False,
                    code="sirene_fallback_geocoder_contract_changed",
                ) from error
            self._backend.stage_outcome(
                reservation,
                run,
                staged,
                self._clock(),
            )
            if on_progress is not None and (
                processed % PROGRESS_REPORT_INTERVAL == 0 or processed == total
            ):
                on_progress(processed, total)

        summary = self._backend.complete_run(reservation, run, self._clock())
        summary.validate()
        return summary

    def _wait_for_rate_limit(self) -> None:
        remaining = self._next_request_at - self._monotonic()
        if remaining > 0:
            self._sleeper(remaining)
        self._next_request_at = self._monotonic() + MIN_REQUEST_INTERVAL_SECONDS

    def _record_failure(
        self,
        reservation: ReservedCollection,
        run: SireneFallbackGeocodingRun,
        failure: SireneFallbackGeocodingFailure,
    ) -> None:
        self._backend.record_failure(
            reservation,
            run,
            failure=failure,
            now=self._clock(),
        )
