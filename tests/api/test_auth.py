"""API tests for cookies, access control, CSRF and login throttling."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from radar.app import create_app
from radar.auth.contracts import (
    AuthenticatedSession,
    InvalidCurrentPasswordError,
    IssuedSession,
    SessionSecrets,
)
from radar.auth.rate_limit import LoginRateLimiter
from radar.config import Settings

DATABASE_URL = "postgresql+psycopg://radar:private@127.0.0.1:5432/radar"
PASSWORD = "une phrase secrète assez longue"


@dataclass(frozen=True)
class ReadyProbe:
    def is_ready(self) -> bool:
        return True


class StubAuthenticationBackend:
    """Predictable web boundary that never persists test browser secrets."""

    def __init__(self) -> None:
        self.session_id = uuid4()
        self.valid_token = "valid-session-token"
        self.csrf_token = "valid-csrf-token"
        self.logged_out: UUID | None = None

    def issued(self, token: str | None = None) -> IssuedSession:
        session_token = token or self.valid_token
        return IssuedSession(
            current=AuthenticatedSession(
                id=self.session_id,
                account_id=uuid4(),
                display_name="Radar",
                csrf_token_hash="stubbed",
            ),
            secrets=SessionSecrets(
                token=session_token,
                token_hash="not-used",
                csrf_token=self.csrf_token,
                csrf_token_hash="not-used",
            ),
        )

    def login(self, password: str) -> IssuedSession | None:
        return self.issued() if password == PASSWORD else None

    def authenticate(self, token: str) -> AuthenticatedSession | None:
        if token != self.valid_token or self.logged_out is not None:
            return None
        return self.issued().current

    def logout(self, session_id: UUID) -> None:
        self.logged_out = session_id

    def csrf_is_valid(self, session: AuthenticatedSession, token: str) -> bool:
        return session.id == self.session_id and token == self.csrf_token

    def change_password(
        self,
        session: AuthenticatedSession,
        current_password: str,
        new_password: str,
        confirmation: str,
    ) -> IssuedSession:
        if current_password != PASSWORD:
            raise InvalidCurrentPasswordError
        assert session.id == self.session_id
        assert new_password == confirmation
        self.valid_token = "rotated-session-token"
        return self.issued(self.valid_token)


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(DATABASE_URL),
        public_origin="http://testserver",
    )


def client_and_backend() -> tuple[TestClient, StubAuthenticationBackend]:
    backend = StubAuthenticationBackend()
    app = create_app(
        build_settings(),
        ReadyProbe(),
        backend,
        LoginRateLimiter(),
    )
    return TestClient(app), backend


def login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"password": PASSWORD},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200


def mutation_headers(client: TestClient) -> dict[str, str]:
    csrf_token = client.cookies.get("radar_csrf")
    assert csrf_token is not None
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf_token}


def test_login_issues_hardened_non_persistent_cookies() -> None:
    client, _ = client_and_backend()

    response = client.post(
        "/api/v1/auth/login",
        json={"password": PASSWORD},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if value.startswith("radar_session="))
    csrf_cookie = next(value for value in cookies if value.startswith("radar_csrf="))
    assert "HttpOnly" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=strict" in session_cookie
    assert "Max-Age" not in session_cookie
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.json() == {"authenticated": True, "display_name": "Radar"}


def test_production_cookies_use_secure_host_prefixes() -> None:
    backend = StubAuthenticationBackend()
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url=SecretStr(DATABASE_URL),
        public_origin="https://radar.example",
    )
    client = TestClient(
        create_app(settings, ReadyProbe(), backend, LoginRateLimiter()),
        base_url="https://radar.example",
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"password": PASSWORD},
        headers={"Origin": "https://radar.example"},
    )

    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if value.startswith("__Host-radar_session="))
    csrf_cookie = next(value for value in cookies if value.startswith("__Host-radar_csrf="))
    assert "Secure" in session_cookie
    assert "HttpOnly" in session_cookie
    assert "Secure" in csrf_cookie
    assert "Domain=" not in session_cookie


def test_private_session_refuses_anonymous_or_unknown_tokens() -> None:
    client, _ = client_and_backend()

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_login_rejects_foreign_origin_before_checking_credentials() -> None:
    client, _ = client_and_backend()

    response = client.post(
        "/api/v1/auth/login",
        json={"password": PASSWORD},
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "invalid_origin"
    assert "password" not in response.text.lower()


def test_validation_error_never_echoes_a_submitted_password() -> None:
    client, _ = client_and_backend()
    submitted_password = "secret-value-that-must-not-be-echoed-" * 10

    response = client.post(
        "/api/v1/auth/login",
        json={"password": submitted_password},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert submitted_password not in response.text


def test_login_limits_the_sixth_failed_attempt_per_direct_client() -> None:
    client, _ = client_and_backend()

    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"password": "incorrect mais de longueur valide"},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 401

    response = client.post(
        "/api/v1/auth/login",
        json={"password": "incorrect mais de longueur valide"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 429
    assert response.json()["code"] == "login_rate_limited"
    assert int(response.headers["Retry-After"]) >= 1


def test_logout_requires_csrf_then_revokes_session_and_cookies() -> None:
    client, backend = client_and_backend()
    login(client)

    rejected = client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"Origin": "http://testserver"},
    )
    accepted = client.post(
        "/api/v1/auth/logout",
        json={},
        headers=mutation_headers(client),
    )

    assert rejected.status_code == 403
    assert rejected.json()["code"] == "invalid_csrf_token"
    assert accepted.status_code == 204
    assert backend.logged_out == backend.session_id
    assert client.cookies.get("radar_session") is None
    assert client.cookies.get("radar_csrf") is None


def test_password_change_requires_current_password_and_rotates_session() -> None:
    client, backend = client_and_backend()
    login(client)
    headers = mutation_headers(client)

    rejected = client.post(
        "/api/v1/auth/password",
        json={
            "current_password": "incorrect mais de longueur valide",
            "new_password": "une nouvelle phrase secrète valide",
            "confirmation": "une nouvelle phrase secrète valide",
        },
        headers=headers,
    )
    accepted = client.post(
        "/api/v1/auth/password",
        json={
            "current_password": PASSWORD,
            "new_password": "une nouvelle phrase secrète valide",
            "confirmation": "une nouvelle phrase secrète valide",
        },
        headers=headers,
    )

    assert rejected.status_code == 400
    assert rejected.json()["code"] == "invalid_current_password"
    assert accepted.status_code == 200
    assert client.cookies.get("radar_session") == "rotated-session-token"
    assert backend.valid_token == "rotated-session-token"
