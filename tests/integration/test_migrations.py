"""Integration test for a fresh PostgreSQL/PostGIS schema."""

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from radar.persistence.database import Database
from radar.persistence.schema import EXPECTED_SCHEMA_REVISION

pytestmark = pytest.mark.integration


def test_migrations_enable_postgis_authentication_and_geographic_settings(
    integration_database_url: str,
) -> None:
    database_url = integration_database_url
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            has_postgis = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')")
            ).scalar_one()
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            tables = set(
                connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' AND tablename IN "
                        "('account', 'auth_session', 'reference_position', 'application_setting')"
                    )
                ).scalars()
            )
    finally:
        engine.dispose()

    assert has_postgis is True
    assert revision == EXPECTED_SCHEMA_REVISION
    assert tables == {
        "account",
        "auth_session",
        "reference_position",
        "application_setting",
    }

    database = Database(SecretStr(database_url))
    try:
        assert database.is_ready() is True
    finally:
        database.close()
