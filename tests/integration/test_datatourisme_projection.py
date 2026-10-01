"""PostgreSQL projection of DATAtourisme events, periods and provenance."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from radar.collections.contracts import ReservedCollection
from radar.events.contracts import EventCandidate, EventContactCandidate, EventPeriodCandidate
from radar.events.projection import EventProjectionError, EventProjectionService
from radar.events.staging import EventCandidatePageStager
from radar.persistence.datatourisme_projection import SqlAlchemyEventProjectionRepository
from radar.persistence.datatourisme_staging import SqlAlchemyEventCandidateStagingRepository
from radar.providers.datatourisme import DatatourismePage

from .test_datatourisme_staging import NOW, candidate, seed_running_collection

pytestmark = pytest.mark.integration


def _page(number: int, candidates: tuple[EventCandidate, ...]) -> DatatourismePage:
    return DatatourismePage(
        number=number,
        announced_total=len(candidates),
        announced_total_pages=1,
        received_count=len(candidates),
        importable_candidates=candidates,
        rejection_counts={},
        next_link_fingerprint=None,
        terminal=True,
    )


def _finish_source(engine: Engine, batch_id: object, cycle_id: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE collection_batch SET state = 'SUCCEEDED' WHERE id = :batch_id"),
            {"batch_id": batch_id},
        )
        connection.execute(
            text(
                """
                UPDATE collection_source_run SET status = 'SUCCEEDED'
                WHERE collection_cycle_id = :cycle_id AND source = 'DATATOURISME_API'
                """
            ),
            {"cycle_id": cycle_id},
        )


def _next_attempt(
    engine: Engine, reservation: ReservedCollection, batch_id: object
) -> ReservedCollection:
    next_attempt_id = uuid4()
    next_number = reservation.attempt_number + 1
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE collection_attempt SET finished_at = :now WHERE id = :id"),
            {"id": reservation.attempt_id, "now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO collection_attempt (
                    id, collection_job_id, attempt_number, worker_id,
                    started_at, heartbeat_at
                ) VALUES (:id, :job_id, :attempt_number, 'test-worker', :now, :now)
                """
            ),
            {
                "id": next_attempt_id,
                "job_id": reservation.job_id,
                "attempt_number": next_number,
                "now": NOW,
            },
        )
        connection.execute(
            text("UPDATE collection_job SET attempt_count = :attempt_number WHERE id = :id"),
            {"id": reservation.job_id, "attempt_number": next_number},
        )
        connection.execute(
            text(
                """
                UPDATE collection_batch SET state = 'RUNNING',
                    attempt_count = :attempt_number,
                    last_collection_attempt_id = :attempt_id
                WHERE id = :batch_id
                """
            ),
            {
                "attempt_id": next_attempt_id,
                "attempt_number": next_number,
                "batch_id": batch_id,
            },
        )
        connection.execute(
            text(
                """
                UPDATE collection_source_run SET status = 'RUNNING'
                WHERE collection_cycle_id = :cycle_id
                """
            ),
            {"cycle_id": reservation.cycle_id},
        )
    return replace(reservation, attempt_id=next_attempt_id, attempt_number=next_number)


def test_two_new_uuids_claiming_one_source_uri_are_quarantined(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    first = candidate(81)
    second = replace(candidate(82), source_uri=first.source_uri)
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    projector = EventProjectionService(
        SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
    )
    try:
        stager.handle(reservation, batch_id, _page(1, (first, second)))
        _finish_source(engine, batch_id, reservation.cycle_id)
        summary = projector.project(reservation)
        assert projector.project(reservation) == summary
        with engine.connect() as connection:
            observations = (
                connection.execute(
                    text(
                        """
                        SELECT validation_status, normalization_error ->> 'code' AS code
                        FROM source_observation ORDER BY id
                        """
                    )
                )
                .mappings()
                .all()
            )
            decisions = (
                connection.execute(text("SELECT decision FROM collection_item ORDER BY item_rank"))
                .scalars()
                .all()
            )
            event_count = connection.execute(text("SELECT count(*) FROM event")).scalar_one()
    finally:
        engine.dispose()

    assert summary.identity_conflict_count == 2
    assert decisions == ["ERROR", "ERROR"]
    assert event_count == 0
    assert all(
        observation["validation_status"] == "IDENTITY_CONFLICT" for observation in observations
    )
    assert all(
        observation["code"] == "SOURCE_URI_SHARED_BY_MULTIPLE_UUIDS" for observation in observations
    )


def test_conflicting_new_uuid_does_not_change_the_existing_event(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    original = candidate(91)
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    projector = EventProjectionService(
        SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
    )
    try:
        stager.handle(reservation, batch_id, _page(1, (original,)))
        _finish_source(engine, batch_id, reservation.cycle_id)
        assert projector.project(reservation).created_count == 1
        retry = _next_attempt(engine, reservation, batch_id)
        conflicting = replace(candidate(92), source_uri=original.source_uri)
        stager.handle(retry, batch_id, _page(1, (conflicting,)))
        _finish_source(engine, batch_id, retry.cycle_id)
        summary = projector.project(retry)

        later_attempt = _next_attempt(engine, retry, batch_id)
        corrected = replace(conflicting, source_uri="https://data.datatourisme.fr/92-corrected")
        stager.handle(later_attempt, batch_id, _page(1, (corrected,)))
        _finish_source(engine, batch_id, later_attempt.cycle_id)
        still_blocked = projector.project(later_attempt)
        with engine.connect() as connection:
            events = (
                connection.execute(text("SELECT source_title, source_uri FROM event"))
                .mappings()
                .all()
            )
            bindings = connection.execute(text("SELECT count(*) FROM source_binding")).scalar_one()
            conflict_status = connection.execute(
                text(
                    """
                    SELECT validation_status FROM source_observation
                    WHERE source_reference = :uri AND source_binding_id IS NULL
                    """
                ),
                {"uri": original.source_uri},
            ).scalar_one()
            corrected_status = (
                connection.execute(
                    text(
                        """
                    SELECT validation_status, normalization_error ->> 'code' AS code
                    FROM source_observation WHERE source_reference = :uri
                    """
                    ),
                    {"uri": corrected.source_uri},
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()

    assert summary.identity_conflict_count == 1
    assert still_blocked.identity_conflict_count == 1
    assert [dict(event) for event in events] == [
        {"source_title": original.title, "source_uri": original.source_uri}
    ]
    assert bindings == 1
    assert conflict_status == "IDENTITY_CONFLICT"
    assert dict(corrected_status) == {
        "validation_status": "IDENTITY_CONFLICT",
        "code": "PRIOR_IDENTITY_CONFLICT",
    }


def test_conflicting_return_of_a_published_revision_preserves_its_observation(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    original = candidate(93)
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    projector = EventProjectionService(
        SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
    )
    try:
        stager.handle(reservation, batch_id, _page(1, (original,)))
        _finish_source(engine, batch_id, reservation.cycle_id)
        assert projector.project(reservation).created_count == 1

        second_attempt = _next_attempt(engine, reservation, batch_id)
        changed = replace(original, source_uri="https://data.datatourisme.fr/93-new")
        competing = replace(candidate(94), source_uri=original.source_uri)
        stager.handle(second_attempt, batch_id, _page(1, (changed, competing)))
        _finish_source(engine, batch_id, reservation.cycle_id)
        assert projector.project(second_attempt).identity_conflict_count == 1

        third_attempt = _next_attempt(engine, second_attempt, batch_id)
        stager.handle(third_attempt, batch_id, _page(1, (original,)))
        _finish_source(engine, batch_id, reservation.cycle_id)
        summary = projector.project(third_attempt)
        with engine.connect() as connection:
            current_uri = connection.execute(text("SELECT source_uri FROM event")).scalar_one()
            original_observation = (
                connection.execute(
                    text(
                        """
                        SELECT validation_status, source_binding_id
                        FROM source_observation
                        WHERE source_reference = :uri
                          AND external_identity_id = (
                              SELECT id FROM external_identity
                              WHERE canonical_value = :identifier
                          )
                        """
                    ),
                    {
                        "uri": original.source_uri,
                        "identifier": original.external_identifier,
                    },
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()

    assert summary.identity_conflict_count == 1
    assert current_uri == changed.source_uri
    assert original_observation["validation_status"] == "VALID"
    assert original_observation["source_binding_id"] is not None


def test_projection_creates_only_current_events_and_reconciles_retries(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    future = replace(
        candidate(1),
        contacts=(
            EventContactCandidate(
                "GENERAL",
                "Office de tourisme",
                ("05 58 12 34 56",),
                ("https://EXAMPLE.fr/evenement",),
            ),
        ),
    )
    past = candidate(2, periods=(EventPeriodCandidate("2026-09-01", None, None, None),))
    outside = candidate(3, longitude=-2.2)
    invalid = candidate(4, periods=(EventPeriodCandidate("invalid", None, None, None),))
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    projector = EventProjectionService(
        SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
    )
    try:
        stager.handle(reservation, batch_id, _page(1, (future, past, outside, invalid)))
        with pytest.raises(EventProjectionError, match="completed source run"):
            projector.project(reservation)
        _finish_source(engine, batch_id, reservation.cycle_id)

        first = projector.project(reservation)
        second = projector.project(reservation)
        with engine.connect() as connection:
            events = (
                connection.execute(
                    text(
                        """
                    SELECT event.source_title, event.declared_status,
                           event.organizer_name, opportunity.hidden_at
                    FROM event JOIN opportunity ON opportunity.id = event.id
                    """
                    )
                )
                .mappings()
                .all()
            )
            periods = (
                connection.execute(text("SELECT start_date, source_path FROM event_period"))
                .mappings()
                .all()
            )
            locations = (
                connection.execute(
                    text(
                        """
                        SELECT layer, full_address, municipality_code, position_origin,
                               precision, usability, ST_X(point::geometry) AS longitude,
                               ST_Y(point::geometry) AS latitude,
                               diagnostics ->> 'selected_location_index' AS selected_index
                        FROM location_assertion
                        """
                    )
                )
                .mappings()
                .all()
            )
            contacts = (
                connection.execute(
                    text(
                        """
                        SELECT contact.type, contact.display_value,
                               contact.normalized_value, contact.scope,
                               contact.label, contact.source_reference
                        FROM contact_point AS contact
                        JOIN contact_set AS contact_set ON contact_set.id = contact.contact_set_id
                        WHERE contact_set.layer = 'SOURCE'
                        ORDER BY contact.display_order
                        """
                    )
                )
                .mappings()
                .all()
            )
            sightings = connection.execute(
                text("SELECT count(*) FROM source_sighting")
            ).scalar_one()
            decisions = (
                connection.execute(
                    text(
                        """
                    SELECT decision FROM collection_item
                    WHERE collection_cycle_id = :cycle_id ORDER BY item_rank
                    """
                    ),
                    {"cycle_id": reservation.cycle_id},
                )
                .scalars()
                .all()
            )
    finally:
        engine.dispose()

    assert first == second
    assert (
        first.requested_count,
        first.created_count,
        first.rejected_count,
        first.counted_only_count,
    ) == (4, 1, 2, 1)
    assert decisions == ["CREATED", "REJECTED", "COUNTED_ONLY", "REJECTED"]
    assert len(events) == 1
    assert events[0]["source_title"] == "Événement 1"
    assert events[0]["declared_status"] == "UNKNOWN"
    assert events[0]["organizer_name"] is None
    assert periods[0]["source_path"] == "periods[0]"
    assert sightings == 1
    assert len(locations) == 1
    assert locations[0]["layer"] == "SOURCE"
    assert locations[0]["full_address"] == "Place de la Mairie, 40100 Dax"
    assert locations[0]["municipality_code"] == "40088"
    assert locations[0]["position_origin"] == "DATATOURISME"
    assert locations[0]["precision"] == "UNKNOWN"
    assert locations[0]["usability"] == "USABLE"
    assert locations[0]["longitude"] == pytest.approx(-1.051952)
    assert locations[0]["latitude"] == pytest.approx(43.70884)
    assert locations[0]["selected_index"] == "1"
    assert [contact["type"] for contact in contacts] == ["PHONE", "WEBSITE"]
    assert [contact["normalized_value"] for contact in contacts] == [
        "+33558123456",
        "https://example.fr/evenement",
    ]
    assert all(contact["scope"] == "UNKNOWN" for contact in contacts)
    assert contacts[0]["label"] == "Contact général — Office de tourisme"
    assert contacts[0]["source_reference"] == "contacts[0].phones[0]"


def test_projection_updates_a_hidden_event_without_replacing_user_periods_or_location(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    projector = EventProjectionService(
        SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
    )
    try:
        initial = replace(
            candidate(10),
            contacts=(EventContactCandidate("GENERAL", None, ("05 58 12 34 56",), ()),),
        )
        stager.handle(reservation, batch_id, _page(1, (initial,)))
        _finish_source(engine, batch_id, reservation.cycle_id)
        assert projector.project(reservation).created_count == 1
        user_set_id = uuid4()
        with engine.begin() as connection:
            event_id = connection.execute(text("SELECT id FROM event")).scalar_one()
            connection.execute(
                text(
                    """
                    UPDATE opportunity SET hidden_at = :now, hidden_reason = 'NOT_RELEVANT'
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO event_period_set (
                        id, event_id, layer, is_current, created_at
                    ) VALUES (:set_id, :event_id, 'USER', TRUE, :now)
                    """
                ),
                {"set_id": user_set_id, "event_id": event_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO event_period (
                        id, period_set_id, display_order, start_date, end_date,
                        interpretation_timezone, precision, source_path, created_at
                    ) VALUES (
                        :id, :set_id, 0, '2028-01-01', '2028-01-01',
                        'Europe/Paris', 'DATE_ONLY', 'user', :now
                    )
                    """
                ),
                {"id": uuid4(), "set_id": user_set_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO location_assertion (
                        id, opportunity_id, layer, full_address, structured_address,
                        country_code, point, position_origin, precision, usability,
                        rule_version, diagnostics, is_current, created_at, updated_at
                    ) VALUES (
                        :id, :event_id, 'USER', 'Lieu confirmé', '{}'::jsonb, 'FR',
                        ST_SetSRID(ST_MakePoint(-1.03, 43.71), 4326)::geography,
                        'USER_CONFIRMED', 'ROOFTOP', 'USABLE',
                        'user-confirmed', '{}'::jsonb, TRUE, :now, :now
                    )
                    """
                ),
                {"id": uuid4(), "event_id": event_id, "now": NOW},
            )
            user_contact_set_id = uuid4()
            connection.execute(
                text(
                    """
                    INSERT INTO contact_set (
                        id, opportunity_id, layer, is_current, created_at
                    ) VALUES (:id, :event_id, 'USER', TRUE, :now)
                    """
                ),
                {"id": user_contact_set_id, "event_id": event_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO contact_point (
                        id, contact_set_id, type, display_value, normalized_value,
                        scope, label, display_order, created_at
                    ) VALUES (
                        :id, :set_id, 'EMAIL', 'contact@example.fr', 'contact@example.fr',
                        'UNKNOWN', 'Ajout utilisateur', 0, :now
                    )
                    """
                ),
                {"id": uuid4(), "set_id": user_contact_set_id, "now": NOW},
            )
            next_attempt_id = uuid4()
            connection.execute(
                text(
                    """
                    UPDATE collection_attempt SET finished_at = :now WHERE id = :attempt_id
                    """
                ),
                {"attempt_id": reservation.attempt_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO collection_attempt (
                        id, collection_job_id, attempt_number, worker_id,
                        started_at, heartbeat_at
                    ) VALUES (:id, :job_id, 2, 'test-worker', :now, :now)
                    """
                ),
                {"id": next_attempt_id, "job_id": reservation.job_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    UPDATE collection_job SET attempt_count = 2 WHERE id = :job_id
                    """
                ),
                {"job_id": reservation.job_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE collection_batch SET state = 'RUNNING', attempt_count = 2,
                        last_collection_attempt_id = :attempt_id
                    WHERE id = :batch_id
                    """
                ),
                {"attempt_id": next_attempt_id, "batch_id": batch_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE collection_source_run SET status = 'RUNNING'
                    WHERE collection_cycle_id = :cycle_id
                    """
                ),
                {"cycle_id": reservation.cycle_id},
            )
        retry = replace(reservation, attempt_id=next_attempt_id, attempt_number=2)
        changed = replace(
            candidate(10, longitude=-1.04),
            title="Événement 10 corrigé",
            periods=(EventPeriodCandidate("2026-09-15", None, None, None),),
            contacts=(
                EventContactCandidate(
                    "BOOKING",
                    None,
                    ("+33 6 11 22 33 44",),
                    ("https://example.fr/reservation",),
                ),
            ),
        )
        stager.handle(retry, batch_id, _page(1, (changed,)))
        _finish_source(engine, batch_id, retry.cycle_id)
        summary = projector.project(retry)
        with engine.connect() as connection:
            event = (
                connection.execute(
                    text(
                        """
                    SELECT event.id, event.source_title, opportunity.hidden_at
                    FROM event JOIN opportunity ON opportunity.id = event.id
                    """
                    )
                )
                .mappings()
                .one()
            )
            sets = (
                connection.execute(
                    text(
                        """
                    SELECT layer, is_current, retired_at
                    FROM event_period_set WHERE event_id = :event_id
                    ORDER BY layer, is_current
                    """
                    ),
                    {"event_id": event_id},
                )
                .mappings()
                .all()
            )
            binding_count = connection.execute(
                text("SELECT count(*) FROM source_binding")
            ).scalar_one()
            locations = (
                connection.execute(
                    text(
                        """
                        SELECT layer, is_current, retired_at, full_address,
                               ST_X(point::geometry) AS longitude
                        FROM location_assertion WHERE opportunity_id = :event_id
                        ORDER BY layer, is_current
                        """
                    ),
                    {"event_id": event_id},
                )
                .mappings()
                .all()
            )
            contact_sets = (
                connection.execute(
                    text(
                        """
                        SELECT contact_set.layer, contact_set.is_current,
                               contact_set.retired_at, contact.type,
                               contact.normalized_value, contact.scope
                        FROM contact_set
                        JOIN contact_point AS contact ON contact.contact_set_id = contact_set.id
                        WHERE contact_set.opportunity_id = :event_id
                        ORDER BY contact_set.layer, contact_set.is_current,
                                 contact.display_order
                        """
                    ),
                    {"event_id": event_id},
                )
                .mappings()
                .all()
            )
    finally:
        engine.dispose()

    assert summary.updated_count == 1
    assert event["id"] == event_id
    assert event["source_title"] == "Événement 10 corrigé"
    assert event["hidden_at"] == NOW
    assert binding_count == 1
    assert [(row["layer"], row["is_current"]) for row in sets] == [
        ("SOURCE", False),
        ("SOURCE", True),
        ("USER", True),
    ]
    assert sets[0]["retired_at"] == NOW
    assert [(row["layer"], row["is_current"]) for row in locations] == [
        ("SOURCE", False),
        ("SOURCE", True),
        ("USER", True),
    ]
    assert [row["longitude"] for row in locations] == pytest.approx([-1.051952, -1.04, -1.03])
    assert locations[0]["retired_at"] == NOW
    assert locations[2]["full_address"] == "Lieu confirmé"
    assert [(row["layer"], row["is_current"], row["type"]) for row in contact_sets] == [
        ("SOURCE", False, "PHONE"),
        ("SOURCE", True, "PHONE"),
        ("SOURCE", True, "WEBSITE"),
        ("USER", True, "EMAIL"),
    ]
    assert contact_sets[0]["retired_at"] == NOW
    assert contact_sets[1]["normalized_value"] == "+33611223344"
    assert contact_sets[2]["normalized_value"] == "https://example.fr/reservation"
    assert contact_sets[3]["normalized_value"] == "contact@example.fr"
    assert all(row["scope"] == "UNKNOWN" for row in contact_sets)
