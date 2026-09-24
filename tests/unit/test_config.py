"""Tests for typed application settings."""

from pathlib import Path

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


def test_sirene_connector_requires_complete_file_provenance() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=SecretStr(DATABASE_URL),
            sirene_geolocation_resource_identifier="2026-09",
        )


def test_sirene_connector_is_enabled_only_with_a_readable_release(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sirene-geolocation.parquet"
    path.write_bytes(b"fixture")
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(DATABASE_URL),
        sirene_api_key=SecretStr("secret"),
        sirene_geolocation_file=path,
        sirene_geolocation_resource_identifier="2026-09",
        sirene_geolocation_resource_url="https://example.data.gouv.fr/file.parquet",
        sirene_geolocation_retrieved_at="2026-09-24T12:00:00+02:00",
    )

    assert settings.sirene_connector_configured is True
