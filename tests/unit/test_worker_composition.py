"""Tests for provider registration in the standalone worker."""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from radar.config import Settings
from radar.persistence.database import Database
from radar.worker import build_runtime

DATABASE_URL = "postgresql+psycopg://radar:private@127.0.0.1:5432/radar"


def test_worker_keeps_sirene_disabled_without_the_monthly_file() -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(DATABASE_URL),
        sirene_api_key=SecretStr("secret"),
    )
    database = Database(settings.database_url)
    try:
        runtime = build_runtime(settings, database)
        assert runtime.executors == {}
    finally:
        database.close()


def test_worker_registers_sirene_with_complete_local_provenance(tmp_path: Path) -> None:
    geolocation_file = tmp_path / "sirene-geolocation.parquet"
    geolocation_file.write_bytes(b"fixture")
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(DATABASE_URL),
        sirene_api_key=SecretStr("secret"),
        sirene_geolocation_file=geolocation_file,
        sirene_geolocation_resource_identifier="2026-09",
        sirene_geolocation_resource_url="https://example.data.gouv.fr/file.parquet",
        sirene_geolocation_published_on="2026-09-01",
        sirene_geolocation_retrieved_at=datetime(2026, 9, 24, 12, tzinfo=UTC),
        sirene_geolocation_expected_sha1="a" * 40,
        sirene_geolocation_expected_size_bytes=7,
    )
    database = Database(settings.database_url)
    runtime = build_runtime(settings, database)
    try:
        assert tuple(runtime.executors) == ("SIRENE",)
    finally:
        runtime.close()
        database.close()


def test_worker_registers_datatourisme_without_sirene_file() -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(DATABASE_URL),
        datatourisme_api_key=SecretStr("datatourisme-test-secret"),
    )
    database = Database(settings.database_url)
    runtime = build_runtime(settings, database)
    try:
        assert tuple(runtime.executors) == ("DATATOURISME",)
        assert len(runtime.close_callbacks) == 1
    finally:
        runtime.close()
        database.close()


def test_worker_registers_both_configured_connectors(tmp_path: Path) -> None:
    geolocation_file = tmp_path / "sirene-geolocation.parquet"
    geolocation_file.write_bytes(b"fixture")
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(DATABASE_URL),
        sirene_api_key=SecretStr("sirene-test-secret"),
        sirene_geolocation_file=geolocation_file,
        sirene_geolocation_resource_identifier="2026-09",
        sirene_geolocation_resource_url="https://example.data.gouv.fr/file.parquet",
        sirene_geolocation_retrieved_at=datetime(2026, 9, 24, 12, tzinfo=UTC),
        datatourisme_api_key=SecretStr("datatourisme-test-secret"),
    )
    database = Database(settings.database_url)
    runtime = build_runtime(settings, database)
    try:
        assert tuple(runtime.executors) == ("SIRENE", "DATATOURISME")
    finally:
        runtime.close()
        database.close()
