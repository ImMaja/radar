"""API tests for private reference geography settings."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from radar.app import create_app
from radar.auth.contracts import AuthenticatedSession, IssuedSession
from radar.auth.rate_limit import LoginRateLimiter
from radar.config import Settings
from radar.geography.contracts import GeographySettings, ReferencePosition, StructuredAddress

DATABASE_URL = "postgresql+psycopg://radar:private@127.0.0.1:5432/radar"
NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)


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
        raise AssertionError("not used by geography tests")


def candidate(confirmed: bool = False) -> ReferencePosition:
    return ReferencePosition(
        id=uuid4(),
        input_address="12 rue Saint-Pierre 40100 Dax",
        normalized_label="12 Rue Saint Pierre 40100 Dax",
        structured_address=StructuredAddress(
            house_number="12",
            street="Rue Saint Pierre",
            postcode="40100",
            city="Dax",
            context="40, Landes, Nouvelle-Aquitaine",
        ),
        longitude=-1.051952,
        latitude=43.70884,
        municipality_code="40088",
        ban_id="40088_1750_00012",
        result_type="housenumber",
        score=0.9653,
        provider_name="Géoplateforme",
        provider_url="https://data.geopf.fr/geocodage/search",
        geocoded_at=NOW,
        confirmed_at=NOW if confirmed else None,
    )


class StubGeographyBackend:
    def __init__(self) -> None:
        self.proposal = candidate()
        self.state = GeographySettings(None, 50_000, 50_000, NOW)
        self.geocoded_address: str | None = None

    def geocode_reference(self, input_address: str) -> ReferencePosition:
        self.geocoded_address = input_address
        return self.proposal

    def get_settings(self) -> GeographySettings:
        return self.state

    def confirm_reference(self, candidate_id: UUID) -> GeographySettings:
        assert candidate_id == self.proposal.id
        confirmed = replace(self.proposal, confirmed_at=NOW)
        self.state = GeographySettings(confirmed, 50_000, 50_000, NOW)
        return self.state

    def update_radii(
        self,
        collection_radius_meters: int,
        search_radius_meters: int,
    ) -> GeographySettings:
        self.state = GeographySettings(
            self.state.reference_position,
            collection_radius_meters,
            search_radius_meters,
            NOW,
        )
        return self.state


def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(DATABASE_URL),
        public_origin="http://testserver",
    )


def client_and_backend() -> tuple[TestClient, StubGeographyBackend]:
    authentication = StubAuthenticationBackend()
    geography = StubGeographyBackend()
    app = create_app(
        settings(),
        ReadyProbe(),
        authentication,
        LoginRateLimiter(),
        geography,
    )
    client = TestClient(app)
    client.cookies.set("radar_session", "valid-session")
    client.cookies.set("radar_csrf", "valid-csrf")
    return client, geography


def mutation_headers() -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": "valid-csrf"}


def test_geography_settings_are_private_and_start_without_coverage() -> None:
    client, _ = client_and_backend()
    client.cookies.clear()

    anonymous = client.get("/api/v1/settings/geography")

    assert anonymous.status_code == 401

    client.cookies.set("radar_session", "valid-session")
    current = client.get("/api/v1/settings/geography")
    assert current.status_code == 200
    assert current.json()["reference_position"] is None
    assert current.json()["collection_radius_meters"] == 50_000
    assert current.json()["search_radius_meters"] == 50_000
    assert current.json()["coverage"] == [
        {
            "connector": "SIRENE",
            "status": "NOT_COLLECTED",
            "search_circle_covered": False,
        },
        {
            "connector": "DATATOURISME",
            "status": "NOT_COLLECTED",
            "search_circle_covered": False,
        },
    ]


def test_geocode_then_confirm_keeps_the_two_actions_distinct() -> None:
    client, backend = client_and_backend()

    proposed = client.post(
        "/api/v1/settings/geography/geocodings",
        json={"address": "  12 rue Saint-Pierre   40100 Dax "},
        headers=mutation_headers(),
    )

    assert proposed.status_code == 201
    assert proposed.json()["confirmed_at"] is None
    assert backend.geocoded_address == "12 rue Saint-Pierre 40100 Dax"
    assert backend.state.reference_position is None

    confirmed = client.post(
        "/api/v1/settings/geography/reference-position",
        json={"candidate_id": proposed.json()["id"]},
        headers=mutation_headers(),
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["reference_position"]["confirmed_at"] is not None


def test_radius_change_is_local_and_bounded() -> None:
    client, backend = client_and_backend()

    changed = client.patch(
        "/api/v1/settings/geography/radii",
        json={"collection_radius_meters": 50_000, "search_radius_meters": 30_000},
        headers=mutation_headers(),
    )

    assert changed.status_code == 200
    assert backend.state.search_radius_meters == 30_000
    assert backend.geocoded_address is None

    rejected = client.patch(
        "/api/v1/settings/geography/radii",
        json={"collection_radius_meters": 50_001, "search_radius_meters": 30_000},
        headers=mutation_headers(),
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "invalid_request"


def test_geography_mutations_require_csrf() -> None:
    client, _ = client_and_backend()

    response = client.post(
        "/api/v1/settings/geography/geocodings",
        json={"address": "12 rue Saint-Pierre 40100 Dax"},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "invalid_csrf_token"
