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
    GeocodingUnavailableError,
)

GEOPLATFORM_DATA_SOURCE_CODE = "GEOPLATFORM_GEOCODER"
GEOPLATFORM_ADAPTER_VERSION = "geoplatform-address-v1"
GEOPLATFORM_SCHEMA_VERSION = "sirene-fallback-geocoding-v1"
GEOPLATFORM_POSITION_RULE_VERSION = "sirene-geoplatform-position-v1"
MIN_REQUEST_INTERVAL_SECONDS = 0.05

_MUNICIPALITY_CODE = re.compile(r"^(?:[0-9]{5}|2[AB][0-9]{3})$")
GeocodingOutcome = Literal["MATCHED", "NOT_FOUND", "OUTSIDE_METROPOLITAN_FRANCE"]


class SireneFallbackGeocodingError(RuntimeError):
    """The fallback geocoding stage cannot safely complete or reconcile."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class SireneFallbackGeocodingRun:
    """Durable source-run identity for one resumable fallback pass."""

    id: UUID
    status: str


@dataclass(frozen=True)
class SireneFallbackGeocodingTarget:
    """One public establishment address still requiring a provider lookup."""

    collection_item_id: UUID
    external_identity_id: UUID
    input_address: str
    expected_municipality_code: str


@dataclass(frozen=True)
class StagedSireneFallbackGeocoding:
    """Normalized provider outcome before independent PostGIS assessment."""

    target: SireneFallbackGeocodingTarget
    outcome: GeocodingOutcome
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

    def validate(self) -> None:
        """Reject counters that could hide a skipped or duplicated address."""

        counts = (
            self.requested_count,
            self.matched_count,
            self.usable_count,
            self.to_verify_count,
            self.missing_count,
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
        code: str,
        final: bool,
        now: datetime,
    ) -> None: ...


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


def normalize_fallback_geocoding(
    target: SireneFallbackGeocodingTarget,
    outcome: GeocodingOutcome,
    result: GeocodedAddress | None,
) -> StagedSireneFallbackGeocoding:
    """Build a deterministic, provider-owned observation for one lookup outcome."""

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

        for target in self._backend.pending_targets(reservation, run):
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
                self._record_failure(reservation, run, "geocoder_unavailable", final=False)
                raise SireneFallbackGeocodingError(
                    "the fallback geocoder is temporarily unavailable",
                    transient=True,
                ) from error
            except GeocodingContractError as error:
                self._record_failure(reservation, run, "geocoder_contract_changed", final=True)
                raise SireneFallbackGeocodingError(
                    "the fallback geocoder contract changed",
                    transient=False,
                ) from error
            self._backend.stage_outcome(
                reservation,
                run,
                staged,
                self._clock(),
            )

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
        code: str,
        *,
        final: bool,
    ) -> None:
        self._backend.record_failure(
            reservation,
            run,
            code=code,
            final=final,
            now=self._clock(),
        )
