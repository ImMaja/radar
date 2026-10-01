"""Private HTTP tests for bounded event catalogue reads."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from radar.app import create_app
from radar.config import Settings
from radar.events.catalog import (
    EventContact,
    EventDetail,
    EventNotFoundError,
    EventPage,
    EventPeriod,
    EventReferencePositionRequiredError,
    EventSearch,
    EventSource,
    EventSummary,
)

from .test_prospects import ReadyProbe, StubAuthenticationBackend, UnusedGeographyBackend

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
EVENT_ID = uuid4()
DATABASE_URL = "postgresql+psycopg://radar:private@127.0.0.1:5432/radar"


def _summary() -> EventSummary:
    return EventSummary(
        id=EVENT_ID,
        title="Fête de Dax",
        types=("Festival",),
        organizer_name=None,
        declared_status="UNKNOWN",
        temporal_state="UPCOMING",
        next_start_at=datetime(2027, 7, 12, tzinfo=UTC),
        full_address="Place de la Mairie, 40100 Dax",
        municipality="Dax",
        distance_meters=123.4,
        has_contact=True,
        last_observed_at=NOW,
    )


class StubEventBackend:
    def __init__(self) -> None:
        self.received_query: EventSearch | None = None
        self.has_reference = True

    def search(self, query: EventSearch) -> EventPage:
        if not self.has_reference:
            raise EventReferencePositionRequiredError
        self.received_query = query
        return EventPage((_summary(),), 1, query.limit, query.offset, 30_000)

    def get(self, event_id: UUID) -> EventDetail:
        if event_id != EVENT_ID:
            raise EventNotFoundError
        return EventDetail(
            summary=_summary(),
            description="Fête locale publique.",
            source_uri="https://data.datatourisme.fr/event",
            period_layer="SOURCE",
            periods=(
                EventPeriod(
                    date(2027, 7, 12), date(2027, 7, 13), None, None, "DATE_ONLY", "periods[0]"
                ),
            ),
            longitude=-1.051952,
            latitude=43.70884,
            contacts=(
                EventContact("PHONE", "05 58 12 34 56", "UNKNOWN", "Accueil", "contacts[0]"),
            ),
            sources=(
                EventSource(
                    "DATATOURISME_API",
                    "API DATAtourisme v1",
                    "DATAtourisme",
                    "CURRENT",
                    NOW,
                    NOW,
                    NOW,
                    NOW,
                ),
            ),
        )


def _client() -> tuple[TestClient, StubEventBackend]:
    backend = StubEventBackend()
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(DATABASE_URL),
        public_origin="http://testserver",
    )
    app = create_app(
        settings=settings,
        readiness_probe=ReadyProbe(),
        authentication_backend=StubAuthenticationBackend(),
        geography_backend=UnusedGeographyBackend(),
        event_backend=backend,
    )
    client = TestClient(app)
    client.cookies.set("radar_session", "valid-session")
    return client, backend


def test_event_list_requires_authentication_and_passes_validated_filters() -> None:
    client, backend = _client()
    client.cookies.clear()
    assert client.get("/api/v1/events").status_code == 401
    client.cookies.set("radar_session", "valid-session")

    response = client.get(
        "/api/v1/events",
        params={
            "q": "  Dax  ",
            "max_distance_meters": 30_000,
            "date_from": "2027-07-12",
            "date_to": "2027-07-13",
            "category": " Festival ",
            "organizer": " Comité des fêtes ",
            "has_contact": "true",
            "declared_status": "UNKNOWN",
            "sort": "distance",
            "direction": "desc",
            "limit": 10,
            "offset": 20,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["title"] == "Fête de Dax"
    assert backend.received_query == EventSearch(
        text="Dax",
        max_distance_meters=30_000,
        date_from=date(2027, 7, 12),
        date_to=date(2027, 7, 13),
        category="Festival",
        organizer="Comité des fêtes",
        has_contact=True,
        declared_status="UNKNOWN",
        sort="distance",
        direction="desc",
        limit=10,
        offset=20,
    )


def test_event_list_rejects_inverted_dates_and_excessive_radius() -> None:
    client, _backend = _client()
    assert (
        client.get(
            "/api/v1/events", params={"date_from": "2027-08-01", "date_to": "2027-07-01"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/events", params={"max_distance_meters": 50_001}).status_code == 422


def test_event_detail_exposes_effective_periods_contacts_and_sources() -> None:
    client, backend = _client()
    response = client.get(f"/api/v1/events/{EVENT_ID}")
    assert response.status_code == 200
    assert response.json()["periods"][0]["start_date"] == "2027-07-12"
    assert response.json()["contacts"][0]["scope"] == "UNKNOWN"
    assert response.json()["sources"][0]["code"] == "DATATOURISME_API"
    assert client.get(f"/api/v1/events/{uuid4()}").status_code == 404
    backend.has_reference = False
    assert client.get("/api/v1/events").status_code == 409
