"""Run the DATAtourisme pipeline through the real durable worker."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from radar import worker as worker_module
from radar.collections.service import CollectionService
from radar.collections.worker import CollectionWorker
from radar.config import Settings
from radar.persistence.collections import SqlAlchemyCollectionRepository
from radar.persistence.database import Database
from radar.providers.datatourisme import API_KEY_HEADER, PAGE_SIZE, DatatourismeClient

from .test_collections import confirm_position

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
API_KEY = "datatourisme-worker-test-key"


def _event(identifier: str, *, uri: str | None = None) -> dict[str, object]:
    return {
        "uuid": identifier,
        "uri": uri or f"https://data.datatourisme.fr/{identifier}",
        "label": {"@fr": "Fête locale de Dax"},
        "type": ["Festival"],
        "isLocatedAt": [{"geo": {"longitude": -1.051952, "latitude": 43.70884}}],
        "takesPlaceAt": [{"startDate": "2027-07-12"}],
    }


def _seed_metropolitan_boundary(database_url: str) -> None:
    engine = create_engine(database_url)
    release_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO dataset_release (
                        id, source_name, dataset_code, resource_identifier,
                        resource_url, published_on, retrieved_at, file_size_bytes,
                        digest_algorithm, file_digest, expected_schema, status,
                        license_name, metadata, created_at, updated_at
                    ) VALUES (
                        :id, 'data.gouv.fr', 'contours-administratifs-communes-100m',
                        'worker-test-boundary', 'https://example.test/communes.geojson',
                        :published_on, :now, 1, 'SHA-256', :digest,
                        '{}'::jsonb, 'ACTIVE', 'Licence Ouverte 2.0',
                        '{}'::jsonb, :now, :now
                    )
                    """
                ),
                {
                    "id": release_id,
                    "published_on": date(2026, 1, 1),
                    "now": NOW,
                    "digest": "d" * 64,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO commune_boundary (
                        dataset_release_id, municipality_code, official_name,
                        boundary, is_metropolitan_france
                    ) VALUES (
                        :release_id, '40088', 'Zone métropolitaine de test',
                        ST_Multi(ST_MakeEnvelope(-2.0, 43.0, -0.3, 44.0, 4326)),
                        TRUE
                    )
                    """
                ),
                {"release_id": release_id},
            )
    finally:
        engine.dispose()


def test_worker_collects_and_recollects_one_event_without_duplication(
    integration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    confirm_position(integration_database_url)
    _seed_metropolitan_boundary(integration_database_url)
    requests: list[httpx.Request] = []
    identifier = str(UUID(int=52))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "objects": [_event(identifier)],
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
        database_url=SecretStr(integration_database_url),
        datatourisme_api_key=SecretStr(API_KEY),
    )
    database = Database(settings.database_url)
    runtime = worker_module.build_runtime(settings, database)
    repository = SqlAlchemyCollectionRepository(database.engine)
    collections = CollectionService(
        repository,
        enabled_connectors=frozenset(("DATATOURISME",)),
        clock=lambda: NOW,
    )
    worker = CollectionWorker(repository, runtime.executors, "worker-events", clock=lambda: NOW)
    try:
        first = collections.request_manual("DATATOURISME")
        assert first.created is True
        assert worker.run_once() is True
        second = collections.request_manual("DATATOURISME")
        assert second.created is True
        assert worker.run_once() is True

        dashboard = repository.dashboard().connectors[1]
        assert dashboard.latest_job is not None
        assert dashboard.latest_job.state == "SUCCEEDED"
        assert dashboard.coverage is not None
        assert dashboard.coverage.search_circle_covered is True

        with database.engine.connect() as connection:
            counts = (
                connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM event) AS events,
                            (SELECT count(*) FROM source_observation
                             WHERE data_source_code = 'DATATOURISME_API') AS observations,
                            (SELECT count(*) FROM source_sighting) AS sightings,
                            (SELECT count(*) FROM collection_page) AS pages,
                            (SELECT count(*) FROM connector_coverage
                             WHERE connector = 'DATATOURISME') AS coverages
                        """
                    )
                )
                .mappings()
                .one()
            )
    finally:
        runtime.close()
        http_client.close()
        database.close()

    assert [request.headers[API_KEY_HEADER] for request in requests] == [API_KEY, API_KEY]
    assert all("api_key" not in request.url.params for request in requests)
    assert dict(counts) == {
        "events": 1,
        "observations": 1,
        "sightings": 2,
        "pages": 2,
        "coverages": 2,
    }


def test_worker_quarantines_conflicting_uuids_without_coverage(
    integration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    confirm_position(integration_database_url)
    _seed_metropolitan_boundary(integration_database_url)
    shared_uri = "https://data.datatourisme.fr/shared-resource"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "objects": [
                    _event(str(UUID(int=101)), uri=shared_uri),
                    _event(str(UUID(int=102)), uri=shared_uri),
                ],
                "meta": {
                    "total": 2,
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
        database_url=SecretStr(integration_database_url),
        datatourisme_api_key=SecretStr(API_KEY),
    )
    database = Database(settings.database_url)
    runtime = worker_module.build_runtime(settings, database)
    repository = SqlAlchemyCollectionRepository(database.engine)
    collections = CollectionService(
        repository,
        enabled_connectors=frozenset(("DATATOURISME",)),
        clock=lambda: NOW,
    )
    worker = CollectionWorker(repository, runtime.executors, "worker-events", clock=lambda: NOW)
    try:
        collections.request_manual("DATATOURISME")
        assert worker.run_once() is True
        dashboard = repository.dashboard().connectors[1]
        assert dashboard.latest_job is not None
        assert dashboard.latest_job.state == "PARTIAL"
        assert dashboard.latest_job.last_error is not None
        assert dashboard.latest_job.last_error.code == "datatourisme_identity_conflict"
        assert dashboard.coverage is None
        with database.engine.connect() as connection:
            counts = (
                connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM event) AS events,
                            (SELECT count(*) FROM source_observation
                             WHERE validation_status = 'IDENTITY_CONFLICT') AS quarantined,
                            (SELECT count(*) FROM collection_item
                             WHERE decision = 'ERROR') AS blocked,
                            (SELECT count(*) FROM connector_coverage
                             WHERE connector = 'DATATOURISME') AS coverages
                        """
                    )
                )
                .mappings()
                .one()
            )
    finally:
        runtime.close()
        http_client.close()
        database.close()

    assert dict(counts) == {
        "events": 0,
        "quarantined": 2,
        "blocked": 2,
        "coverages": 0,
    }
