"""Local event catalogue filters and effective-calendar precedence."""

from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from radar.events.catalog import EventNotFoundError, EventSearch
from radar.events.contracts import EventContactCandidate, EventPeriodCandidate
from radar.events.projection import EventProjectionService
from radar.events.staging import EventCandidatePageStager
from radar.persistence.datatourisme_projection import SqlAlchemyEventProjectionRepository
from radar.persistence.datatourisme_staging import SqlAlchemyEventCandidateStagingRepository
from radar.persistence.event_catalog import SqlAlchemyEventCatalogRepository

from .test_collections import confirm_position
from .test_datatourisme_projection import _finish_source, _page
from .test_datatourisme_staging import NOW, candidate, seed_running_collection

pytestmark = pytest.mark.integration


def test_searches_visible_events_and_reads_periods_contacts_and_freshness(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    confirm_position(integration_database_url)
    summer = replace(
        candidate(
            301,
            periods=(
                EventPeriodCandidate("2026-09-01", None, None, None),
                EventPeriodCandidate("2027-07-12", "2027-07-13", None, None),
            ),
        ),
        types=("Festival",),
        contacts=(EventContactCandidate("GENERAL", "Accueil", ("05 58 12 34 56",), ()),),
    )
    autumn = replace(
        candidate(
            302, longitude=-1.04, periods=(EventPeriodCandidate("2026-11-05", None, None, None),)
        ),
        types=("Concert",),
    )
    old = candidate(303, periods=(EventPeriodCandidate("2026-01-01", None, None, None),))
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    projector = EventProjectionService(
        SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
    )
    catalog = SqlAlchemyEventCatalogRepository(engine, clock=lambda: NOW)
    try:
        stager.handle(reservation, batch_id, _page(1, (summer, autumn, old)))
        _finish_source(engine, batch_id, reservation.cycle_id)
        assert projector.project(reservation).created_count == 2

        page = catalog.search(EventSearch())
        assert page.total == 2
        assert [item.title for item in page.items] == ["Événement 302", "Événement 301"]
        assert all(item.temporal_state == "UPCOMING" for item in page.items)
        assert page.applied_radius_meters == 50_000
        distance_page = catalog.search(
            EventSearch(sort="distance", direction="desc", limit=1, offset=0)
        )
        assert distance_page.total == 2
        assert [item.title for item in distance_page.items] == ["Événement 302"]
        assert (
            catalog.search(
                EventSearch(date_from=date(2026, 11, 5), date_to=date(2026, 11, 5))
            ).total
            == 1
        )

        summer_page = catalog.search(
            EventSearch(
                text="Dax",
                date_from=date(2027, 7, 13),
                date_to=date(2027, 7, 13),
                category="Festival",
                has_contact=True,
                max_distance_meters=500,
            )
        )
        assert summer_page.total == 1
        assert summer_page.items[0].title == "Événement 301"
        assert summer_page.items[0].has_contact is True
        assert catalog.search(EventSearch(category="Concert", max_distance_meters=500)).total == 0

        detail = catalog.get(summer_page.items[0].id)
        assert detail.summary.municipality == "Dax"
        assert detail.period_layer == "SOURCE"
        assert [period.start_date for period in detail.periods] == [
            date(2026, 9, 1),
            date(2027, 7, 12),
        ]
        assert [contact.type for contact in detail.contacts] == ["PHONE"]
        assert detail.contacts[0].scope == "UNKNOWN"
        assert detail.sources[0].code == "DATATOURISME_API"
        assert detail.sources[0].retrieved_at == NOW
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE event SET organizer_name = 'Comité des fêtes' WHERE id = :id"),
                {"id": detail.summary.id},
            )
        assert catalog.search(EventSearch(organizer="Comité", has_contact=True)).total == 1
    finally:
        engine.dispose()


def test_cancelled_hidden_and_user_past_periods_are_not_in_the_ordinary_list(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    confirm_position(integration_database_url)
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine), clock=lambda: NOW
    )
    projector = EventProjectionService(
        SqlAlchemyEventProjectionRepository(engine), clock=lambda: NOW
    )
    catalog = SqlAlchemyEventCatalogRepository(engine, clock=lambda: NOW)
    try:
        stager.handle(reservation, batch_id, _page(1, (candidate(311), candidate(312))))
        _finish_source(engine, batch_id, reservation.cycle_id)
        assert projector.project(reservation).created_count == 2
        with engine.begin() as connection:
            first_id = connection.execute(
                text("SELECT id FROM event WHERE source_title = 'Événement 311'")
            ).scalar_one()
            second_id = connection.execute(
                text("SELECT id FROM event WHERE source_title = 'Événement 312'")
            ).scalar_one()
            connection.execute(
                text("UPDATE event SET declared_status = 'CANCELLED' WHERE id = :id"),
                {"id": second_id},
            )
        assert catalog.search(EventSearch()).total == 1
        assert catalog.search(EventSearch(declared_status="CANCELLED")).total == 1
        assert catalog.get(second_id).summary.declared_status == "CANCELLED"

        user_set_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO event_period_set (id, event_id, layer, is_current, created_at)
                    VALUES (:id, :event_id, 'USER', TRUE, :now)
                    """
                ),
                {"id": user_set_id, "event_id": first_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO event_period (
                        id, period_set_id, display_order, start_date, end_date,
                        interpretation_timezone, precision, source_path, created_at
                    ) VALUES (
                        :id, :period_set_id, 0, '2025-01-01', '2025-01-01',
                        'Europe/Paris', 'DATE_ONLY', 'user', :now
                    )
                    """
                ),
                {"id": uuid4(), "period_set_id": user_set_id, "now": NOW},
            )
        assert catalog.search(EventSearch()).total == 0
        with pytest.raises(EventNotFoundError):
            catalog.get(first_id)

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE opportunity SET hidden_at = :now WHERE id = :id"),
                {"id": second_id, "now": NOW},
            )
        assert catalog.search(EventSearch(declared_status="CANCELLED")).total == 0
        with pytest.raises(EventNotFoundError):
            catalog.get(second_id)
    finally:
        engine.dispose()
