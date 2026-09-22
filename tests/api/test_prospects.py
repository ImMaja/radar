"""API tests for private local prospect catalogue reads."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from radar.app import create_app
from radar.auth.contracts import AuthenticatedSession, IssuedSession
from radar.config import Settings
from radar.geography.contracts import GeographySettings, ReferencePosition
from radar.prospects.catalog import (
    ProspectAddress,
    ProspectDetail,
    ProspectNotFoundError,
    ProspectPage,
    ProspectReferencePositionRequiredError,
    ProspectSearch,
    ProspectSource,
    ProspectSummary,
)

DATABASE_URL = "postgresql+psycopg://radar:private@127.0.0.1:5432/radar"
NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
PROSPECT_ID = uuid4()


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

    def csrf_is_valid(self, _session: AuthenticatedSession, _token: str) -> bool:
        return False

    def change_password(
        self,
        _session: AuthenticatedSession,
        _current_password: str,
        _new_password: str,
        _confirmation: str,
    ) -> IssuedSession:
        raise AssertionError("not used by prospect tests")


class UnusedGeographyBackend:
    def geocode_reference(self, _input_address: str) -> ReferencePosition:
        raise AssertionError("not used by prospect tests")

    def get_settings(self) -> GeographySettings:
        raise AssertionError("not used by prospect tests")

    def confirm_reference(self, _candidate_id: UUID) -> GeographySettings:
        raise AssertionError("not used by prospect tests")

    def update_radii(
        self,
        _collection_radius_meters: int,
        _search_radius_meters: int,
    ) -> GeographySettings:
        raise AssertionError("not used by prospect tests")


def summary() -> ProspectSummary:
    return ProspectSummary(
        id=PROSPECT_ID,
        display_name="Atelier public",
        organization_type="UNKNOWN",
        activity_code="10.71C",
        activity_nomenclature="NAFRev2",
        activity_label=None,
        employee_band="12",
        employee_year=2024,
        employee_scope="LOCAL",
        address=ProspectAddress(
            full_address="12 RUE SAINT PIERRE 40100 DAX",
            street_number="12",
            repetition_index=None,
            street_type="RUE",
            street_label="SAINT PIERRE",
            address_complement=None,
            postcode="40100",
            municipality="DAX",
            municipality_code="40088",
        ),
        distance_meters=125.4,
        location_status="located",
        location_precision="UNKNOWN",
        last_observed_at=NOW,
    )


class StubProspectBackend:
    def __init__(self) -> None:
        self.received_query: ProspectSearch | None = None
        self.has_reference_position = True

    def search(self, query: ProspectSearch) -> ProspectPage:
        if not self.has_reference_position:
            raise ProspectReferencePositionRequiredError
        self.received_query = query
        return ProspectPage((summary(),), 1, query.limit, query.offset, 30_000)

    def get(self, prospect_id: UUID) -> ProspectDetail:
        if prospect_id != PROSPECT_ID:
            raise ProspectNotFoundError
        return ProspectDetail(
            summary=summary(),
            description=None,
            siret="12345678901234",
            siren="123456789",
            legal_name="Société exemple",
            usual_name=None,
            legal_category="5710",
            is_head_office=False,
            eligibility="ELIGIBLE",
            eligibility_reason="SIRENE_FULL_PUBLIC_DIFFUSION",
            established_on=date(2020, 1, 2),
            current_period_started_on=date(2024, 3, 4),
            longitude=-1.051,
            latitude=43.708,
            location_origin="SIRENE_API",
            location_quality_code=None,
            location_match_score=None,
            first_observed_at=NOW,
            sources=(
                ProspectSource(
                    code="SIRENE_API",
                    name="API Sirene 3.11",
                    authority="INSEE",
                    producer_name="INSEE",
                    state="CURRENT",
                    first_observed_at=NOW,
                    last_observed_at=NOW,
                    retrieved_at=NOW,
                    source_updated_at=NOW,
                ),
            ),
        )


def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(DATABASE_URL),
        public_origin="http://testserver",
    )


def client_and_backend() -> tuple[TestClient, StubProspectBackend]:
    prospects = StubProspectBackend()
    app = create_app(
        settings=settings(),
        readiness_probe=ReadyProbe(),
        authentication_backend=StubAuthenticationBackend(),
        geography_backend=UnusedGeographyBackend(),
        prospect_backend=prospects,
    )
    client = TestClient(app)
    client.cookies.set("radar_session", "valid-session")
    return client, prospects


def test_prospect_list_is_private_and_passes_only_validated_local_filters() -> None:
    client, backend = client_and_backend()
    client.cookies.clear()

    anonymous = client.get("/api/v1/prospects")
    assert anonymous.status_code == 401

    client.cookies.set("radar_session", "valid-session")
    response = client.get(
        "/api/v1/prospects",
        params={
            "q": "  Dax  ",
            "max_distance_meters": 30_000,
            "organization_type": "unknown",
            "activity_code": "10.71c",
            "employee_band": "12",
            "sort": "name",
            "direction": "desc",
            "limit": 10,
            "offset": 20,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["applied_radius_meters"] == 30_000
    assert response.json()["items"][0]["display_name"] == "Atelier public"
    assert backend.received_query == ProspectSearch(
        text="Dax",
        max_distance_meters=30_000,
        organization_type="UNKNOWN",
        activity_code="10.71C",
        employee_band="12",
        sort="name",
        direction="desc",
        limit=10,
        offset=20,
    )


def test_prospect_list_rejects_unbounded_or_unknown_query_options() -> None:
    client, backend = client_and_backend()

    too_large = client.get("/api/v1/prospects", params={"limit": 101})
    unknown = client.get("/api/v1/prospects", params={"status": "contacted"})

    assert too_large.status_code == 422
    assert unknown.status_code == 422
    assert backend.received_query is None


def test_prospect_list_requires_a_confirmed_reference_position() -> None:
    client, backend = client_and_backend()
    backend.has_reference_position = False

    response = client.get("/api/v1/prospects")

    assert response.status_code == 409
    assert response.json()["code"] == "reference_position_required"


def test_prospect_detail_exposes_business_identity_and_provenance() -> None:
    client, _ = client_and_backend()

    response = client.get(f"/api/v1/prospects/{PROSPECT_ID}")

    assert response.status_code == 200
    assert response.json()["siret"] == "12345678901234"
    assert response.json()["address"]["municipality"] == "DAX"
    assert response.json()["sources"][0]["code"] == "SIRENE_API"


def test_unknown_prospect_returns_stable_not_found_error() -> None:
    client, _ = client_and_backend()

    response = client.get(f"/api/v1/prospects/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "prospect_not_found"
