"""PostgreSQL/PostGIS tests for durable Sirene municipality planning."""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
from sqlalchemy import Engine, create_engine, text

from radar.collections.contracts import (
    CollectionError,
    CollectionOutcome,
    CollectionProgress,
    ConnectorSpecification,
    ProgressReporter,
    ReservedCollection,
)
from radar.collections.worker import CollectionWorker
from radar.geography.contracts import AddressNotFoundError, GeocodedAddress, StructuredAddress
from radar.persistence.collections import SqlAlchemyCollectionRepository
from radar.persistence.geography import SqlAlchemyGeographyRepository
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
from radar.prospects.contracts import (
    Activity,
    EstablishmentAddress,
    LambertCoordinates,
    ProspectCandidate,
)
from radar.prospects.fallback_geocoding import SireneFallbackGeocodingService
from radar.prospects.geolocation import (
    SireneGeolocationImportService,
    SireneGeolocationReleaseSource,
)
from radar.prospects.planning import (
    SireneCollectionPlanningService,
    SireneMunicipalityBatch,
)
from radar.prospects.position_resolution import SirenePositionResolutionService
from radar.prospects.projection import SireneProspectProjectionService
from radar.prospects.sirene_collection import SireneBatchEnumerator, SireneExecutionError
from radar.prospects.staging import SireneCandidatePageStager
from radar.providers.sirene import (
    SireneBatchSummary,
    SirenePage,
    SireneServiceInformation,
    SireneTemporaryError,
)
from radar.reference_data.contracts import MunicipalityReleaseSource
from radar.reference_data.service import MunicipalityReferenceService

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 20, 17, tzinfo=UTC)
DAX_LONGITUDE = -1.051952
DAX_LATITUDE = 43.70884


def polygon(longitude: float, latitude: float) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [longitude - 0.001, latitude - 0.001],
                [longitude + 0.001, latitude - 0.001],
                [longitude + 0.001, latitude + 0.001],
                [longitude - 0.001, latitude + 0.001],
                [longitude - 0.001, latitude - 0.001],
            ]
        ],
    }


def write_release(path: Path, codes: tuple[str, ...]) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"code": code, "nom": f"Commune {code}"},
                        "geometry": polygon(DAX_LONGITUDE, DAX_LATITUDE),
                    }
                    for code in codes
                ],
            }
        ),
        encoding="utf-8",
    )


def write_geolocation_file(path: Path, rows: list[tuple[object, ...]]) -> None:
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE geolocation (
                SIRET VARCHAR,
                X DOUBLE,
                Y DOUBLE,
                QUALITE_XY VARCHAR,
                EPSG VARCHAR,
                PLG_CODE_COMMUNE VARCHAR,
                DISTANCE_PRECISION DOUBLE,
                y_latitude DOUBLE,
                x_longitude DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO geolocation VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute("COPY geolocation TO ? (FORMAT PARQUET)", [str(path)])


def release_source(identifier: str) -> MunicipalityReleaseSource:
    return MunicipalityReleaseSource(
        resource_identifier=identifier,
        resource_url=f"https://example.data.gouv.fr/{identifier}/communes.geojson",
        published_on=None,
        retrieved_at=NOW,
        license_name="ODbL-1.0",
    )


def staging_candidate(
    coordinates: LambertCoordinates | None = None,
    *,
    siret: str = "12345678901234",
    siren: str = "123456789",
    street_number: str = "12",
) -> ProspectCandidate:
    return ProspectCandidate(
        siret=siret,
        siren=siren,
        is_head_office=False,
        establishment_names=("Atelier public",),
        legal_name="Société exemple",
        legal_usual_names=(),
        legal_category="5710",
        activity=Activity("10.71C", "NAFRev2"),
        employee_band="12",
        employee_year=2024,
        address=EstablishmentAddress(
            address_identifier="ADDR-1",
            street_number=street_number,
            repetition_index=None,
            street_type="RUE",
            street_label="SAINT PIERRE",
            address_complement=None,
            postcode="40100",
            municipality_label="DAX",
            municipality_code="40088",
            coordinates=coordinates,
        ),
        establishment_created_on="2020-01-02",
        current_period_started_on="2024-03-04",
        establishment_processed_at="2026-09-20T12:00:00",
        legal_unit_processed_at="2026-09-20T11:00:00",
    )


def confirm_dax(engine_url: str) -> None:
    engine = create_engine(engine_url)
    repository = SqlAlchemyGeographyRepository(engine)
    try:
        candidate = repository.save_candidate(
            "12 rue Saint-Pierre 40100 Dax",
            GeocodedAddress(
                normalized_label="12 Rue Saint Pierre 40100 Dax",
                structured_address=StructuredAddress(
                    house_number="12",
                    street="Rue Saint Pierre",
                    postcode="40100",
                    city="Dax",
                    context="40, Landes, Nouvelle-Aquitaine",
                ),
                longitude=DAX_LONGITUDE,
                latitude=DAX_LATITUDE,
                municipality_code="40088",
                ban_id=None,
                result_type="housenumber",
                score=0.96,
                provider_name="Géoplateforme",
                provider_url="https://data.geopf.fr/geocodage/search",
            ),
            NOW,
        )
        repository.confirm_candidate(candidate.id, NOW)
    finally:
        engine.dispose()


class FixtureSireneReader:
    """Deterministic two-page reader that contains no personal test data."""

    def __init__(self) -> None:
        self.information_calls = 0
        self.batch_calls: list[tuple[tuple[str, ...], str]] = []

    def service_information(self) -> SireneServiceInformation:
        self.information_calls += 1
        return SireneServiceInformation(
            service_state="UP",
            service_version="3.11-fixture",
            freshness=(("Établissements", "2026-09-19T00:00:00"),),
        )

    def collect_batch(
        self,
        municipality_codes: tuple[str, ...],
        at_date: str,
        on_page: Callable[[SirenePage], None],
    ) -> SireneBatchSummary:
        self.batch_calls.append((municipality_codes, at_date))
        on_page(
            SirenePage(
                number=1,
                announced_total=2,
                received_count=2,
                importable_candidates=(),
                rejection_counts={"fixture_filtered": 2},
                next_cursor_fingerprint="a" * 64,
                terminal=False,
            )
        )
        on_page(
            SirenePage(
                number=2,
                announced_total=2,
                received_count=0,
                importable_candidates=(),
                rejection_counts={},
                next_cursor_fingerprint=None,
                terminal=True,
            )
        )
        return SireneBatchSummary(
            announced_total=2,
            received_count=2,
            unique_siret_count=2,
            importable_count=0,
            page_count=2,
            rejection_counts={"fixture_filtered": 2},
        )


class FixtureFallbackGeocoder:
    """Return one public address result without making a network request."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def geocode(self, input_address: str) -> GeocodedAddress:
        self.queries.append(input_address)
        if input_address.startswith("14 "):
            raise AddressNotFoundError("fixture address not found")
        return GeocodedAddress(
            normalized_label="12 Rue Saint Pierre 40100 Dax",
            structured_address=StructuredAddress(
                house_number="12",
                street="Rue Saint Pierre",
                postcode="40100",
                city="Dax",
                context="40, Landes, Nouvelle-Aquitaine",
            ),
            longitude=DAX_LONGITUDE,
            latitude=DAX_LATITUDE,
            municipality_code="40088",
            ban_id="40088_1750_00012",
            result_type="housenumber",
            score=0.96,
            provider_name="Géoplateforme",
            provider_url="https://data.geopf.fr/geocodage/search",
        )


class TemporaryThenSuccessfulReader(FixtureSireneReader):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    def collect_batch(
        self,
        municipality_codes: tuple[str, ...],
        at_date: str,
        on_page: Callable[[SirenePage], None],
    ) -> SireneBatchSummary:
        if not self.failed_once:
            self.failed_once = True
            self.batch_calls.append((municipality_codes, at_date))
            on_page(
                SirenePage(
                    number=1,
                    announced_total=2,
                    received_count=2,
                    importable_candidates=(),
                    rejection_counts={"fixture_filtered": 2},
                    next_cursor_fingerprint="b" * 64,
                    terminal=False,
                )
            )
            raise SireneTemporaryError("fixture interruption")
        return super().collect_batch(municipality_codes, at_date, on_page)


class OrderingPageHandler:
    """Prove candidates are handled before the corresponding page is acknowledged."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.handled: list[tuple[str, int]] = []

    def handle(
        self,
        reservation: ReservedCollection,
        batch: SireneMunicipalityBatch,
        page: SirenePage,
    ) -> None:
        with self._engine.connect() as connection:
            prior_page_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM collection_page
                    WHERE collection_batch_id = :batch_id
                      AND collection_attempt_id = :attempt_id
                    """
                ),
                {"batch_id": batch.id, "attempt_id": reservation.attempt_id},
            ).scalar_one()
        assert prior_page_count == page.number - 1
        self.handled.append((batch.key, page.number))


class RecordingReporter:
    def __init__(self) -> None:
        self.updates: list[tuple[CollectionProgress, dict[str, object] | None]] = []

    def update(
        self,
        progress: CollectionProgress,
        checkpoint: Mapping[str, object] | None = None,
    ) -> None:
        self.updates.append((progress, dict(checkpoint) if checkpoint is not None else None))


class FixtureEnumerationExecutor:
    """Exercise worker retries without pretending enumeration is the full connector."""

    def __init__(self, enumerator: SireneBatchEnumerator) -> None:
        self._enumerator = enumerator

    def collect(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> CollectionOutcome:
        result = self._enumerator.enumerate(reservation, reporter)
        return CollectionOutcome(
            "SUCCEEDED",
            counters={"observations": result.importable_count},
        )


@dataclass
class MutableClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


def test_freezes_disjoint_batches_and_reuses_them_after_a_reference_change(
    integration_database_url: str,
    tmp_path: Path,
) -> None:
    first_codes = tuple(f"40{index:03d}" for index in range(65))
    first_path = tmp_path / "communes-2026.geojson"
    write_release(first_path, first_codes)
    replacement_path = tmp_path / "communes-2027.geojson"
    write_release(replacement_path, ("40088",))

    confirm_dax(integration_database_url)
    engine = create_engine(integration_database_url)
    municipality_reference = MunicipalityReferenceService(
        SqlAlchemyMunicipalityReferenceRepository(engine),
        clock=lambda: NOW,
    )
    collection_repository = SqlAlchemyCollectionRepository(engine)
    planning_service = SireneCollectionPlanningService(
        municipality_reference,
        SqlAlchemySirenePlanRepository(engine),
        clock=lambda: NOW,
    )
    try:
        first_release = municipality_reference.import_file(
            first_path,
            release_source("2026"),
        )
        queued = collection_repository.enqueue(
            "SIRENE",
            "MANUAL",
            ConnectorSpecification("sirene-test", "b" * 64),
            NOW,
        )
        reservation = collection_repository.reserve_next(
            "sirene-planning-test",
            ("SIRENE",),
            NOW + timedelta(seconds=1),
            NOW + timedelta(minutes=5),
        )
        assert reservation is not None
        assert reservation.cycle_id == queued.job.cycle_id

        plan = planning_service.plan(reservation)
        assert plan.newly_created is True
        assert plan.dataset_release_id == first_release.id
        assert plan.margin_meters == 1_000
        assert plan.municipality_count == 65
        assert [len(batch.municipality_codes) for batch in plan.batches] == [30, 30, 5]
        planned_codes = tuple(code for batch in plan.batches for code in batch.municipality_codes)
        assert planned_codes == first_codes
        assert len(set(planned_codes)) == 65

        replacement = municipality_reference.import_file(
            replacement_path,
            release_source("2027"),
        )
        assert replacement.id != first_release.id
        reused = planning_service.plan(reservation)
        assert reused.newly_created is False
        assert reused.dataset_release_id == first_release.id
        assert tuple(batch.id for batch in reused.batches) == tuple(
            batch.id for batch in plan.batches
        )

        with engine.connect() as connection:
            counts = (
                connection.execute(
                    text(
                        """
                    SELECT
                        (SELECT count(*) FROM collection_source_run) AS source_runs,
                        (SELECT count(*) FROM collection_batch) AS batches,
                        (SELECT count(*) FROM collection_cycle_commune) AS communes,
                        (SELECT count(*) FROM collection_reference_usage) AS reference_usages
                    """
                    )
                )
                .mappings()
                .one()
            )
            distinct_batch_assignments = connection.execute(
                text(
                    """
                    SELECT count(DISTINCT municipality_code), count(*)
                    FROM collection_cycle_commune
                    WHERE collection_cycle_id = :cycle_id
                    """
                ),
                {"cycle_id": reservation.cycle_id},
            ).one()
        assert dict(counts) == {
            "source_runs": 1,
            "batches": 3,
            "communes": 65,
            "reference_usages": 1,
        }
        assert tuple(distinct_batch_assignments) == (65, 65)
    finally:
        engine.dispose()


def test_enumerates_batches_with_durable_page_evidence_and_is_idempotent(
    integration_database_url: str,
    tmp_path: Path,
) -> None:
    codes = tuple(f"40{index:03d}" for index in range(31))
    release_path = tmp_path / "communes-execution.geojson"
    write_release(release_path, codes)

    confirm_dax(integration_database_url)
    engine = create_engine(integration_database_url)
    municipality_reference = MunicipalityReferenceService(
        SqlAlchemyMunicipalityReferenceRepository(engine),
        clock=lambda: NOW,
    )
    collection_repository = SqlAlchemyCollectionRepository(engine)
    planning_service = SireneCollectionPlanningService(
        municipality_reference,
        SqlAlchemySirenePlanRepository(engine),
        clock=lambda: NOW,
    )
    reader = FixtureSireneReader()
    page_handler = OrderingPageHandler(engine)
    reporter = RecordingReporter()
    enumerator = SireneBatchEnumerator(
        planning_service,
        SqlAlchemySireneExecutionRepository(engine),
        reader,
        page_handler,
        clock=lambda: NOW,
    )
    try:
        municipality_reference.import_file(release_path, release_source("execution-2026"))
        collection_repository.enqueue(
            "SIRENE",
            "MANUAL",
            ConnectorSpecification("sirene-test", "c" * 64),
            NOW,
        )
        reservation = collection_repository.reserve_next(
            "sirene-execution-test",
            ("SIRENE",),
            NOW + timedelta(seconds=1),
            NOW + timedelta(minutes=5),
        )
        assert reservation is not None

        result = enumerator.enumerate(reservation, reporter)
        assert result.announced_total == 4
        assert result.received_count == 4
        assert result.unique_siret_count == 4
        assert result.importable_count == 0
        assert result.page_count == 4
        assert result.batch_count == 2
        assert result.rejection_counts == {"fixture_filtered": 4}
        assert result.source_metadata == {
            "freshness": [
                {
                    "collection": "Établissements",
                    "last_availability": "2026-09-19T00:00:00",
                }
            ],
            "service_state": "UP",
            "service_version": "3.11-fixture",
        }
        assert reader.information_calls == 1
        assert [len(batch_codes) for batch_codes, _ in reader.batch_calls] == [30, 1]
        assert {query_date for _, query_date in reader.batch_calls} == {"2026-09-20"}
        assert len(page_handler.handled) == 4
        assert reporter.updates[-1][0] == CollectionProgress(
            "sirene_enumeration",
            processed=2,
            total=2,
        )

        with engine.connect() as connection:
            source = (
                connection.execute(
                    text(
                        """
                        SELECT status, request_count, counters, metadata
                        FROM collection_source_run
                        """
                    )
                )
                .mappings()
                .one()
            )
            batches = (
                connection.execute(
                    text(
                        """
                        SELECT state, attempt_count, processing_counts
                        FROM collection_batch
                        ORDER BY order_number
                        """
                    )
                )
                .mappings()
                .all()
            )
            page_counts = connection.execute(
                text(
                    """
                    SELECT count(*) AS pages,
                           count(*) FILTER (WHERE is_terminal) AS terminal_pages,
                           count(*) FILTER (WHERE next_link_fingerprint IS NOT NULL) AS cursors
                    FROM collection_page
                    """
                )
            ).one()
            commune_states = connection.execute(
                text(
                    """
                    SELECT state, count(*)
                    FROM collection_cycle_commune
                    GROUP BY state
                    """
                )
            ).all()

        assert source["status"] == "SUCCEEDED"
        assert source["request_count"] == 5
        assert source["counters"]["batch_count"] == 2
        assert source["metadata"]["service_version"] == "3.11-fixture"
        assert [batch["state"] for batch in batches] == ["SUCCEEDED", "SUCCEEDED"]
        assert [batch["attempt_count"] for batch in batches] == [1, 1]
        assert [batch["processing_counts"]["page_count"] for batch in batches] == [2, 2]
        assert tuple(page_counts) == (4, 2, 2)
        assert [tuple(row) for row in commune_states] == [("SUCCEEDED", 31)]

        second_result = enumerator.enumerate(reservation, reporter)
        assert second_result == result
        assert reader.information_calls == 1
        assert len(reader.batch_calls) == 2
        assert len(page_handler.handled) == 4
    finally:
        engine.dispose()


def test_worker_retries_a_whole_interrupted_batch_without_losing_page_history(
    integration_database_url: str,
    tmp_path: Path,
) -> None:
    release_path = tmp_path / "communes-retry.geojson"
    write_release(release_path, ("40088",))

    confirm_dax(integration_database_url)
    engine = create_engine(integration_database_url)
    municipality_reference = MunicipalityReferenceService(
        SqlAlchemyMunicipalityReferenceRepository(engine),
        clock=lambda: NOW,
    )
    collection_repository = SqlAlchemyCollectionRepository(engine)
    planning_service = SireneCollectionPlanningService(
        municipality_reference,
        SqlAlchemySirenePlanRepository(engine),
        clock=lambda: NOW,
    )
    reader = TemporaryThenSuccessfulReader()
    page_handler = OrderingPageHandler(engine)
    clock = MutableClock(NOW + timedelta(seconds=1))
    executor = FixtureEnumerationExecutor(
        SireneBatchEnumerator(
            planning_service,
            SqlAlchemySireneExecutionRepository(engine),
            reader,
            page_handler,
            clock=clock,
        )
    )
    worker = CollectionWorker(
        collection_repository,
        {"SIRENE": executor},
        "sirene-retry-test",
        clock=clock,
    )
    try:
        municipality_reference.import_file(release_path, release_source("retry-2026"))
        queued = collection_repository.enqueue(
            "SIRENE",
            "MANUAL",
            ConnectorSpecification("sirene-test", "d" * 64),
            NOW,
        )

        assert worker.run_once() is True
        after_failure = collection_repository.dashboard().connectors[0]
        assert after_failure.active_job is not None
        assert after_failure.active_job.id == queued.job.id
        assert after_failure.active_job.state == "WAITING_RETRY"
        assert after_failure.active_job.attempt_count == 1

        clock.now += timedelta(minutes=31)
        assert worker.run_once() is True
        after_retry = collection_repository.dashboard().connectors[0]
        assert after_retry.latest_job is not None
        assert after_retry.latest_job.id == queued.job.id
        assert after_retry.latest_job.state == "SUCCEEDED"
        assert after_retry.latest_job.attempt_count == 2
        assert after_retry.coverage is not None

        with engine.connect() as connection:
            batch = (
                connection.execute(
                    text(
                        """
                        SELECT state, attempt_count, resume_state
                        FROM collection_batch
                        """
                    )
                )
                .mappings()
                .one()
            )
            pages_by_attempt = connection.execute(
                text(
                    """
                    SELECT attempt.attempt_number, count(*) AS page_count
                    FROM collection_page AS page
                    JOIN collection_attempt AS attempt
                      ON attempt.id = page.collection_attempt_id
                    GROUP BY attempt.attempt_number
                    ORDER BY attempt.attempt_number
                    """
                )
            ).all()
            source = connection.execute(
                text(
                    """
                    SELECT status, request_count, retry_count, error_count
                    FROM collection_source_run
                    """
                )
            ).one()

        assert batch["state"] == "SUCCEEDED"
        assert batch["attempt_count"] == 2
        assert batch["resume_state"] == {
            "restart_policy": "BATCH_FROM_START",
            "terminal_page": 2,
        }
        assert [tuple(row) for row in pages_by_attempt] == [(1, 1), (2, 2)]
        assert tuple(source) == ("SUCCEEDED", 4, 1, 1)
        assert reader.information_calls == 1
        assert len(reader.batch_calls) == 2
        assert len(page_handler.handled) == 3
    finally:
        engine.dispose()


def test_stages_one_observation_idempotently_across_a_whole_batch_retry(
    integration_database_url: str,
    tmp_path: Path,
) -> None:
    release_path = tmp_path / "communes-staging.geojson"
    write_release(release_path, ("40088",))

    confirm_dax(integration_database_url)
    engine = create_engine(integration_database_url)
    municipality_reference = MunicipalityReferenceService(
        SqlAlchemyMunicipalityReferenceRepository(engine),
        clock=lambda: NOW,
    )
    collection_repository = SqlAlchemyCollectionRepository(engine)
    planning_service = SireneCollectionPlanningService(
        municipality_reference,
        SqlAlchemySirenePlanRepository(engine),
        clock=lambda: NOW,
    )
    execution_repository = SqlAlchemySireneExecutionRepository(engine)
    clock = MutableClock(NOW + timedelta(seconds=1))
    stager = SireneCandidatePageStager(
        SqlAlchemySireneCandidateStagingRepository(engine),
        clock=clock,
    )
    with engine.connect() as connection:
        lambert = connection.execute(
            text(
                """
                SELECT
                    ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326), 2154)),
                    ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326), 2154)),
                    ST_X(ST_Transform(
                        ST_SetSRID(ST_MakePoint(:outside_longitude, :latitude), 4326),
                        2154
                    )),
                    ST_Y(ST_Transform(
                        ST_SetSRID(ST_MakePoint(:outside_longitude, :latitude), 4326),
                        2154
                    ))
                """
            ),
            {
                "longitude": DAX_LONGITUDE,
                "outside_longitude": DAX_LONGITUDE + 0.005,
                "latitude": DAX_LATITUDE,
            },
        ).one()
    candidate = staging_candidate(LambertCoordinates(float(lambert[0]), float(lambert[1])))
    candidate_without_coordinates = staging_candidate(
        siret="98765432109876",
        siren="987654321",
    )
    candidate_with_file_fallback = staging_candidate(
        siret="55555555555555",
        siren="555555555",
    )
    candidate_unresolved = staging_candidate(
        siret="66666666666666",
        siren="666666666",
        street_number="14",
    )
    candidate_outside_radius = staging_candidate(
        LambertCoordinates(float(lambert[2]), float(lambert[3])),
        siret="77777777777777",
        siren="777777777",
    )
    information = SireneServiceInformation(
        service_state="UP",
        service_version="3.11-fixture",
        freshness=(("Établissements", "2026-09-20T07:44:27"),),
    )
    candidate_page = SirenePage(
        number=1,
        announced_total=5,
        received_count=5,
        importable_candidates=(
            candidate,
            candidate_without_coordinates,
            candidate_with_file_fallback,
            candidate_unresolved,
            candidate_outside_radius,
        ),
        rejection_counts={},
        next_cursor_fingerprint="d" * 64,
        terminal=False,
    )
    terminal_page = SirenePage(
        number=2,
        announced_total=5,
        received_count=0,
        importable_candidates=(),
        rejection_counts={},
        next_cursor_fingerprint=None,
        terminal=True,
    )
    try:
        municipality_reference.import_file(release_path, release_source("staging-2026"))
        SqlAlchemyGeographyRepository(engine).update_radii(100, 100, clock.now)
        collection_repository.enqueue(
            "SIRENE",
            "MANUAL",
            ConnectorSpecification("sirene-test", "e" * 64),
            NOW,
        )
        first = collection_repository.reserve_next(
            "sirene-staging-test",
            ("SIRENE",),
            clock.now,
            clock.now + timedelta(minutes=5),
        )
        assert first is not None
        first_plan = planning_service.plan(first)
        execution_repository.start_source(first, first_plan, information, clock.now)
        first_batch = first_plan.batches[0]
        assert execution_repository.start_batch(first, first_batch, clock.now) is True

        with pytest.raises(SireneExecutionError, match="staged candidates"):
            execution_repository.record_page(first, first_batch, candidate_page, clock.now)
        stager.handle(first, first_batch, candidate_page)
        stager.handle(first, first_batch, candidate_page)
        execution_repository.record_page(first, first_batch, candidate_page, clock.now)
        execution_repository.fail_batch(
            first,
            first_batch,
            code="fixture_interruption",
            message="Interruption contrôlée.",
            transient=True,
            now=clock.now,
        )
        collection_repository.defer_retry(
            first,
            "sirene-staging-test",
            CollectionError(
                "fixture_interruption",
                "Interruption contrôlée.",
                transient=True,
            ),
            clock.now + timedelta(minutes=30),
            clock.now,
        )

        clock.now += timedelta(minutes=31)
        second = collection_repository.reserve_next(
            "sirene-staging-test",
            ("SIRENE",),
            clock.now,
            clock.now + timedelta(minutes=5),
        )
        assert second is not None
        second_plan = planning_service.plan(second)
        second_batch = second_plan.batches[0]
        assert execution_repository.start_batch(second, second_batch, clock.now) is True
        stager.handle(second, second_batch, candidate_page)
        execution_repository.record_page(second, second_batch, candidate_page, clock.now)
        stager.handle(second, second_batch, terminal_page)
        execution_repository.record_page(second, second_batch, terminal_page, clock.now)
        execution_repository.complete_batch(
            second,
            second_batch,
            SireneBatchSummary(
                announced_total=5,
                received_count=5,
                unique_siret_count=5,
                importable_count=5,
                page_count=2,
                rejection_counts={},
            ),
            clock.now,
        )
        result = execution_repository.finish_source(second, second_plan, clock.now)
        assert result.importable_count == 5

        geolocation_path = tmp_path / "sirene-geolocation.parquet"
        write_geolocation_file(
            geolocation_path,
            [
                (
                    "12345678901234",
                    float(lambert[0]),
                    float(lambert[1]),
                    "11",
                    "2154",
                    "40088",
                    0.0,
                    DAX_LATITUDE,
                    DAX_LONGITUDE,
                ),
                (
                    "98765432109876",
                    float(lambert[0]),
                    float(lambert[1]),
                    "33",
                    "2154",
                    "40088",
                    500.0,
                    DAX_LATITUDE,
                    DAX_LONGITUDE,
                ),
                (
                    "55555555555555",
                    float(lambert[0]),
                    float(lambert[1]),
                    "22",
                    "2154",
                    "40088",
                    50.0,
                    DAX_LATITUDE,
                    DAX_LONGITUDE,
                ),
                (
                    "77777777777777",
                    float(lambert[2]),
                    float(lambert[3]),
                    "11",
                    "2154",
                    "40088",
                    0.0,
                    DAX_LATITUDE,
                    DAX_LONGITUDE + 0.005,
                ),
                (
                    "99999999999999",
                    float(lambert[0]),
                    float(lambert[1]),
                    "11",
                    "2154",
                    "40088",
                    0.0,
                    DAX_LATITUDE,
                    DAX_LONGITUDE,
                ),
            ],
        )
        geolocation_content = geolocation_path.read_bytes()
        geolocation_service = SireneGeolocationImportService(
            SqlAlchemySireneGeolocationRepository(engine),
            clock=clock,
        )
        geolocation_source = SireneGeolocationReleaseSource(
            resource_identifier="sirene-geolocation-2026-09-fixture",
            resource_url="https://example.data.gouv.fr/sirene-geolocation.parquet",
            published_on=None,
            retrieved_at=clock.now,
            license_name="Licence Ouverte 2.0",
            expected_sha1=hashlib.sha1(
                geolocation_content,
                usedforsecurity=False,
            ).hexdigest(),
            expected_size_bytes=len(geolocation_content),
        )
        geolocation_scan = geolocation_service.import_file(
            second,
            geolocation_path,
            geolocation_source,
        )
        repeated_scan = geolocation_service.import_file(
            second,
            geolocation_path,
            geolocation_source,
        )
        assert geolocation_scan.requested_siret_count == 5
        assert geolocation_scan.matched_siret_count == 4
        assert geolocation_scan.missing_siret_count == 1
        assert repeated_scan == geolocation_scan

        resolution_service = SirenePositionResolutionService(
            SqlAlchemySirenePositionResolutionRepository(engine),
            clock=clock,
        )
        resolution = resolution_service.resolve(second)
        repeated_resolution = resolution_service.resolve(second)
        assert resolution.requested_count == 5
        assert resolution.api_selected_count == 2
        assert resolution.file_selected_count == 1
        assert resolution.geocoder_selected_count == 0
        assert resolution.geocoding_required_count == 2
        assert resolution.unresolved_count == 0
        assert resolution.divergent_count == 0
        assert repeated_resolution == resolution

        fixture_geocoder = FixtureFallbackGeocoder()
        fallback_service = SireneFallbackGeocodingService(
            SqlAlchemySireneFallbackGeocodingRepository(engine),
            fixture_geocoder,
            clock=clock,
            monotonic=lambda: 1.0,
            sleeper=lambda _seconds: None,
        )
        fallback_summary = fallback_service.geocode_pending(second)
        repeated_fallback_summary = fallback_service.geocode_pending(second)
        assert fallback_summary.requested_count == 2
        assert fallback_summary.matched_count == 1
        assert fallback_summary.usable_count == 1
        assert fallback_summary.to_verify_count == 0
        assert fallback_summary.missing_count == 1
        assert repeated_fallback_summary == fallback_summary
        assert sorted(fixture_geocoder.queries) == [
            "12 RUE SAINT PIERRE 40100 DAX",
            "14 RUE SAINT PIERRE 40100 DAX",
        ]

        final_resolution = resolution_service.resolve(second)
        assert final_resolution.requested_count == 5
        assert final_resolution.api_selected_count == 2
        assert final_resolution.file_selected_count == 1
        assert final_resolution.geocoder_selected_count == 1
        assert final_resolution.geocoding_required_count == 0
        assert final_resolution.unresolved_count == 1
        assert final_resolution.divergent_count == 0

        projection_service = SireneProspectProjectionService(
            SqlAlchemySireneProspectProjectionRepository(engine),
            clock=clock,
        )
        projection = projection_service.project(second)
        repeated_projection = projection_service.project(second)
        assert projection.requested_count == 5
        assert projection.created_count == 4
        assert projection.updated_count == 0
        assert projection.unchanged_count == 0
        assert projection.counted_only_count == 1
        assert projection.location_unknown_count == 1
        assert repeated_projection == projection

        with engine.connect() as connection:
            counts = (
                connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM external_identity) AS identities,
                            (SELECT count(*) FROM source_observation) AS observations,
                            (SELECT count(*) FROM collection_item) AS items,
                            (SELECT count(*) FROM candidate_position) AS positions,
                            (SELECT count(*) FROM collection_page) AS pages,
                            (SELECT count(*) FROM collection_item
                             WHERE collection_page_id IS NOT NULL) AS linked_items,
                            (SELECT count(*) FROM organization) AS organizations,
                            (SELECT count(*) FROM establishment) AS establishments,
                            (SELECT count(*) FROM opportunity) AS opportunities,
                            (SELECT count(*) FROM prospect) AS prospects,
                            (SELECT count(*) FROM source_binding) AS source_bindings,
                            (SELECT count(*) FROM source_sighting) AS source_sightings,
                            (SELECT count(*) FROM location_assertion) AS locations
                        """
                    )
                )
                .mappings()
                .one()
            )
            identity = (
                connection.execute(
                    text(
                        """
                        SELECT authority, namespace, canonical_value,
                               fingerprint_algorithm, restricted_at
                        FROM external_identity
                        WHERE canonical_value = '12345678901234'
                        """
                    )
                )
                .mappings()
                .one()
            )
            observation = (
                connection.execute(
                    text(
                        """
                        SELECT data_source_code, validation_status, payload,
                               collection_cycle_id, collection_page_id
                        FROM source_observation
                        WHERE payload ->> 'siret' = '12345678901234'
                          AND data_source_code = 'SIRENE_API'
                        """
                    )
                )
                .mappings()
                .one()
            )
            items = (
                connection.execute(
                    text(
                        """
                        SELECT attempt.attempt_number, item.page_number,
                               item.item_rank, item.geographic_classification,
                               item.distance_meters, item.decision, item.reason
                        FROM collection_item AS item
                        JOIN collection_attempt AS attempt
                          ON attempt.id = item.collection_attempt_id
                        ORDER BY attempt.attempt_number, item.item_rank
                        """
                    )
                )
                .mappings()
                .all()
            )
            source = connection.execute(
                text(
                    """
                    SELECT status, request_count, retry_count, error_count
                    FROM collection_source_run
                    WHERE source = 'SIRENE_API'
                    """
                )
            ).one()
            geolocation_positions = (
                connection.execute(
                    text(
                        """
                        SELECT identity.canonical_value AS siret,
                               position.quality_code,
                               position.precision,
                               position.usability,
                               position.geographic_classification,
                               position.distance_meters,
                               position.diagnostics,
                               release.status AS release_status,
                               source.status AS source_status
                        FROM candidate_position AS position
                        JOIN collection_item AS item
                          ON item.id = position.collection_item_id
                        JOIN external_identity AS identity
                          ON identity.id = item.external_identity_id
                        JOIN dataset_release AS release
                          ON release.id = position.dataset_release_id
                        JOIN collection_source_run AS source
                          ON source.dataset_release_id = release.id
                         AND source.collection_cycle_id = item.collection_cycle_id
                         AND source.source = 'SIRENE_GEOLOCATION'
                        WHERE position.origin = 'SIRENE_GEOLOCATION'
                        ORDER BY identity.canonical_value
                        """
                    )
                )
                .mappings()
                .all()
            )
            fallback_positions = (
                connection.execute(
                    text(
                        """
                        SELECT
                            position.precision,
                            position.usability,
                            position.geographic_classification,
                            position.distance_meters,
                            position.diagnostics,
                            observation.payload,
                            source.status AS source_status,
                            source.request_count,
                            source.error_count
                        FROM candidate_position AS position
                        JOIN source_observation AS observation
                          ON observation.id = position.source_observation_id
                        JOIN collection_item AS item
                          ON item.id = position.collection_item_id
                        JOIN collection_source_run AS source
                          ON source.collection_cycle_id = item.collection_cycle_id
                         AND source.source = 'GEOPLATFORM_GEOCODER'
                        WHERE position.origin = 'GEOPLATFORM_GEOCODER'
                        ORDER BY observation.payload #>> '{request,input_address}'
                        """
                    )
                )
                .mappings()
                .all()
            )
            projected_prospects = (
                connection.execute(
                    text(
                        """
                        SELECT
                            establishment.siret,
                            organization.siren,
                            organization.legal_name,
                            organization.administrative_state
                                AS organization_state,
                            organization.diffusion_status
                                AS organization_diffusion,
                            establishment.activity_code,
                            establishment.activity_nomenclature,
                            establishment.employee_band,
                            establishment.employee_scope,
                            establishment.administrative_state
                                AS establishment_state,
                            prospect.source_display_name,
                            prospect.eligibility,
                            opportunity.hidden_at,
                            location.position_origin,
                            location.precision,
                            location.usability,
                            location.point IS NOT NULL AS has_point,
                            location.municipality_code,
                            binding.state AS binding_state,
                            identity.establishment_id = establishment.id
                                AS identity_linked
                        FROM prospect
                        JOIN opportunity ON opportunity.id = prospect.id
                        JOIN establishment
                          ON establishment.id = prospect.establishment_id
                        JOIN organization
                          ON organization.id = establishment.organization_id
                        JOIN source_binding AS binding
                          ON binding.opportunity_id = opportunity.id
                         AND binding.data_source_code = 'SIRENE_API'
                        JOIN external_identity AS identity
                          ON identity.id = binding.external_identity_id
                        JOIN location_assertion AS location
                          ON location.opportunity_id = opportunity.id
                         AND location.layer = 'SOURCE'
                         AND location.is_current
                        ORDER BY establishment.siret
                        """
                    )
                )
                .mappings()
                .all()
            )
            lineage_counts = connection.execute(
                text(
                    """
                    SELECT field_code, count(*)
                    FROM field_lineage
                    GROUP BY field_code
                    ORDER BY field_code
                    """
                )
            ).all()

        assert dict(counts) == {
            "identities": 5,
            "observations": 11,
            "items": 10,
            "positions": 16,
            "pages": 3,
            "linked_items": 10,
            "organizations": 4,
            "establishments": 4,
            "opportunities": 4,
            "prospects": 4,
            "source_bindings": 4,
            "source_sightings": 4,
            "locations": 4,
        }
        assert dict(identity) == {
            "authority": "INSEE",
            "namespace": "SIRET",
            "canonical_value": "12345678901234",
            "fingerprint_algorithm": "SHA-256",
            "restricted_at": None,
        }
        assert observation["data_source_code"] == "SIRENE_API"
        assert observation["validation_status"] == "VALID"
        assert observation["collection_cycle_id"] == second.cycle_id
        assert observation["collection_page_id"] is not None
        assert observation["payload"]["employee_band"] == "12"
        assert observation["payload"]["address"]["municipality_code"] == "40088"
        assert observation["payload"]["address"]["coordinates"]["crs"] == "EPSG:2154"
        assert [item["attempt_number"] for item in items] == [
            1,
            1,
            1,
            1,
            1,
            2,
            2,
            2,
            2,
            2,
        ]
        assert all(item["page_number"] == 1 for item in items)
        assert [item["item_rank"] for item in items] == [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
        first_attempt = [item for item in items if item["attempt_number"] == 1]
        current_attempt = [item for item in items if item["attempt_number"] == 2]
        assert first_attempt[0]["geographic_classification"] == "IN_RADIUS"
        assert first_attempt[0]["distance_meters"] == pytest.approx(0.0, abs=0.1)
        assert first_attempt[0]["reason"]["code"] == "API_COORDINATES_USABLE"
        assert first_attempt[0]["reason"]["precision"] == "UNKNOWN"
        assert all(
            item["geographic_classification"] == "LOCATION_UNKNOWN" for item in first_attempt[1:4]
        )
        assert all(item["distance_meters"] is None for item in first_attempt[1:4])
        assert all(
            item["reason"]["code"] == "API_COORDINATES_MISSING" for item in first_attempt[1:4]
        )
        assert first_attempt[4]["geographic_classification"] == "OUTSIDE_RADIUS"
        assert first_attempt[4]["distance_meters"] > 100
        assert current_attempt[0]["geographic_classification"] == "IN_RADIUS"
        assert current_attempt[0]["distance_meters"] == pytest.approx(0.0, abs=0.1)
        assert current_attempt[0]["reason"]["code"] == "POSITION_RESOLVED"
        assert current_attempt[0]["reason"]["position_source"] == "SIRENE_API"
        assert current_attempt[0]["reason"]["precision"] == "UNKNOWN"
        assert current_attempt[1]["geographic_classification"] == "IN_RADIUS"
        assert current_attempt[1]["distance_meters"] == pytest.approx(0.0, abs=0.1)
        assert current_attempt[1]["reason"]["code"] == "POSITION_RESOLVED"
        assert current_attempt[1]["reason"]["position_source"] == "GEOPLATFORM_GEOCODER"
        assert current_attempt[1]["reason"]["precision"] == "ADDRESS"
        assert current_attempt[1]["reason"]["file_quality_code"] == "33"
        assert current_attempt[2]["geographic_classification"] == "IN_RADIUS"
        assert current_attempt[2]["distance_meters"] == pytest.approx(0.0, abs=0.1)
        assert current_attempt[2]["reason"]["code"] == "POSITION_RESOLVED"
        assert current_attempt[2]["reason"]["position_source"] == "SIRENE_GEOLOCATION"
        assert current_attempt[2]["reason"]["precision"] == "STREET"
        assert current_attempt[3]["geographic_classification"] == "LOCATION_UNKNOWN"
        assert current_attempt[3]["distance_meters"] is None
        assert current_attempt[3]["reason"]["code"] == "POSITION_UNRESOLVED"
        assert current_attempt[3]["reason"]["geocoder_usability"] == "MISSING"
        assert (
            current_attempt[3]["reason"]["geocoder_diagnostic_code"] == "GEOCODER_ADDRESS_NOT_FOUND"
        )
        assert current_attempt[4]["geographic_classification"] == "OUTSIDE_RADIUS"
        assert current_attempt[4]["distance_meters"] > 100
        assert current_attempt[4]["reason"]["position_source"] == "SIRENE_API"
        assert all(item["decision"] is None for item in first_attempt)
        assert all(item["decision"] == "CREATED" for item in current_attempt[:4])
        assert current_attempt[4]["decision"] == "COUNTED_ONLY"
        assert all(
            item["reason"]["projection_code"] == "PROSPECT_PROJECTED"
            for item in current_attempt[:4]
        )
        assert current_attempt[4]["reason"]["projection_code"] == "OUTSIDE_COLLECTION_RADIUS"
        assert tuple(source) == ("SUCCEEDED", 4, 1, 1)
        assert len(geolocation_positions) == 4
        (
            usable_file_position,
            fallback_file_position,
            outside_file_position,
            approximate_file_position,
        ) = geolocation_positions
        assert usable_file_position["siret"] == "12345678901234"
        assert usable_file_position["quality_code"] == "11"
        assert usable_file_position["precision"] == "ADDRESS"
        assert usable_file_position["usability"] == "USABLE"
        assert usable_file_position["geographic_classification"] == "IN_RADIUS"
        assert usable_file_position["distance_meters"] == pytest.approx(0.0, abs=0.1)
        assert usable_file_position["diagnostics"]["code"] == "FILE_COORDINATES_USABLE"
        assert fallback_file_position["siret"] == "55555555555555"
        assert fallback_file_position["quality_code"] == "22"
        assert fallback_file_position["precision"] == "STREET"
        assert fallback_file_position["usability"] == "USABLE"
        assert fallback_file_position["geographic_classification"] == "IN_RADIUS"
        assert fallback_file_position["distance_meters"] == pytest.approx(0.0, abs=0.1)
        assert fallback_file_position["diagnostics"]["code"] == "FILE_COORDINATES_USABLE"
        assert outside_file_position["siret"] == "77777777777777"
        assert outside_file_position["quality_code"] == "11"
        assert outside_file_position["usability"] == "USABLE"
        assert outside_file_position["geographic_classification"] == "OUTSIDE_RADIUS"
        assert outside_file_position["distance_meters"] > 100
        assert approximate_file_position["siret"] == "98765432109876"
        assert approximate_file_position["quality_code"] == "33"
        assert approximate_file_position["precision"] == "MUNICIPALITY"
        assert approximate_file_position["usability"] == "TO_VERIFY"
        assert approximate_file_position["geographic_classification"] == "LOCATION_UNKNOWN"
        assert approximate_file_position["distance_meters"] is None
        assert (
            approximate_file_position["diagnostics"]["code"] == "FILE_QUALITY_REQUIRES_VERIFICATION"
        )
        assert all(position["release_status"] == "ACTIVE" for position in geolocation_positions)
        assert all(position["source_status"] == "SUCCEEDED" for position in geolocation_positions)
        assert len(fallback_positions) == 2
        usable_fallback, missing_fallback = fallback_positions
        assert usable_fallback["precision"] == "ADDRESS"
        assert usable_fallback["usability"] == "USABLE"
        assert usable_fallback["geographic_classification"] == "IN_RADIUS"
        assert usable_fallback["distance_meters"] == pytest.approx(0.0, abs=0.1)
        assert usable_fallback["diagnostics"]["code"] == "GEOCODER_ADDRESS_USABLE"
        assert usable_fallback["diagnostics"]["score"] == 0.96
        assert usable_fallback["payload"]["outcome"] == "MATCHED"
        assert usable_fallback["payload"]["request"]["input_address"] == (
            "12 RUE SAINT PIERRE 40100 DAX"
        )
        assert missing_fallback["precision"] == "UNKNOWN"
        assert missing_fallback["usability"] == "MISSING"
        assert missing_fallback["geographic_classification"] == "LOCATION_UNKNOWN"
        assert missing_fallback["distance_meters"] is None
        assert missing_fallback["diagnostics"]["code"] == "GEOCODER_ADDRESS_NOT_FOUND"
        assert missing_fallback["payload"]["outcome"] == "NOT_FOUND"
        assert missing_fallback["payload"]["request"]["input_address"] == (
            "14 RUE SAINT PIERRE 40100 DAX"
        )
        assert all(position["source_status"] == "SUCCEEDED" for position in fallback_positions)
        assert all(position["request_count"] == 2 for position in fallback_positions)
        assert all(position["error_count"] == 0 for position in fallback_positions)
        assert len(projected_prospects) == 4
        assert [prospect["siret"] for prospect in projected_prospects] == [
            "12345678901234",
            "55555555555555",
            "66666666666666",
            "98765432109876",
        ]
        assert all(prospect["legal_name"] == "Société exemple" for prospect in projected_prospects)
        assert all(prospect["organization_state"] == "ACTIVE" for prospect in projected_prospects)
        assert all(prospect["organization_diffusion"] == "FULL" for prospect in projected_prospects)
        assert all(prospect["activity_code"] == "10.71C" for prospect in projected_prospects)
        assert all(
            prospect["activity_nomenclature"] == "NAFRev2" for prospect in projected_prospects
        )
        assert all(prospect["employee_band"] == "12" for prospect in projected_prospects)
        assert all(prospect["employee_scope"] == "LOCAL" for prospect in projected_prospects)
        assert all(prospect["establishment_state"] == "ACTIVE" for prospect in projected_prospects)
        assert all(
            prospect["source_display_name"] == "Atelier public" for prospect in projected_prospects
        )
        assert all(prospect["eligibility"] == "ELIGIBLE" for prospect in projected_prospects)
        assert all(prospect["hidden_at"] is None for prospect in projected_prospects)
        assert all(prospect["municipality_code"] == "40088" for prospect in projected_prospects)
        assert all(prospect["binding_state"] == "CURRENT" for prospect in projected_prospects)
        assert all(prospect["identity_linked"] is True for prospect in projected_prospects)
        projected_by_siret = {prospect["siret"]: prospect for prospect in projected_prospects}
        assert projected_by_siret["12345678901234"]["position_origin"] == "SIRENE_API"
        assert projected_by_siret["12345678901234"]["precision"] == "UNKNOWN"
        assert projected_by_siret["12345678901234"]["usability"] == "USABLE"
        assert projected_by_siret["12345678901234"]["has_point"] is True
        assert projected_by_siret["55555555555555"]["position_origin"] == "SIRENE_DATASET"
        assert projected_by_siret["55555555555555"]["precision"] == "STREET"
        assert projected_by_siret["66666666666666"]["usability"] == "MISSING"
        assert projected_by_siret["66666666666666"]["has_point"] is False
        assert projected_by_siret["98765432109876"]["position_origin"] == ("GEOPLATFORM_GEOCODER")
        assert projected_by_siret["98765432109876"]["precision"] == "ADDRESS"
        assert [tuple(row) for row in lineage_counts] == [
            ("PROSPECT_ACTIVITY", 4),
            ("PROSPECT_DISPLAY_NAME", 4),
            ("PROSPECT_EMPLOYEE_BAND", 4),
            ("PROSPECT_ORGANIZATION_TYPE", 4),
        ]
    finally:
        engine.dispose()
