"""Tests for typed application settings."""

import pytest
from pydantic import SecretStr, ValidationError

from radar.config import Settings

DATABASE_URL = "postgresql+psycopg://radar:private@127.0.0.1:5432/radar"


def test_settings_accept_explicit_psycopg_url_without_exposing_it() -> None:
    settings = Settings(_env_file=None, database_url=SecretStr(DATABASE_URL))

    assert settings.database_url.get_secret_value() == DATABASE_URL
    assert DATABASE_URL not in repr(settings)


def test_settings_reject_ambiguous_postgresql_driver() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=SecretStr("postgresql://radar:private@127.0.0.1/radar"),
        )


def test_production_requires_an_exact_https_origin() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            database_url=SecretStr(DATABASE_URL),
            public_origin="http://radar.example",
        )


def test_session_idle_timeout_cannot_exceed_absolute_timeout() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=SecretStr(DATABASE_URL),
            session_idle_seconds=601,
            session_absolute_seconds=600,
        )
