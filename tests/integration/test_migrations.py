"""Integration test for a fresh PostgreSQL/PostGIS schema."""

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from radar.persistence.database import Database
from radar.persistence.schema import EXPECTED_SCHEMA_REVISION

pytestmark = pytest.mark.integration


def test_migrations_enable_postgis_and_create_the_current_schema(
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
                        "('account', 'auth_session', 'reference_position', 'application_setting', "
                        "'collection_cycle', 'collection_job', 'collection_attempt', "
                        "'connector_coverage', 'dataset_release', 'commune_boundary', "
                        "'collection_source_run', 'collection_batch', 'collection_page', "
                        "'collection_cycle_commune', 'collection_reference_usage', "
                        "'data_source', 'external_identity', 'source_observation', "
                        "'collection_item', 'candidate_position', 'opportunity', "
                        "'organization', 'establishment', 'prospect', 'source_binding', "
                        "'source_sighting', 'field_lineage', 'location_assertion', "
                        "'contact_set', 'contact_point', 'sirene_known_status_check')"
                    )
                ).scalars()
            )
            municipality_indexes = set(
                connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename = 'commune_boundary'"
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
        "collection_cycle",
        "collection_job",
        "collection_attempt",
        "connector_coverage",
        "dataset_release",
        "commune_boundary",
        "collection_source_run",
        "collection_batch",
        "collection_page",
        "collection_cycle_commune",
        "collection_reference_usage",
        "data_source",
        "external_identity",
        "source_observation",
        "collection_item",
        "candidate_position",
        "opportunity",
        "organization",
        "establishment",
        "prospect",
        "source_binding",
        "source_sighting",
        "field_lineage",
        "location_assertion",
        "contact_set",
        "contact_point",
        "sirene_known_status_check",
    }
    assert "ix_commune_boundary_boundary" in municipality_indexes
    assert "ix_commune_boundary_boundary_geography" in municipality_indexes

    database = Database(SecretStr(database_url))
    try:
        assert database.is_ready() is True
    finally:
        database.close()
