"""PostGIS staging tests for normalized DATAtourisme candidate pages."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from radar.collections.contracts import ReservedCollection
from radar.events.contracts import (
    EventAddressCandidate,
    EventCandidate,
    EventLocationCandidate,
    EventPeriodCandidate,
)
from radar.events.staging import EventCandidatePageStager
from radar.persistence.datatourisme_staging import (
    SqlAlchemyEventCandidateStagingRepository,
)
from radar.providers.datatourisme import DatatourismePage

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
DAX_LONGITUDE = -1.051952
DAX_LATITUDE = 43.70884


def seed_running_collection(
    engine: Engine,
) -> tuple[ReservedCollection, UUID]:
    reference_id = uuid4()
    cycle_id = uuid4()
    job_id = uuid4()
    attempt_id = uuid4()
    source_run_id = uuid4()
    batch_id = uuid4()
    release_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO reference_position (
                    id, input_address, normalized_label, structured_address,
                    point, municipality_code, provider_name, provider_url,
                    geocoded_at, confirmed_at, country_code,
                    is_metropolitan_france, created_at, updated_at
                ) VALUES (
                    :id, 'Mairie de Dax', 'Mairie de Dax', '{}'::jsonb,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                    '40088', 'GEOPLATFORM', 'https://data.geopf.fr',
                    :now, :now, 'FR', TRUE, :now, :now
                )
                """
            ),
            {
                "id": reference_id,
                "longitude": DAX_LONGITUDE,
                "latitude": DAX_LATITUDE,
                "now": NOW,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO collection_cycle (
                    id, connector, trigger, adapter_version,
                    configuration_fingerprint, reference_position_id,
                    center, collection_radius_meters, schedule_timezone,
                    requested_at, started_at, counters, request_fingerprint
                ) VALUES (
                    :id, 'DATATOURISME', 'MANUAL', 'datatourisme-v1-events-v1',
                    :fingerprint, :reference_id,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                    50000, 'Europe/Paris', :now, :now, '{}'::jsonb, :fingerprint
                )
                """
            ),
            {
                "id": cycle_id,
                "reference_id": reference_id,
                "longitude": DAX_LONGITUDE,
                "latitude": DAX_LATITUDE,
                "fingerprint": "c" * 64,
                "now": NOW,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO collection_job (
                    id, cycle_id, connector, trigger, state, created_at,
                    available_at, started_at, attempt_count, max_attempts,
                    lease_owner, lease_expires_at, heartbeat_at,
                    progress, request_fingerprint
                ) VALUES (
                    :id, :cycle_id, 'DATATOURISME', 'MANUAL', 'RUNNING',
                    :now, :now, :now, 1, 3, 'test-worker',
                    :lease_expires_at, :now, '{"stage": "events"}'::jsonb,
                    :fingerprint
                )
                """
            ),
            {
                "id": job_id,
                "cycle_id": cycle_id,
                "now": NOW,
                "lease_expires_at": datetime(2026, 10, 1, 13, tzinfo=UTC),
                "fingerprint": "c" * 64,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO collection_attempt (
                    id, collection_job_id, attempt_number, worker_id,
                    started_at, heartbeat_at
                ) VALUES (
                    :id, :job_id, 1, 'test-worker', :now, :now
                )
                """
            ),
            {"id": attempt_id, "job_id": job_id, "now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO collection_source_run (
                    id, collection_cycle_id, source, started_at, status,
                    counters, metadata, request_count, retry_count,
                    error_count, contract_version, created_at, updated_at
                ) VALUES (
                    :id, :cycle_id, 'DATATOURISME_API', :now, 'RUNNING',
                    '{}'::jsonb, '{}'::jsonb, 0, 0, 0,
                    'datatourisme-v1-events-v1', :now, :now
                )
                """
            ),
            {"id": source_run_id, "cycle_id": cycle_id, "now": NOW},
        )
        connection.execute(
            text(
                """
                INSERT INTO collection_batch (
                    id, collection_cycle_id, source_run_id,
                    last_collection_attempt_id, batch_type, batch_key,
                    order_number, state, attempt_count, started_at,
                    resume_state, processing_counts, created_at, updated_at
                ) VALUES (
                    :id, :cycle_id, :source_run_id, :attempt_id,
                    'DATATOURISME_EVENTS', 'events', 1, 'RUNNING', 1, :now,
                    '{}'::jsonb, '{}'::jsonb, :now, :now
                )
                """
            ),
            {
                "id": batch_id,
                "cycle_id": cycle_id,
                "source_run_id": source_run_id,
                "attempt_id": attempt_id,
                "now": NOW,
            },
        )
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
                    'test-metropolitan-boundary', 'https://example.test/communes.geojson',
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
    return (
        ReservedCollection(
            job_id=job_id,
            cycle_id=cycle_id,
            attempt_id=attempt_id,
            attempt_number=1,
            max_attempts=3,
            connector="DATATOURISME",
            longitude=DAX_LONGITUDE,
            latitude=DAX_LATITUDE,
            collection_radius_meters=50_000,
            last_safe_checkpoint=None,
        ),
        batch_id,
    )


def candidate(
    number: int,
    *,
    longitude: float | None = DAX_LONGITUDE,
    latitude: float | None = DAX_LATITUDE,
    periods: tuple[EventPeriodCandidate, ...] | None = None,
) -> EventCandidate:
    identifier = str(UUID(int=number))
    return EventCandidate(
        external_identifier=identifier,
        source_uri=f"https://data.datatourisme.fr/{identifier}",
        producer_identifier=f"source-{number}",
        title=f"Événement {number}",
        types=("EntertainmentAndEvent",),
        descriptions=(),
        locations=(
            EventLocationCandidate(
                longitude,
                latitude,
                (
                    EventAddressCandidate(
                        ("Place de la Mairie",),
                        "40100",
                        "Dax",
                        "40088",
                    ),
                ),
            ),
        ),
        periods=(
            periods
            if periods is not None
            else (EventPeriodCandidate("2027-07-12", None, None, None),)
        ),
        contacts=(),
        source_parties=(),
        source_updated_at="2026-09-29T12:00:00+00:00",
        aggregator_updated_at="2026-09-29T13:00:00+00:00",
        source_obsolete=None,
    )


def test_stages_revisions_idempotently_with_exact_postgis_classification(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reservation, batch_id = seed_running_collection(engine)
    candidates = (
        candidate(1),
        candidate(2, longitude=-0.4),
        candidate(3, longitude=-2.5, latitude=42.8),
        candidate(4, longitude=None, latitude=None),
        candidate(
            5,
            periods=(EventPeriodCandidate("invalid", None, None, None),),
        ),
        candidate(
            6,
            periods=(EventPeriodCandidate("2026-09-01", None, None, None),),
        ),
    )
    page = DatatourismePage(
        number=1,
        announced_total=len(candidates),
        announced_total_pages=1,
        received_count=len(candidates),
        importable_candidates=candidates,
        rejection_counts={},
        next_link_fingerprint=None,
        terminal=True,
    )
    stager = EventCandidatePageStager(
        SqlAlchemyEventCandidateStagingRepository(engine),
        clock=lambda: NOW,
    )
    try:
        stager.handle(reservation, batch_id, page)
        stager.handle(reservation, batch_id, page)

        with engine.connect() as connection:
            counts = (
                connection.execute(
                    text(
                        """
                    SELECT
                        (SELECT count(*) FROM external_identity
                         WHERE namespace = 'DATATOURISME_UUID') AS identities,
                        (SELECT count(*) FROM source_observation
                         WHERE data_source_code = 'DATATOURISME_API') AS observations,
                        (SELECT count(*) FROM collection_item
                         WHERE collection_cycle_id = :cycle_id) AS items
                    """
                    ),
                    {"cycle_id": reservation.cycle_id},
                )
                .mappings()
                .one()
            )
            items = (
                connection.execute(
                    text(
                        """
                    SELECT
                        identifier_value,
                        normalization_result,
                        geographic_classification,
                        decision,
                        reason ->> 'code' AS reason_code,
                        distance_meters
                    FROM collection_item
                    WHERE collection_cycle_id = :cycle_id
                    ORDER BY item_rank
                    """
                    ),
                    {"cycle_id": reservation.cycle_id},
                )
                .mappings()
                .all()
            )
            observations = (
                connection.execute(
                    text(
                        """
                    SELECT validation_status, normalization_error
                    FROM source_observation
                    WHERE data_source_code = 'DATATOURISME_API'
                    ORDER BY payload ->> 'title'
                    """
                    )
                )
                .mappings()
                .all()
            )
    finally:
        engine.dispose()

    assert counts == {"identities": 6, "observations": 6, "items": 6}
    assert [item["geographic_classification"] for item in items] == [
        "IN_RADIUS",
        "OUTSIDE_RADIUS",
        "OUTSIDE_METROPOLITAN_FRANCE",
        "LOCATION_UNKNOWN",
        "IN_RADIUS",
        "IN_RADIUS",
    ]
    assert [item["decision"] for item in items] == [
        None,
        "COUNTED_ONLY",
        "COUNTED_ONLY",
        "REJECTED",
        "REJECTED",
        None,
    ]
    assert [item["reason_code"] for item in items] == [
        "READY_FOR_PROJECTION",
        "OUTSIDE_RADIUS",
        "OUTSIDE_METROPOLITAN_FRANCE",
        "LOCATION_MISSING",
        "NO_VALID_PERIOD",
        "PAST_ONLY",
    ]
    assert items[0]["distance_meters"] == pytest.approx(0)
    assert items[1]["distance_meters"] > 50_000
    assert [observation["validation_status"] for observation in observations].count("REJECTED") == 1
    rejected = next(
        observation
        for observation in observations
        if observation["validation_status"] == "REJECTED"
    )
    assert rejected["normalization_error"]["code"] == "NO_VALID_PERIOD"
