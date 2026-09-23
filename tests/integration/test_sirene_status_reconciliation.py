"""PostgreSQL tests for explicit checks of known SIRET absent from discovery."""

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, create_engine, text

from radar.collections.contracts import CollectionProgress, ReservedCollection
from radar.persistence.sirene_status_reconciliation import (
    SqlAlchemySireneKnownStatusRepository,
)
from radar.prospects.status_reconciliation import SireneKnownStatusReconciliationService
from radar.providers.sirene import SireneEstablishmentStatus, SireneStatusLookup

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 23, 12, tzinfo=UTC)
DAX_LONGITUDE = -1.051952
DAX_LATITUDE = 43.70884


class FixtureStatusReader:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def lookup_establishment_statuses(
        self,
        sirets: Sequence[str],
        at_date: str,
    ) -> SireneStatusLookup:
        requested = tuple(sirets)
        self.calls.append((requested, at_date))
        statuses = (
            SireneEstablishmentStatus(
                requested[0], requested[0][:9], "ACTIVE", "ACTIVE", "FULL", "FULL"
            ),
            SireneEstablishmentStatus(
                requested[1], requested[1][:9], "CLOSED", "ACTIVE", "FULL", "FULL"
            ),
            SireneEstablishmentStatus(
                requested[2], requested[2][:9], "ACTIVE", "CEASED", "FULL", "FULL"
            ),
        )
        return SireneStatusLookup(requested, statuses, (requested[3],))


class FixtureReporter:
    def __init__(self) -> None:
        self.progress: list[CollectionProgress] = []

    def update(
        self,
        progress: CollectionProgress,
        checkpoint: Mapping[str, object] | None = None,
    ) -> None:
        del checkpoint
        self.progress.append(progress)


def _seed_collection(connection: Connection) -> tuple[ReservedCollection, UUID]:
    reference_id = uuid4()
    cycle_id = uuid4()
    job_id = uuid4()
    attempt_id = uuid4()
    release_id = uuid4()
    api_source_id = uuid4()
    batch_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO reference_position (
                id, input_address, normalized_label, structured_address, point,
                municipality_code, ban_id, result_type, score, provider_name,
                provider_url, geocoded_at, confirmed_at, country_code,
                is_metropolitan_france, created_at, updated_at
            ) VALUES (
                :id, 'Mairie de Dax', 'Mairie de Dax', '{}'::jsonb,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                '40088', NULL, 'housenumber', 1, 'fixture', 'https://example.test',
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
                id, connector, trigger, result, adapter_version,
                configuration_fingerprint, reference_position_id, center,
                collection_radius_meters, schedule_timezone, requested_at,
                started_at, finished_at, counters, error, request_fingerprint
            ) VALUES (
                :id, 'SIRENE', 'MANUAL', NULL, 'sirene-test', :fingerprint,
                :reference_id,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                50000, 'Europe/Paris', :now, :now, NULL, '{}'::jsonb, NULL, :fingerprint
            )
            """
        ),
        {
            "id": cycle_id,
            "reference_id": reference_id,
            "longitude": DAX_LONGITUDE,
            "latitude": DAX_LATITUDE,
            "now": NOW,
            "fingerprint": "a" * 64,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO collection_job (
                id, cycle_id, connector, trigger, scheduled_for, state,
                created_at, available_at, started_at, finished_at, attempt_count,
                max_attempts, lease_owner, lease_expires_at, heartbeat_at, progress,
                last_safe_checkpoint, last_error, request_fingerprint
            ) VALUES (
                :id, :cycle_id, 'SIRENE', 'MANUAL', NULL, 'RUNNING',
                :now, :now, :now, NULL, 1, 3, 'fixture-worker', :lease_expires,
                :now, '{}'::jsonb, NULL, NULL, :fingerprint
            )
            """
        ),
        {
            "id": job_id,
            "cycle_id": cycle_id,
            "now": NOW,
            "lease_expires": NOW + timedelta(minutes=5),
            "fingerprint": "b" * 64,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO collection_attempt (
                id, collection_job_id, attempt_number, worker_id, started_at,
                heartbeat_at, finished_at, result, last_safe_checkpoint, error
            ) VALUES (
                :id, :job_id, 1, 'fixture-worker', :now, :now, NULL, NULL, NULL, NULL
            )
            """
        ),
        {"id": attempt_id, "job_id": job_id, "now": NOW},
    )
    connection.execute(
        text(
            """
            INSERT INTO dataset_release (
                id, source_name, dataset_code, resource_identifier, resource_url,
                published_on, retrieved_at, file_size_bytes, digest_algorithm,
                file_digest, expected_schema, status, license_name, metadata,
                created_at, updated_at
            ) VALUES (
                :id, 'fixture', 'communes-fixture', 'communes-2026',
                'https://example.test/communes.geojson', NULL, :now, 1, 'SHA-256',
                :digest, '{}'::jsonb, 'ACTIVE', 'ODbL-1.0', '{}'::jsonb, :now, :now
            )
            """
        ),
        {"id": release_id, "now": NOW, "digest": "c" * 64},
    )
    connection.execute(
        text(
            """
            INSERT INTO commune_boundary (
                dataset_release_id, municipality_code, official_name, boundary,
                is_metropolitan_france
            ) VALUES (
                :release_id, '40088', 'Dax',
                ST_Multi(ST_GeomFromText(
                    'POLYGON((-1.2 43.6,-0.9 43.6,-0.9 43.9,-1.2 43.9,-1.2 43.6))',
                    4326
                )),
                TRUE
            )
            """
        ),
        {"release_id": release_id},
    )
    source_rows = [
        {
            "id": api_source_id,
            "source": "SIRENE_API",
            "contract": "sirene-api-fixture",
        },
        {
            "id": uuid4(),
            "source": "SIRENE_GEOLOCATION",
            "contract": "sirene-file-fixture",
        },
        {
            "id": uuid4(),
            "source": "GEOPLATFORM_GEOCODER",
            "contract": "geocoder-fixture",
        },
    ]
    connection.execute(
        text(
            """
            INSERT INTO collection_source_run (
                id, collection_cycle_id, source, dataset_release_id, freshness_at,
                started_at, finished_at, status, counters, metadata, request_count,
                retry_count, error_count, contract_version, created_at, updated_at
            ) VALUES (
                :id, :cycle_id, :source, NULL, NULL, :now, :now, 'SUCCEEDED',
                '{}'::jsonb, '{}'::jsonb, 1, 0, 0, :contract, :now, :now
            )
            """
        ),
        [{**row, "cycle_id": cycle_id, "now": NOW} for row in source_rows],
    )
    connection.execute(
        text(
            """
            INSERT INTO collection_batch (
                id, collection_cycle_id, source_run_id, last_collection_attempt_id,
                batch_type, batch_key, order_number, state, attempt_count, started_at,
                finished_at, announced_total, received_count, unique_identifier_count,
                resume_state, processing_counts, error, created_at, updated_at
            ) VALUES (
                :id, :cycle_id, :source_id, :attempt_id, 'SIRENE_MUNICIPALITIES',
                'municipalities:1', 1, 'SUCCEEDED', 1, :now, :now, 0, 0, 0,
                '{}'::jsonb, '{}'::jsonb, NULL, :now, :now
            )
            """
        ),
        {
            "id": batch_id,
            "cycle_id": cycle_id,
            "source_id": api_source_id,
            "attempt_id": attempt_id,
            "now": NOW,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO collection_cycle_commune (
                collection_cycle_id, dataset_release_id, municipality_code,
                collection_batch_id, selection_reason, selection_margin_meters,
                state, created_at, updated_at
            ) VALUES (
                :cycle_id, :release_id, '40088', :batch_id,
                'COLLECTION_RADIUS_PLUS_MARGIN', 1000, 'SUCCEEDED', :now, :now
            )
            """
        ),
        {
            "cycle_id": cycle_id,
            "release_id": release_id,
            "batch_id": batch_id,
            "now": NOW,
        },
    )
    return (
        ReservedCollection(
            job_id=job_id,
            cycle_id=cycle_id,
            attempt_id=attempt_id,
            attempt_number=1,
            max_attempts=3,
            connector="SIRENE",
            longitude=DAX_LONGITUDE,
            latitude=DAX_LATITUDE,
            collection_radius_meters=50_000,
            last_safe_checkpoint=None,
        ),
        cycle_id,
    )


def _seed_prospect(
    connection: Connection,
    siret: str,
    municipality_code: str,
    *,
    hidden: bool = False,
) -> tuple[UUID, UUID]:
    identity_id = uuid4()
    observation_id = uuid4()
    organization_id = uuid4()
    establishment_id = uuid4()
    opportunity_id = uuid4()
    binding_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO external_identity (
                id, authority, namespace, canonical_value, identifier_fingerprint,
                fingerprint_algorithm, first_observed_at, last_observed_at,
                restricted_at, organization_id, establishment_id, opportunity_id
            ) VALUES (
                :id, 'INSEE', 'SIRET', :siret, :fingerprint, 'SHA-256', :now, :now,
                NULL, NULL, NULL, NULL
            )
            """
        ),
        {
            "id": identity_id,
            "siret": siret,
            "fingerprint": hashlib.sha256(siret.encode()).hexdigest(),
            "now": NOW - timedelta(days=30),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO source_observation (
                id, data_source_code, external_identity_id, source_binding_id,
                collection_cycle_id, collection_batch_id, collection_page_id,
                dataset_release_id, retrieved_at, source_updated_at, adapter_version,
                schema_version, content_fingerprint, payload, source_reference,
                validation_status, normalization_error, redacted_at
            ) VALUES (
                :id, 'SIRENE_API', :identity_id, NULL, NULL, NULL, NULL, NULL,
                :observed_at, NULL, 'fixture', 'fixture', :fingerprint,
                jsonb_build_object('siret', CAST(:siret AS text)), NULL,
                'VALID', NULL, NULL
            )
            """
        ),
        {
            "id": observation_id,
            "identity_id": identity_id,
            "siret": siret,
            "observed_at": NOW - timedelta(days=30),
            "fingerprint": hashlib.sha256(f"prior:{siret}".encode()).hexdigest(),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO organization (
                id, siren, legal_name, usual_name, organization_type, legal_category,
                administrative_state, diffusion_status, current_observation_id,
                administrative_state_observation_id, diffusion_status_observation_id,
                first_observed_at, last_observed_at, created_at, updated_at
            ) VALUES (
                :id, :siren, :name, NULL, 'UNKNOWN', '5710', 'CEASED', 'FULL',
                :observation_id, :observation_id, :observation_id,
                :observed_at, :observed_at, :observed_at, :observed_at
            )
            """
        ),
        {
            "id": organization_id,
            "siren": siret[:9],
            "name": f"Organisation {siret}",
            "observation_id": observation_id,
            "observed_at": NOW - timedelta(days=30),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO establishment (
                id, organization_id, siret, is_head_office, source_names,
                activity_code, activity_nomenclature, activity_label, employee_band,
                employee_year, employee_scope, administrative_state, diffusion_status,
                established_on, current_period_started_on, source_processed_at,
                current_observation_id, administrative_state_observation_id,
                diffusion_status_observation_id, first_observed_at, last_observed_at,
                created_at, updated_at
            ) VALUES (
                :id, :organization_id, :siret, FALSE, '[]'::jsonb,
                NULL, NULL, NULL, NULL, NULL, 'UNKNOWN', 'CLOSED', 'FULL',
                NULL, NULL, NULL, :observation_id, :observation_id, :observation_id,
                :observed_at, :observed_at, :observed_at, :observed_at
            )
            """
        ),
        {
            "id": establishment_id,
            "organization_id": organization_id,
            "siret": siret,
            "observation_id": observation_id,
            "observed_at": NOW - timedelta(days=30),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO opportunity (
                id, kind, creation_origin, hidden_at, hidden_reason,
                duplicate_of_opportunity_id, created_at, updated_at
            ) VALUES (
                :id, 'PROSPECT', 'SOURCE', :hidden_at, :hidden_reason,
                NULL, :observed_at, :observed_at
            )
            """
        ),
        {
            "id": opportunity_id,
            "hidden_at": NOW - timedelta(days=2) if hidden else None,
            "hidden_reason": "NOT_RELEVANT" if hidden else None,
            "observed_at": NOW - timedelta(days=30),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO prospect (
                id, establishment_id, source_display_name, source_description,
                source_organization_type, source_business_signals, eligibility,
                eligibility_changed_at, eligibility_reason, first_observed_at,
                last_observed_at, created_at, updated_at
            ) VALUES (
                :id, :establishment_id, :name, NULL, 'UNKNOWN', '{}'::jsonb,
                'UNKNOWN', :observed_at, 'FIXTURE_UNKNOWN', :observed_at,
                :observed_at, :observed_at, :observed_at
            )
            """
        ),
        {
            "id": opportunity_id,
            "establishment_id": establishment_id,
            "name": f"Prospect {siret}",
            "observed_at": NOW - timedelta(days=30),
        },
    )
    connection.execute(
        text(
            """
            UPDATE external_identity
            SET establishment_id = :establishment_id
            WHERE id = :identity_id
            """
        ),
        {"establishment_id": establishment_id, "identity_id": identity_id},
    )
    connection.execute(
        text(
            """
            INSERT INTO source_binding (
                id, data_source_code, external_identity_id, opportunity_id,
                source_url, producer_name, first_observed_at, last_observed_at,
                current_observation_id, state, consecutive_absence_count,
                last_checked_at, created_at, updated_at
            ) VALUES (
                :id, 'SIRENE_API', :identity_id, :opportunity_id, NULL, 'INSEE',
                :observed_at, :observed_at, :observation_id, 'CURRENT', 0,
                :observed_at, :observed_at, :observed_at
            )
            """
        ),
        {
            "id": binding_id,
            "identity_id": identity_id,
            "opportunity_id": opportunity_id,
            "observation_id": observation_id,
            "observed_at": NOW - timedelta(days=30),
        },
    )
    connection.execute(
        text("UPDATE source_observation SET source_binding_id = :binding_id WHERE id = :id"),
        {"binding_id": binding_id, "id": observation_id},
    )
    connection.execute(
        text(
            """
            INSERT INTO location_assertion (
                id, opportunity_id, layer, full_address, structured_address,
                municipality_code, postcode, country_code, point, position_origin,
                source_crs, quality_code, match_score, precision, usability,
                address_observation_id, position_observation_id, dataset_release_id,
                candidate_position_id, rule_version, diagnostics, is_current,
                created_at, retired_at, updated_at
            ) VALUES (
                gen_random_uuid(), :opportunity_id, 'SOURCE', 'Dax', '{}'::jsonb,
                :municipality_code, '40100', 'FR',
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                'SIRENE_API', 'EPSG:4326', NULL, NULL, 'UNKNOWN', 'USABLE',
                :observation_id, :observation_id, NULL, NULL, 'fixture', '{}'::jsonb,
                TRUE, :observed_at, NULL, :observed_at
            )
            """
        ),
        {
            "opportunity_id": opportunity_id,
            "municipality_code": municipality_code,
            "longitude": DAX_LONGITUDE,
            "latitude": DAX_LATITUDE,
            "observation_id": observation_id,
            "observed_at": NOW - timedelta(days=30),
        },
    )
    return opportunity_id, binding_id


def test_checks_only_known_absences_and_applies_explicit_states_idempotently(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    reader = FixtureStatusReader()
    reporter = FixtureReporter()
    try:
        with engine.begin() as connection:
            reservation, cycle_id = _seed_collection(connection)
            active_opportunity, _ = _seed_prospect(
                connection,
                "11111111111111",
                "40088",
                hidden=True,
            )
            _seed_prospect(connection, "22222222222222", "40088")
            _seed_prospect(connection, "33333333333333", "40088")
            _, missing_binding = _seed_prospect(connection, "44444444444444", "40088")
            _, seen_binding = _seed_prospect(connection, "55555555555555", "40088")
            _seed_prospect(connection, "66666666666666", "40100")
            current_observation = connection.execute(
                text("SELECT current_observation_id FROM source_binding WHERE id = :binding_id"),
                {"binding_id": seen_binding},
            ).scalar_one()
            connection.execute(
                text(
                    """
                    INSERT INTO source_sighting (
                        source_binding_id, collection_cycle_id, source_observation_id, seen_at
                    ) VALUES (:binding_id, :cycle_id, :observation_id, :now)
                    """
                ),
                {
                    "binding_id": seen_binding,
                    "cycle_id": cycle_id,
                    "observation_id": current_observation,
                    "now": NOW,
                },
            )
            contact_set_id = uuid4()
            connection.execute(
                text(
                    """
                    INSERT INTO contact_set (
                        id, opportunity_id, layer, source_observation_id,
                        is_current, created_at, retired_at
                    ) VALUES (:id, :opportunity_id, 'USER', NULL, TRUE, :now, NULL)
                    """
                ),
                {"id": contact_set_id, "opportunity_id": active_opportunity, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO contact_point (
                        id, contact_set_id, type, display_value, normalized_value,
                        scope, label, source_reference, display_order, created_at
                    ) VALUES (
                        gen_random_uuid(), :set_id, 'EMAIL', 'contact@example.test',
                        'contact@example.test', 'LOCAL', NULL, NULL, 0, :now
                    )
                    """
                ),
                {"set_id": contact_set_id, "now": NOW},
            )

        service = SireneKnownStatusReconciliationService(
            SqlAlchemySireneKnownStatusRepository(engine),
            reader,
            clock=lambda: NOW,
        )
        summary = service.reconcile(reservation, reporter)
        repeated = service.reconcile(reservation, reporter)

        assert summary.checked_count == 4
        assert summary.active_count == 1
        assert summary.closed_count == 1
        assert summary.ceased_count == 1
        assert summary.not_found_count == 1
        assert repeated == summary
        assert reader.calls == [
            (
                (
                    "11111111111111",
                    "22222222222222",
                    "33333333333333",
                    "44444444444444",
                ),
                "2026-09-23",
            )
        ]

        with engine.connect() as connection:
            states = (
                connection.execute(
                    text(
                        """
                    SELECT establishment.siret,
                           establishment.administrative_state AS establishment_state,
                           organization.administrative_state AS organization_state,
                           prospect.eligibility,
                           opportunity.hidden_at IS NOT NULL AS hidden
                    FROM prospect
                    JOIN opportunity ON opportunity.id = prospect.id
                    JOIN establishment ON establishment.id = prospect.establishment_id
                    JOIN organization ON organization.id = establishment.organization_id
                    ORDER BY establishment.siret
                    """
                    )
                )
                .mappings()
                .all()
            )
            outcomes = connection.execute(
                text(
                    """
                    SELECT identity.canonical_value, checked.outcome,
                           checked.source_observation_id IS NOT NULL AS has_observation
                    FROM sirene_known_status_check AS checked
                    JOIN external_identity AS identity
                      ON identity.id = checked.external_identity_id
                    ORDER BY identity.canonical_value
                    """
                )
            ).all()
            source = (
                connection.execute(
                    text(
                        """
                    SELECT status, request_count, retry_count, error_count, counters
                    FROM collection_source_run
                    WHERE collection_cycle_id = :cycle_id
                      AND source = 'SIRENE_KNOWN_STATUS'
                    """
                    ),
                    {"cycle_id": cycle_id},
                )
                .mappings()
                .one()
            )
            missing_binding_state = (
                connection.execute(
                    text(
                        """
                    SELECT state, consecutive_absence_count, last_checked_at
                    FROM source_binding WHERE id = :binding_id
                    """
                    ),
                    {"binding_id": missing_binding},
                )
                .mappings()
                .one()
            )
            preserved = (
                connection.execute(
                    text(
                        """
                    SELECT
                        (SELECT count(*) FROM opportunity) AS opportunities,
                        (SELECT count(*) FROM prospect) AS prospects,
                        (SELECT count(*) FROM contact_set WHERE layer = 'USER') AS user_sets,
                        (SELECT count(*) FROM contact_point) AS contact_points,
                        (SELECT count(*) FROM source_sighting
                         WHERE collection_cycle_id = :cycle_id) AS sightings
                    """
                    ),
                    {"cycle_id": cycle_id},
                )
                .mappings()
                .one()
            )

        by_siret = {row["siret"]: row for row in states}
        assert by_siret["11111111111111"]["establishment_state"] == "ACTIVE"
        assert by_siret["11111111111111"]["organization_state"] == "ACTIVE"
        assert by_siret["11111111111111"]["eligibility"] == "ELIGIBLE"
        assert by_siret["11111111111111"]["hidden"] is True
        assert by_siret["22222222222222"]["establishment_state"] == "CLOSED"
        assert by_siret["22222222222222"]["organization_state"] == "ACTIVE"
        assert by_siret["33333333333333"]["organization_state"] == "CEASED"
        assert by_siret["44444444444444"]["establishment_state"] == "CLOSED"
        assert by_siret["55555555555555"]["establishment_state"] == "CLOSED"
        assert by_siret["66666666666666"]["establishment_state"] == "CLOSED"
        assert [tuple(row) for row in outcomes] == [
            ("11111111111111", "ACTIVE", True),
            ("22222222222222", "CLOSED", True),
            ("33333333333333", "CEASED", True),
            ("44444444444444", "NOT_FOUND", False),
        ]
        assert source["status"] == "SUCCEEDED"
        assert source["request_count"] == 1
        assert source["retry_count"] == 0
        assert source["error_count"] == 0
        assert source["counters"]["checked_count"] == 4
        assert missing_binding_state["state"] == "CURRENT"
        assert missing_binding_state["consecutive_absence_count"] == 1
        assert missing_binding_state["last_checked_at"] == NOW
        assert dict(preserved) == {
            "opportunities": 6,
            "prospects": 6,
            "user_sets": 1,
            "contact_points": 1,
            "sightings": 4,
        }
    finally:
        engine.dispose()
