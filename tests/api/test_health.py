"""API tests for non-sensitive health endpoints."""

from dataclasses import dataclass

from fastapi.testclient import TestClient
from pydantic import SecretStr

from radar.app import create_app
from radar.config import Environment, Settings

DATABASE_URL = "postgresql+psycopg://radar:private@127.0.0.1:5432/radar"


@dataclass(frozen=True)
class StubReadinessProbe:
    ready: bool

    def is_ready(self) -> bool:
        return self.ready


def settings(environment: Environment = "test") -> Settings:
    return Settings(
        _env_file=None,
        environment=environment,
        database_url=SecretStr(DATABASE_URL),
        public_origin=(
            "https://radar.example" if environment == "production" else "http://testserver"
        ),
    )


def test_liveness_does_not_depend_on_database_readiness() -> None:
    app = create_app(settings(), StubReadinessProbe(ready=False))

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_hides_failure_details() -> None:
    app = create_app(settings(), StubReadinessProbe(ready=False))

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "database" not in response.text.lower()


def test_readiness_succeeds_when_local_dependencies_are_ready() -> None:
    app = create_app(settings(), StubReadinessProbe(ready=True))

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_interactive_documentation_is_disabled_in_production() -> None:
    app = create_app(settings("production"), StubReadinessProbe(ready=True))

    with TestClient(app) as client:
        docs_response = client.get("/docs")
        schema_response = client.get("/openapi.json")

    assert docs_response.status_code == 404
    assert schema_response.status_code == 404
