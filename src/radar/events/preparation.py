"""Local validation and selection rules applied before event persistence."""

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from radar.events.contracts import EventCandidate, EventLocationCandidate, EventPeriodCandidate

PARIS_TIMEZONE = ZoneInfo("Europe/Paris")
EARTH_RADIUS_METERS = 6_371_008.8

EventPeriodPrecision = Literal["DATE_ONLY", "DATE_AND_TIME", "MIXED"]
EventTemporalState = Literal["UPCOMING", "ONGOING", "PAST"]
EventPreparationDecision = Literal[
    "IMPORTABLE",
    "PAST_ONLY",
    "NO_VALID_PERIOD",
    "LOCATION_MISSING",
    "OUTSIDE_METROPOLITAN_FRANCE",
    "OUTSIDE_RADIUS",
]


@dataclass(frozen=True)
class ValidatedEventPeriod:
    """One readable source period interpreted without inventing recurrence."""

    source_index: int
    start_date: date
    end_date: date
    start_time: time | None
    end_time: time | None
    precision: EventPeriodPrecision
    interpretation_timezone: str
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class PreparedEventCandidate:
    """Candidate classified locally with diagnostics retained for collection counts."""

    candidate: EventCandidate
    decision: EventPreparationDecision
    location: EventLocationCandidate | None
    distance_meters: float | None
    periods: tuple[ValidatedEventPeriod, ...]
    temporal_state: EventTemporalState | None
    period_rejection_counts: tuple[tuple[str, int], ...]

    @property
    def has_non_ended_period(self) -> bool:
        """Return whether the candidate may create a new event fiche."""

        return self.temporal_state in {"UPCOMING", "ONGOING"}


@dataclass(frozen=True)
class PreparedEventPeriods:
    """Validated source periods and their time-relative state at collection time."""

    periods: tuple[ValidatedEventPeriod, ...]
    temporal_state: EventTemporalState | None
    rejection_counts: tuple[tuple[str, int], ...]

    @property
    def has_non_ended_period(self) -> bool:
        """Return whether at least one valid period is current or future."""

        return self.temporal_state in {"UPCOMING", "ONGOING"}


def _parse_date(value: str | None, reason: str) -> date:
    if value is None:
        raise ValueError(reason)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(reason) from error


def _parse_optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("invalid_end_date") from error


def _parse_optional_time(value: str | None, reason: str) -> time | None:
    if value is None:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError as error:
        raise ValueError(reason) from error


def _local_instant(day: date, value: time | None, *, end_of_day: bool) -> datetime:
    selected_time = value if value is not None else (time.max if end_of_day else time.min)
    instant = datetime.combine(day, selected_time)
    if instant.tzinfo is None:
        return instant.replace(tzinfo=PARIS_TIMEZONE)
    return instant.astimezone(PARIS_TIMEZONE)


def _validate_period(
    candidate: EventPeriodCandidate,
    source_index: int,
) -> ValidatedEventPeriod:
    start_date = _parse_date(candidate.start_date, "missing_or_invalid_start_date")
    end_date = _parse_optional_date(candidate.end_date) or start_date
    if end_date < start_date:
        raise ValueError("end_before_start_date")

    start_time = _parse_optional_time(candidate.start_time, "invalid_start_time")
    end_time = _parse_optional_time(candidate.end_time, "invalid_end_time")
    start_at = _local_instant(start_date, start_time, end_of_day=False)
    end_at = _local_instant(end_date, end_time, end_of_day=True)
    if end_at < start_at:
        raise ValueError("end_before_start_time")

    if start_time is None and end_time is None:
        precision: EventPeriodPrecision = "DATE_ONLY"
    elif start_time is not None and end_time is not None:
        precision = "DATE_AND_TIME"
    else:
        precision = "MIXED"
    return ValidatedEventPeriod(
        source_index=source_index,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        precision=precision,
        interpretation_timezone="Europe/Paris",
        start_at=start_at,
        end_at=end_at,
    )


def _validated_periods(
    candidates: tuple[EventPeriodCandidate, ...],
) -> tuple[tuple[ValidatedEventPeriod, ...], tuple[tuple[str, int], ...]]:
    periods: list[ValidatedEventPeriod] = []
    rejection_counts: Counter[str] = Counter()
    for source_index, candidate in enumerate(candidates, start=1):
        try:
            periods.append(_validate_period(candidate, source_index))
        except ValueError as error:
            rejection_counts[str(error)] += 1
    return tuple(periods), tuple(sorted(rejection_counts.items()))


def _temporal_state(
    periods: tuple[ValidatedEventPeriod, ...],
    now: datetime,
) -> EventTemporalState | None:
    if not periods:
        return None
    if any(period.start_at <= now <= period.end_at for period in periods):
        return "ONGOING"
    if any(period.start_at > now for period in periods):
        return "UPCOMING"
    return "PAST"


def prepare_event_periods(
    candidate: EventCandidate,
    now: datetime,
) -> PreparedEventPeriods:
    """Validate published periods independently from provider geography."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("the event preparation clock must return an aware datetime")
    periods, rejection_counts = _validated_periods(candidate.periods)
    temporal_state = _temporal_state(periods, now.astimezone(PARIS_TIMEZONE))
    return PreparedEventPeriods(periods, temporal_state, rejection_counts)


def _distance_meters(
    latitude: float,
    longitude: float,
    candidate_latitude: float,
    candidate_longitude: float,
) -> float:
    latitude_radians = math.radians(latitude)
    candidate_latitude_radians = math.radians(candidate_latitude)
    latitude_delta = candidate_latitude_radians - latitude_radians
    longitude_delta = math.radians(candidate_longitude - longitude)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_radians)
        * math.cos(candidate_latitude_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return (
        EARTH_RADIUS_METERS
        * 2
        * math.atan2(
            math.sqrt(haversine),
            math.sqrt(1 - haversine),
        )
    )


class EventCandidatePreparationService:
    """Validate dates and independently enforce Radar's geographic circle."""

    def __init__(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_meters: int,
        contains_metropolitan_point: Callable[[float, float], bool],
        clock: Callable[[], datetime],
    ) -> None:
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("the event collection latitude is invalid")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("the event collection longitude is invalid")
        if not 1 <= radius_meters <= 50_000:
            raise ValueError("the event collection radius must be between 1 and 50,000 meters")
        self._latitude = latitude
        self._longitude = longitude
        self._radius_meters = radius_meters
        self._contains_metropolitan_point = contains_metropolitan_point
        self._clock = clock

    def prepare(self, candidate: EventCandidate) -> PreparedEventCandidate:
        """Return a deterministic import decision without mutating source data."""

        now = self._clock()
        prepared_periods = prepare_event_periods(candidate, now)
        periods = prepared_periods.periods
        rejection_counts = prepared_periods.rejection_counts
        temporal_state = prepared_periods.temporal_state
        location, distance, geographic_decision = self._select_location(candidate.locations)

        if geographic_decision is not None:
            decision = geographic_decision
        elif temporal_state is None:
            decision = "NO_VALID_PERIOD"
        elif temporal_state == "PAST":
            decision = "PAST_ONLY"
        else:
            decision = "IMPORTABLE"
        return PreparedEventCandidate(
            candidate=candidate,
            decision=decision,
            location=location,
            distance_meters=distance,
            periods=periods,
            temporal_state=temporal_state,
            period_rejection_counts=rejection_counts,
        )

    def _select_location(
        self,
        locations: tuple[EventLocationCandidate, ...],
    ) -> tuple[
        EventLocationCandidate | None,
        float | None,
        EventPreparationDecision | None,
    ]:
        positioned: list[tuple[EventLocationCandidate, float]] = []
        metropolitan: list[tuple[EventLocationCandidate, float]] = []
        for location in locations:
            if location.latitude is None or location.longitude is None:
                continue
            if (
                not math.isfinite(location.latitude)
                or not math.isfinite(location.longitude)
                or not -90 <= location.latitude <= 90
                or not -180 <= location.longitude <= 180
            ):
                continue
            distance = _distance_meters(
                self._latitude,
                self._longitude,
                location.latitude,
                location.longitude,
            )
            positioned.append((location, distance))
            if self._contains_metropolitan_point(location.latitude, location.longitude):
                metropolitan.append((location, distance))

        if not positioned:
            return None, None, "LOCATION_MISSING"
        if not metropolitan:
            return None, None, "OUTSIDE_METROPOLITAN_FRANCE"
        selected, distance = min(metropolitan, key=lambda item: item[1])
        if distance > self._radius_meters:
            return selected, distance, "OUTSIDE_RADIUS"
        return selected, distance, None
