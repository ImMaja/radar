"""Tests for local DATAtourisme event validation and selection."""

from datetime import UTC, datetime

import pytest

from radar.events.contracts import (
    EventCandidate,
    EventLocationCandidate,
    EventPeriodCandidate,
)
from radar.events.preparation import EventCandidatePreparationService

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
DAX_LATITUDE = 43.70884
DAX_LONGITUDE = -1.051952


def event_candidate(
    *,
    periods: tuple[EventPeriodCandidate, ...] | None = None,
    locations: tuple[EventLocationCandidate, ...] | None = None,
) -> EventCandidate:
    return EventCandidate(
        external_identifier="5c92ef83-51c2-4dad-adfd-105d56320b41",
        source_uri="https://example.test/events/5c92ef83-51c2-4dad-adfd-105d56320b41",
        producer_identifier="producer-1",
        title="Fête locale",
        types=("Festival",),
        descriptions=(),
        locations=(
            locations
            if locations is not None
            else (EventLocationCandidate(DAX_LONGITUDE, DAX_LATITUDE, ()),)
        ),
        periods=(
            periods
            if periods is not None
            else (EventPeriodCandidate("2026-10-10", None, None, None),)
        ),
        contacts=(),
        source_parties=(),
        source_updated_at=None,
        aggregator_updated_at=None,
        source_obsolete=None,
    )


def service(
    *,
    radius_meters: int = 50_000,
    contains_metropolitan_point: object | None = None,
) -> EventCandidatePreparationService:
    predicate = (
        contains_metropolitan_point
        if callable(contains_metropolitan_point)
        else lambda _latitude, _longitude: True
    )
    return EventCandidatePreparationService(
        latitude=DAX_LATITUDE,
        longitude=DAX_LONGITUDE,
        radius_meters=radius_meters,
        contains_metropolitan_point=predicate,
        clock=lambda: NOW,
    )


def test_future_date_only_period_is_importable_until_the_end_of_its_day() -> None:
    prepared = service().prepare(event_candidate())

    assert prepared.decision == "IMPORTABLE"
    assert prepared.temporal_state == "UPCOMING"
    assert prepared.has_non_ended_period is True
    assert prepared.period_rejection_counts == ()
    assert len(prepared.periods) == 1
    assert prepared.periods[0].precision == "DATE_ONLY"
    assert prepared.periods[0].start_at.isoformat() == "2026-10-10T00:00:00+02:00"
    assert prepared.periods[0].end_at.isoformat() == "2026-10-10T23:59:59.999999+02:00"


def test_period_spanning_the_current_instant_is_ongoing() -> None:
    candidate = event_candidate(
        periods=(EventPeriodCandidate("2026-09-30", "2026-10-02", "10:00", "18:00"),)
    )

    prepared = service().prepare(candidate)

    assert prepared.decision == "IMPORTABLE"
    assert prepared.temporal_state == "ONGOING"
    assert prepared.periods[0].precision == "DATE_AND_TIME"


def test_past_periods_are_valid_but_cannot_create_a_new_fiche() -> None:
    candidate = event_candidate(
        periods=(EventPeriodCandidate("2026-09-01", "2026-09-02", None, None),)
    )

    prepared = service().prepare(candidate)

    assert prepared.decision == "PAST_ONLY"
    assert prepared.temporal_state == "PAST"
    assert prepared.has_non_ended_period is False
    assert len(prepared.periods) == 1


def test_invalid_periods_are_counted_without_discarding_valid_siblings() -> None:
    candidate = event_candidate(
        periods=(
            EventPeriodCandidate(None, None, None, None),
            EventPeriodCandidate("2026-10-05", "not-a-date", None, None),
            EventPeriodCandidate("2026-10-05", "2026-10-04", None, None),
            EventPeriodCandidate("2026-10-05", None, "18:00", "12:00"),
            EventPeriodCandidate("2026-10-05", None, "bad", None),
            EventPeriodCandidate("2026-10-05", None, "10:00", None),
        )
    )

    prepared = service().prepare(candidate)

    assert prepared.decision == "IMPORTABLE"
    assert len(prepared.periods) == 1
    assert prepared.periods[0].source_index == 6
    assert prepared.periods[0].precision == "MIXED"
    assert dict(prepared.period_rejection_counts) == {
        "end_before_start_date": 1,
        "end_before_start_time": 1,
        "invalid_end_date": 1,
        "invalid_start_time": 1,
        "missing_or_invalid_start_date": 1,
    }


def test_an_empty_or_entirely_invalid_period_set_is_not_importable() -> None:
    empty = service().prepare(event_candidate(periods=()))
    invalid = service().prepare(
        event_candidate(periods=(EventPeriodCandidate("invalid", None, None, None),))
    )

    assert empty.decision == "NO_VALID_PERIOD"
    assert empty.temporal_state is None
    assert invalid.decision == "NO_VALID_PERIOD"
    assert dict(invalid.period_rejection_counts) == {"missing_or_invalid_start_date": 1}


def test_nearest_metropolitan_location_is_selected_with_a_local_distance() -> None:
    distant = EventLocationCandidate(-1.3, 43.9, ())
    nearby = EventLocationCandidate(DAX_LONGITUDE + 0.001, DAX_LATITUDE, ())

    prepared = service().prepare(event_candidate(locations=(distant, nearby)))

    assert prepared.decision == "IMPORTABLE"
    assert prepared.location == nearby
    assert prepared.distance_meters is not None
    assert 70 < prepared.distance_meters < 100


def test_missing_invalid_and_foreign_locations_are_distinguished() -> None:
    missing = service().prepare(
        event_candidate(locations=(EventLocationCandidate(None, None, ()),))
    )
    invalid = service().prepare(
        event_candidate(locations=(EventLocationCandidate(181.0, 91.0, ()),))
    )
    foreign = service(contains_metropolitan_point=lambda _lat, _lon: False).prepare(
        event_candidate()
    )

    assert missing.decision == "LOCATION_MISSING"
    assert invalid.decision == "LOCATION_MISSING"
    assert foreign.decision == "OUTSIDE_METROPOLITAN_FRANCE"
    assert foreign.location is None


def test_provider_radius_is_not_trusted_for_the_exact_local_circle() -> None:
    outside = EventLocationCandidate(DAX_LONGITUDE + 0.02, DAX_LATITUDE, ())

    prepared = service(radius_meters=1_000).prepare(event_candidate(locations=(outside,)))

    assert prepared.decision == "OUTSIDE_RADIUS"
    assert prepared.location == outside
    assert prepared.distance_meters is not None
    assert prepared.distance_meters > 1_000


def test_geographic_rejection_does_not_hide_period_diagnostics() -> None:
    candidate = event_candidate(
        periods=(EventPeriodCandidate(None, None, None, None),),
        locations=(),
    )

    prepared = service().prepare(candidate)

    assert prepared.decision == "LOCATION_MISSING"
    assert dict(prepared.period_rejection_counts) == {"missing_or_invalid_start_date": 1}


def test_constructor_and_clock_reject_invalid_collection_context() -> None:
    with pytest.raises(ValueError, match="latitude"):
        EventCandidatePreparationService(
            latitude=float("nan"),
            longitude=DAX_LONGITUDE,
            radius_meters=50_000,
            contains_metropolitan_point=lambda _lat, _lon: True,
            clock=lambda: NOW,
        )
    with pytest.raises(ValueError, match="longitude"):
        EventCandidatePreparationService(
            latitude=DAX_LATITUDE,
            longitude=200,
            radius_meters=50_000,
            contains_metropolitan_point=lambda _lat, _lon: True,
            clock=lambda: NOW,
        )
    with pytest.raises(ValueError, match="radius"):
        service(radius_meters=50_001)

    naive_clock = EventCandidatePreparationService(
        latitude=DAX_LATITUDE,
        longitude=DAX_LONGITUDE,
        radius_meters=50_000,
        contains_metropolitan_point=lambda _lat, _lon: True,
        clock=lambda: NOW.replace(tzinfo=None),
    )
    with pytest.raises(ValueError, match="aware datetime"):
        naive_clock.prepare(event_candidate())


def test_explicit_time_offsets_are_compared_as_instants() -> None:
    candidate = event_candidate(
        periods=(
            EventPeriodCandidate(
                "2026-10-01",
                "2026-10-01",
                "13:30:00+02:00",
                "14:30:00+02:00",
            ),
        )
    )

    prepared = service().prepare(candidate)

    assert prepared.temporal_state == "ONGOING"
    assert prepared.periods[0].start_at.isoformat() == "2026-10-01T13:30:00+02:00"
