"""Real PostgreSQL tests for the single account and session lifecycle."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from radar.auth.contracts import AccountAlreadyExistsError, InvalidCurrentPasswordError
from radar.auth.service import AuthService
from radar.persistence.auth import SqlAlchemyAuthRepository

PASSWORD = "une phrase secrète initiale"
NEW_PASSWORD = "une phrase secrète remplacée"

pytestmark = pytest.mark.integration


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


def test_account_sessions_password_rotation_and_admin_reset(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    clock = MutableClock(datetime(2026, 9, 11, 10, 0, tzinfo=UTC))
    service = AuthService(
        SqlAlchemyAuthRepository(engine),
        idle_timeout=timedelta(hours=12),
        absolute_timeout=timedelta(days=7),
        clock=clock,
    )
    try:
        service.create_account(PASSWORD, PASSWORD, "Food truck Radar")
        with pytest.raises(AccountAlreadyExistsError):
            service.create_account(PASSWORD, PASSWORD)

        first = service.login(PASSWORD)
        second = service.login(PASSWORD)
        assert first is not None
        assert second is not None
        assert service.authenticate(first.secrets.token) is not None
        assert service.authenticate(second.secrets.token) is not None

        with engine.connect() as connection:
            stored_tokens = connection.execute(
                text("SELECT token_hash, csrf_token_hash FROM auth_session")
            ).all()
        assert first.secrets.token not in {value for row in stored_tokens for value in row}
        assert first.secrets.csrf_token not in {value for row in stored_tokens for value in row}

        first_session = service.authenticate(first.secrets.token)
        assert first_session is not None
        assert service.csrf_is_valid(first_session, first.secrets.csrf_token) is True
        assert service.csrf_is_valid(first_session, "incorrect-csrf-token") is False
        with pytest.raises(InvalidCurrentPasswordError):
            service.change_password(
                first_session,
                "mot de passe actuel incorrect",
                NEW_PASSWORD,
                NEW_PASSWORD,
            )
        replacement = service.change_password(
            first_session,
            PASSWORD,
            NEW_PASSWORD,
            NEW_PASSWORD,
        )

        assert service.authenticate(first.secrets.token) is None
        assert service.authenticate(second.secrets.token) is None
        assert service.authenticate(replacement.secrets.token) is not None
        assert service.login(PASSWORD) is None
        assert service.login(NEW_PASSWORD) is not None

        service.reset_password(PASSWORD, PASSWORD)
        assert service.authenticate(replacement.secrets.token) is None
        assert service.login(NEW_PASSWORD) is None
        final_session = service.login(PASSWORD)
        assert final_session is not None
        service.logout(final_session.current.id)
        assert service.authenticate(final_session.secrets.token) is None
    finally:
        engine.dispose()


def test_idle_expiration_is_enforced_server_side(integration_database_url: str) -> None:
    engine = create_engine(integration_database_url)
    clock = MutableClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
    service = AuthService(
        SqlAlchemyAuthRepository(engine),
        idle_timeout=timedelta(hours=12),
        absolute_timeout=timedelta(days=7),
        clock=clock,
    )
    try:
        issued = service.login(PASSWORD)
        assert issued is not None
        clock.current += timedelta(hours=12, seconds=1)
        assert service.authenticate(issued.secrets.token) is None
    finally:
        engine.dispose()


def test_absolute_expiration_is_not_extended_by_activity(integration_database_url: str) -> None:
    engine = create_engine(integration_database_url)
    clock = MutableClock(datetime(2026, 9, 13, 10, 0, tzinfo=UTC))
    service = AuthService(
        SqlAlchemyAuthRepository(engine),
        idle_timeout=timedelta(hours=12),
        absolute_timeout=timedelta(days=7),
        clock=clock,
    )
    try:
        issued = service.login(PASSWORD)
        assert issued is not None
        for _ in range(15):
            clock.current += timedelta(hours=11)
            assert service.authenticate(issued.secrets.token) is not None
        clock.current += timedelta(hours=4)
        assert service.authenticate(issued.secrets.token) is None
    finally:
        engine.dispose()
