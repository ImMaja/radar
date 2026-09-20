"""Shared PostgreSQL/PostGIS setup for integration tests."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from radar.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def integration_database_url() -> Iterator[str]:
    """Rebuild the explicitly named disposable database for every integration test."""

    database_url = os.getenv("RADAR_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("RADAR_TEST_DATABASE_URL is not configured")
    if make_url(database_url).database != "radar_test":
        pytest.fail("integration tests require the dedicated radar_test database")

    previous_url = os.environ.get("RADAR_DATABASE_URL")
    os.environ["RADAR_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    try:
        yield database_url
    finally:
        if previous_url is None:
            os.environ.pop("RADAR_DATABASE_URL", None)
        else:
            os.environ["RADAR_DATABASE_URL"] = previous_url
        get_settings.cache_clear()
