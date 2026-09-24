"""Command-line process for Radar's durable single-concurrency worker."""

import argparse
import os
import socket
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from radar.collections.contracts import CollectionExecutor, Connector
from radar.collections.worker import CollectionWorker
from radar.config import Settings, get_settings
from radar.persistence.collections import SqlAlchemyCollectionRepository
from radar.persistence.database import Database
from radar.persistence.reference_data import SqlAlchemyMunicipalityReferenceRepository
from radar.persistence.sirene_execution import SqlAlchemySireneExecutionRepository
from radar.persistence.sirene_fallback_geocoding import (
    SqlAlchemySireneFallbackGeocodingRepository,
)
from radar.persistence.sirene_geolocation import SqlAlchemySireneGeolocationRepository
from radar.persistence.sirene_planning import SqlAlchemySirenePlanRepository
from radar.persistence.sirene_position_resolution import (
    SqlAlchemySirenePositionResolutionRepository,
)
from radar.persistence.sirene_projection import SqlAlchemySireneProspectProjectionRepository
from radar.persistence.sirene_staging import SqlAlchemySireneCandidateStagingRepository
from radar.persistence.sirene_status_reconciliation import (
    SqlAlchemySireneKnownStatusRepository,
)
from radar.prospects.fallback_geocoding import SireneFallbackGeocodingService
from radar.prospects.geolocation import (
    SireneGeolocationImportService,
    SireneGeolocationReleaseSource,
)
from radar.prospects.planning import SireneCollectionPlanningService
from radar.prospects.position_resolution import SirenePositionResolutionService
from radar.prospects.projection import SireneProspectProjectionService
from radar.prospects.sirene_collection import SireneBatchEnumerator
from radar.prospects.sirene_pipeline import SireneProspectCollectionExecutor
from radar.prospects.staging import SireneCandidatePageStager
from radar.prospects.status_reconciliation import SireneKnownStatusReconciliationService
from radar.providers.geoplatform import GeoPlatformGeocoder
from radar.providers.sirene import SireneClient
from radar.reference_data.service import MunicipalityReferenceService


def parser() -> argparse.ArgumentParser:
    """Build the worker command surface."""

    command_parser = argparse.ArgumentParser(prog="radar-worker")
    command_parser.add_argument(
        "--once",
        action="store_true",
        help="reserve at most one job and then exit",
    )
    return command_parser


def utc_now() -> datetime:
    """Return an aware UTC instant for source-release persistence."""

    return datetime.now(UTC)


@dataclass(frozen=True)
class WorkerRuntime:
    """Configured executors and provider clients owned by one worker process."""

    executors: Mapping[Connector, CollectionExecutor]
    close_callbacks: tuple[Callable[[], None], ...] = ()

    def close(self) -> None:
        """Close provider clients in reverse construction order."""

        for callback in reversed(self.close_callbacks):
            callback()


def build_runtime(settings: Settings, database: Database) -> WorkerRuntime:
    """Register only connectors whose complete local configuration is usable."""

    if not settings.sirene_connector_configured:
        return WorkerRuntime({})

    api_key = settings.sirene_api_key
    geolocation_path = settings.sirene_geolocation_file
    resource_identifier = settings.sirene_geolocation_resource_identifier
    resource_url = settings.sirene_geolocation_resource_url
    retrieved_at = settings.sirene_geolocation_retrieved_at
    assert api_key is not None
    assert geolocation_path is not None
    assert resource_identifier is not None
    assert resource_url is not None
    assert retrieved_at is not None

    engine = database.engine
    sirene_client = SireneClient(api_key.get_secret_value())
    geocoder = GeoPlatformGeocoder()
    planner = SireneCollectionPlanningService(
        MunicipalityReferenceService(SqlAlchemyMunicipalityReferenceRepository(engine)),
        SqlAlchemySirenePlanRepository(engine),
    )
    enumerator = SireneBatchEnumerator(
        planner,
        SqlAlchemySireneExecutionRepository(engine),
        sirene_client,
        SireneCandidatePageStager(SqlAlchemySireneCandidateStagingRepository(engine)),
    )
    geolocation_importer = SireneGeolocationImportService(
        SqlAlchemySireneGeolocationRepository(engine),
        clock=utc_now,
    )
    position_resolver = SirenePositionResolutionService(
        SqlAlchemySirenePositionResolutionRepository(engine)
    )
    fallback_geocoder = SireneFallbackGeocodingService(
        SqlAlchemySireneFallbackGeocodingRepository(engine),
        geocoder,
    )
    projector = SireneProspectProjectionService(
        SqlAlchemySireneProspectProjectionRepository(engine)
    )
    status_reconciler = SireneKnownStatusReconciliationService(
        SqlAlchemySireneKnownStatusRepository(engine),
        sirene_client,
    )
    executor = SireneProspectCollectionExecutor(
        enumerator,
        geolocation_importer,
        geolocation_path,
        SireneGeolocationReleaseSource(
            resource_identifier=resource_identifier,
            resource_url=resource_url,
            published_on=settings.sirene_geolocation_published_on,
            retrieved_at=retrieved_at,
            license_name=settings.sirene_geolocation_license_name,
            expected_sha1=settings.sirene_geolocation_expected_sha1,
            expected_size_bytes=settings.sirene_geolocation_expected_size_bytes,
        ),
        position_resolver,
        fallback_geocoder,
        projector,
        status_reconciler,
    )

    return WorkerRuntime({"SIRENE": executor}, (sirene_client.close, geocoder.close))


def worker_identity() -> str:
    """Create a diagnostic lease owner without exposing configuration secrets."""

    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the worker loop separately from the FastAPI process."""

    parsed = parser().parse_args(arguments)
    settings = get_settings()
    database = Database(settings.database_url)
    runtime = WorkerRuntime({})
    stopped = threading.Event()
    try:
        runtime = build_runtime(settings, database)
        if not runtime.executors:
            print("Aucun connecteur de collecte n'est complètement configuré dans le worker.")
            return 1
        worker = CollectionWorker(
            SqlAlchemyCollectionRepository(database.engine),
            runtime.executors,
            worker_identity(),
        )
        if parsed.once:
            worker.run_once()
            return 0
        while not stopped.is_set():
            if not worker.run_once():
                stopped.wait(5)
    except KeyboardInterrupt:
        stopped.set()
    finally:
        runtime.close()
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
