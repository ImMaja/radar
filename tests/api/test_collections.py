"""API tests for private durable collection supervision."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from radar.app import create_app
from radar.auth.contracts import AuthenticatedSession, IssuedSession
from radar.auth.rate_limit import LoginRateLimiter
from radar.collections.contracts import (
    CollectionDashboard,
    CollectionJob,
    CollectionProgress,
    Connector,
    ConnectorCollectionStatus,
    EnqueuedCollection,
    ReferencePositionRequiredError,
)
from radar.config import Settings
from radar.geography.contracts import GeographySettings, ReferencePosition

DATABASE_URL = "postgresql+psycopg://radar:private@127.0.0.1:5432/radar"
NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


@dataclass(frozen=True)
class ReadyProbe:
    def is_ready(self) -> bool:
        return True


class StubAuthenticationBackend:
    def __init__(self) -> None:
        self.session = AuthenticatedSession(
            id=uuid4(),
            account_id=uuid4(),
            display_name="Radar",
            csrf_token_hash="unused",
        )

    def login(self, _password: str) -> IssuedSession | None:
        return None

    def authenticate(self, token: str) -> AuthenticatedSession | None:
        return self.session if token == "valid-session" else None

    def logout(self, _session_id: UUID) -> None:
        return None

    def csrf_is_valid(self, session: AuthenticatedSession, token: str) -> bool:
        return session.id == self.session.id and token == "valid-csrf"

    def change_password(
        self,
        _session: AuthenticatedSession,
        _current_password: str,
        _new_password: str,
        _confirmation: str,
    ) -> IssuedSession:
        raise AssertionError("not used by collection tests")


def collection_job(connector: Connector = "SIRENE") -> CollectionJob:
    return CollectionJob(
        id=uuid4(),
        cycle_id=uuid4(),
        connector=connector,
        trigger="MANUAL",
        state="WAITING",
        reference_label="12 Rue Saint Pierre 40100 Dax",
        longitude=-1.051952,
        latitude=43.70884,
        collection_radius_meters=50_000,
        created_at=NOW,
        available_at=NOW,
        started_at=None,
        finished_at=None,
        heartbeat_at=None,
        attempt_count=0,
        max_attempts=3,
        progress=CollectionProgress("waiting"),
        last_error=None,
    )


class StubCollectionBackend:
    def __init__(self) -> None:
        self.job = collection_job()
        self.requested: Connector | None = None
        self.has_reference = True

    def request_manual(self, connector: Connector) -> EnqueuedCollection:
        if not self.has_reference:
            raise ReferencePositionRequiredError
        self.requested = connector
        return EnqueuedCollection(self.job, created=True)

    def dashboard(self) -> CollectionDashboard:
        return CollectionDashboard(
            (
                ConnectorCollectionStatus("SIRENE", True, self.job, self.job, None, None),
                ConnectorCollectionStatus("DATATOURISME", True, None, None, None, None),
            )
        )


class UnusedGeographyBackend:
    def geocode_reference(self, _input_address: str) -> ReferencePosition:
        raise AssertionError("not used by collection tests")

    def get_settings(self) -> GeographySettings:
        raise AssertionError("not used by collection tests")

    def confirm_reference(self, _candidate_id: UUID) -> GeographySettings:
        raise AssertionError("not used by collection tests")

    def update_radii(
        self,
        _collection_radius_meters: int,
        _search_radius_meters: int,
    ) -> GeographySettings:
        raise AssertionError("not used by collection tests")


def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(DATABASE_URL),
        public_origin="http://testserver",
    )


def client_and_backend() -> tuple[TestClient, StubCollectionBackend]:
    authentication = StubAuthenticationBackend()
    collections = StubCollectionBackend()
    app = create_app(
        settings=settings(),
        readiness_probe=ReadyProbe(),
        authentication_backend=authentication,
        login_rate_limiter=LoginRateLimiter(),
        geography_backend=UnusedGeographyBackend(),
        collection_backend=collections,
    )
    client = TestClient(app)
    client.cookies.set("radar_session", "valid-session")
    client.cookies.set("radar_csrf", "valid-csrf")
    return client, collections


def mutation_headers() -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": "valid-csrf"}


def test_collection_dashboard_is_private_and_reports_both_connectors() -> None:
    client, _ = client_and_backend()
    client.cookies.clear()

    anonymous = client.get("/api/v1/collections")
    assert anonymous.status_code == 401

    client.cookies.set("radar_session", "valid-session")
    dashboard = client.get("/api/v1/collections")
    assert dashboard.status_code == 200
    assert [item["connector"] for item in dashboard.json()["connectors"]] == [
        "SIRENE",
        "DATATOURISME",
    ]
    assert dashboard.json()["connectors"][0]["active_job"]["state"] == "WAITING"


def test_manual_collection_requires_csrf_and_enqueues_without_running_provider_io() -> None:
    client, backend = client_and_backend()

    rejected = client.post("/api/v1/collections/SIRENE", json={})
    accepted = client.post(
        "/api/v1/collections/SIRENE",
        json={},
        headers=mutation_headers(),
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 202
    assert accepted.json()["created"] is True
    assert accepted.json()["job"]["state"] == "WAITING"
    assert backend.requested == "SIRENE"


def test_manual_collection_requires_a_confirmed_reference_position() -> None:
    client, backend = client_and_backend()
    backend.has_reference = False

    response = client.post(
        "/api/v1/collections/DATATOURISME",
        json={},
        headers=mutation_headers(),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "reference_position_required"
