"""Exercise private HTTP collection, the worker, and the local event catalogue."""

from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from radar import worker as worker_module
from radar.app import create_app
from radar.auth.passwords import PasswordManager
from radar.collections.worker import CollectionWorker
from radar.config import Settings
from radar.persistence.auth import SqlAlchemyAuthRepository
from radar.persistence.collections import SqlAlchemyCollectionRepository
from radar.persistence.database import Database
from radar.providers.datatourisme import PAGE_SIZE, DatatourismeClient

from .test_collections import confirm_position
from .test_datatourisme_worker import _event, _seed_metropolitan_boundary

pytestmark = pytest.mark.integration
ORIGIN = "http://testserver"
PASSWORD = "public integration-test password"


def _log_in(client: TestClient, database: Database) -> dict[str, str]:
    assert SqlAlchemyAuthRepository(database.engine).create_account(
        PasswordManager().hash(PASSWORD), "Radar", datetime.now(UTC)
    )
    response = client.post(
        "/api/v1/auth/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    token = client.cookies.get("radar_csrf")
    assert token is not None
    return {"Origin": ORIGIN, "X-CSRF-Token": token}


@pytest.mark.parametrize("api_key", [None, ""])
def test_web_keeps_datatourisme_unavailable_without_a_key(
    integration_database_url: str, api_key: str | None
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(integration_database_url),
        public_origin=ORIGIN,
        datatourisme_api_key=SecretStr(api_key) if api_key is not None else None,
    )
    database = Database(settings.database_url)
    try:
        with TestClient(create_app(settings)) as client:
            headers = _log_in(client, database)
            dashboard = client.get("/api/v1/collections")
            assert dashboard.status_code == 200
            assert all(not item["available"] for item in dashboard.json()["connectors"])
            refused = client.post("/api/v1/collections/DATATOURISME", json={}, headers=headers)
            assert refused.status_code == 409
            assert refused.json()["code"] == "connector_not_available"
    finally:
        database.close()


def test_web_queues_collects_reads_and_updates_a_recurring_event(
    integration_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    confirm_position(integration_database_url)
    _seed_metropolitan_boundary(integration_database_url)
    requests: list[httpx.Request] = []
    identifier = str(UUID(int=71))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        event = _event(identifier)
        if len(requests) > 1:
            event["takesPlaceAt"] = [
                {"startDate": "2027-07-12"},
                {"startDate": "2028-07-15", "endDate": "2028-07-17"},
            ]
        return httpx.Response(
            200,
            json={
                "objects": [event],
                "meta": {
                    "total": 1,
                    "page": 1,
                    "page_size": PAGE_SIZE,
                    "total_pages": 1,
                    "next": None,
                },
            },
            request=request,
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        worker_module,
        "DatatourismeClient",
        lambda api_key: DatatourismeClient(api_key, http_client),
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(integration_database_url),
        public_origin=ORIGIN,
        datatourisme_api_key=SecretStr("public-datatourisme-test-key"),
    )
    database = Database(settings.database_url)
    runtime = worker_module.build_runtime(settings, database)
    worker = CollectionWorker(
        SqlAlchemyCollectionRepository(database.engine), runtime.executors, "events-web-test"
    )
    try:
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/events").status_code == 401
            headers = _log_in(client, database)
            dashboard = client.get("/api/v1/collections").json()
            assert [item["available"] for item in dashboard["connectors"]] == [False, True]
            assert client.post("/api/v1/collections/DATATOURISME", json={}).status_code == 403

            queued = client.post("/api/v1/collections/DATATOURISME", json={}, headers=headers)
            duplicate = client.post("/api/v1/collections/DATATOURISME", json={}, headers=headers)
            assert queued.status_code == duplicate.status_code == 202
            assert queued.json()["job"]["state"] == "WAITING"
            assert duplicate.json()["created"] is False
            assert duplicate.json()["job"]["id"] == queued.json()["job"]["id"]
            assert requests == []

            assert worker.run_once() is True
            listed = client.get("/api/v1/events?max_distance_meters=30000").json()
            assert listed["total"] == 1
            event_id = listed["items"][0]["id"]
            detail_response = client.get(f"/api/v1/events/{event_id}")
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert len(detail["periods"]) == 1
            assert detail["organizer_name"] is None
            assert detail["declared_status"] == "UNKNOWN"
            assert detail["sources"][0]["code"] == "DATATOURISME_API"
            assert len(requests) == 1

            refreshed = client.post("/api/v1/collections/DATATOURISME", json={}, headers=headers)
            assert refreshed.status_code == 202
            assert refreshed.json()["created"] is True
            assert worker.run_once() is True
            updated_response = client.get(f"/api/v1/events/{event_id}")
            assert updated_response.status_code == 200
            updated = updated_response.json()
            assert [period["start_date"] for period in updated["periods"]] == [
                "2027-07-12",
                "2028-07-15",
            ]
            assert client.get("/api/v1/events").json()["total"] == 1
            assert client.get("/api/v1/events?category=Concert").json()["total"] == 0
            assert len(requests) == 2

            status = client.get("/api/v1/collections").json()["connectors"][1]
            assert status["latest_job"]["state"] == "SUCCEEDED"
            assert status["coverage"]["search_circle_covered"] is True
            with database.engine.connect() as connection:
                assert connection.execute(text("SELECT count(*) FROM event")).scalar_one() == 1
    finally:
        runtime.close()
        http_client.close()
        database.close()
