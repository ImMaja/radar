"""PostgreSQL/PostGIS integration tests for local prospect catalogue reads."""

import json
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from radar.geography.contracts import GeocodedAddress, StructuredAddress
from radar.persistence.geography import SqlAlchemyGeographyRepository
from radar.persistence.prospect_catalog import SqlAlchemyProspectCatalogRepository
from radar.prospects.catalog import ProspectSearch

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
DAX_LONGITUDE = -1.051952
DAX_LATITUDE = 43.70884


def _confirm_dax(engine: Engine) -> None:
    geography = SqlAlchemyGeographyRepository(engine)
    candidate = geography.save_candidate(
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
    geography.confirm_candidate(candidate.id, NOW)
    geography.update_radii(50_000, 30_000, NOW)


def _insert_prospect(
    engine: Engine,
    *,
    rank: int,
    display_name: str,
    municipality: str,
    municipality_code: str,
    longitude: float | None,
    latitude: float | None,
    activity_code: str = "10.71C",
    employee_band: str = "12",
    organization_type: str = "UNKNOWN",
    hidden: bool = False,
    closed: bool = False,
) -> UUID:
    opportunity_id = uuid4()
    organization_id = uuid4()
    establishment_id = uuid4()
    siret = f"{rank:014d}"
    siren = f"{rank:09d}"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO opportunity (
                    id, kind, creation_origin, hidden_at, hidden_reason,
                    duplicate_of_opportunity_id, created_at, updated_at
                ) VALUES (
                    :opportunity_id, 'PROSPECT', 'SOURCE', :hidden_at, :hidden_reason,
                    NULL, :now, :now
                )
                """
            ),
            {
                "opportunity_id": opportunity_id,
                "hidden_at": NOW if hidden else None,
                "hidden_reason": "NOT_RELEVANT" if hidden else None,
                "now": NOW,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO organization (
                    id, siren, legal_name, usual_name, organization_type,
                    legal_category, administrative_state, diffusion_status,
                    current_observation_id, administrative_state_observation_id,
                    diffusion_status_observation_id, first_observed_at,
                    last_observed_at, created_at, updated_at
                ) VALUES (
                    :organization_id, :siren, :legal_name, NULL, :organization_type,
                    '5710', 'ACTIVE', 'FULL', NULL, NULL, NULL, :now, :now, :now, :now
                )
                """
            ),
            {
                "organization_id": organization_id,
                "siren": siren,
                "legal_name": f"Société {display_name}",
                "organization_type": organization_type,
                "now": NOW,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO establishment (
                    id, organization_id, siret, is_head_office, source_names,
                    activity_code, activity_nomenclature, activity_label,
                    employee_band, employee_year, employee_scope,
                    administrative_state, diffusion_status, established_on,
                    current_period_started_on, source_processed_at,
                    current_observation_id, administrative_state_observation_id,
                    diffusion_status_observation_id, first_observed_at,
                    last_observed_at, created_at, updated_at
                ) VALUES (
                    :establishment_id, :organization_id, :siret, FALSE,
                    CAST(:source_names AS jsonb), :activity_code, 'NAFRev2', NULL,
                    :employee_band, 2024, 'LOCAL', :administrative_state, 'FULL',
                    :established_on, :period_started_on, '2026-09-22T10:00:00',
                    NULL, NULL, NULL, :now, :now, :now, :now
                )
                """
            ),
            {
                "establishment_id": establishment_id,
                "organization_id": organization_id,
                "siret": siret,
                "source_names": json.dumps([display_name]),
                "activity_code": activity_code,
                "employee_band": employee_band,
                "administrative_state": "CLOSED" if closed else "ACTIVE",
                "established_on": date(2020, 1, 2),
                "period_started_on": date(2024, 3, 4),
                "now": NOW,
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
                    :opportunity_id, :establishment_id, :display_name, NULL,
                    :organization_type, '{}'::jsonb, 'ELIGIBLE', :now,
                    'SIRENE_FULL_PUBLIC_DIFFUSION', :now, :now, :now, :now
                )
                """
            ),
            {
                "opportunity_id": opportunity_id,
                "establishment_id": establishment_id,
                "display_name": display_name,
                "organization_type": organization_type,
                "now": NOW,
            },
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
                    :id, :opportunity_id, 'SOURCE', :full_address,
                    CAST(:structured_address AS jsonb), :municipality_code, '40100', 'FR',
                    CASE WHEN CAST(:longitude AS double precision) IS NULL THEN NULL
                         ELSE ST_SetSRID(
                             ST_MakePoint(:longitude, :latitude), 4326
                         )::geography
                    END,
                    'SIRENE_API', 'EPSG:4326', NULL, NULL, 'UNKNOWN', :usability,
                    NULL, NULL, NULL, NULL, 'sirene-position-resolution-v1',
                    '{}'::jsonb, TRUE, :now, NULL, :now
                )
                """
            ),
            {
                "id": uuid4(),
                "opportunity_id": opportunity_id,
                "full_address": f"1 RUE EXEMPLE 40100 {municipality}",
                "structured_address": json.dumps(
                    {
                        "street_number": "1",
                        "street_type": "RUE",
                        "street_label": "EXEMPLE",
                        "postcode": "40100",
                        "municipality_label": municipality,
                        "municipality_code": municipality_code,
                    }
                ),
                "municipality_code": municipality_code,
                "longitude": longitude,
                "latitude": latitude,
                "usability": "USABLE" if longitude is not None else "MISSING",
                "now": NOW,
            },
        )
    return opportunity_id


def _attach_sirene_provenance(engine: Engine, prospect_id: UUID) -> UUID:
    identity_id = uuid4()
    observation_id = uuid4()
    binding_id = uuid4()
    with engine.begin() as connection:
        establishment_id = connection.execute(
            text("SELECT establishment_id FROM prospect WHERE id = :id"),
            {"id": prospect_id},
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO external_identity (
                    id, authority, namespace, canonical_value, identifier_fingerprint,
                    fingerprint_algorithm, first_observed_at, last_observed_at,
                    restricted_at, organization_id, establishment_id, opportunity_id
                ) VALUES (
                    :id, 'INSEE', 'SIRET', '00000000000001', :fingerprint,
                    'SHA-256', :now, :now, NULL, NULL, :establishment_id, NULL
                )
                """
            ),
            {
                "id": identity_id,
                "fingerprint": "a" * 64,
                "now": NOW,
                "establishment_id": establishment_id,
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
                    :now, :now, 'sirene-3.11-v1', 'sirene-establishment-v1',
                    :fingerprint, '{}'::jsonb, NULL, 'VALID', NULL, NULL
                )
                """
            ),
            {
                "id": observation_id,
                "identity_id": identity_id,
                "now": NOW,
                "fingerprint": "b" * 64,
            },
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
                    :id, 'SIRENE_API', :identity_id, :prospect_id, NULL, 'INSEE',
                    :now, :now, :observation_id, 'CURRENT', 0, :now, :now, :now
                )
                """
            ),
            {
                "id": binding_id,
                "identity_id": identity_id,
                "prospect_id": prospect_id,
                "observation_id": observation_id,
                "now": NOW,
            },
        )
        connection.execute(
            text("UPDATE source_observation SET source_binding_id = :binding_id WHERE id = :id"),
            {"binding_id": binding_id, "id": observation_id},
        )
    return observation_id


def _attach_contacts(
    engine: Engine,
    prospect_id: UUID,
    *,
    layer: str,
    source_observation_id: UUID | None,
    contacts: tuple[tuple[str, str, str, str], ...],
) -> None:
    contact_set_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO contact_set (
                    id, opportunity_id, layer, source_observation_id,
                    is_current, created_at, retired_at
                ) VALUES (
                    :id, :opportunity_id, :layer, :source_observation_id,
                    TRUE, :now, NULL
                )
                """
            ),
            {
                "id": contact_set_id,
                "opportunity_id": prospect_id,
                "layer": layer,
                "source_observation_id": source_observation_id,
                "now": NOW,
            },
        )
        for display_order, (contact_type, display_value, normalized_value, scope) in enumerate(
            contacts
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO contact_point (
                        id, contact_set_id, type, display_value, normalized_value,
                        scope, label, source_reference, display_order, created_at
                    ) VALUES (
                        :id, :contact_set_id, :type, :display_value, :normalized_value,
                        :scope, :label, :source_reference, :display_order, :now
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "contact_set_id": contact_set_id,
                    "type": contact_type,
                    "display_value": display_value,
                    "normalized_value": normalized_value,
                    "scope": scope,
                    "label": "Accueil" if contact_type == "EMAIL" else None,
                    "source_reference": f"contacts.{contact_type.lower()}",
                    "display_order": display_order,
                    "now": NOW,
                },
            )


def test_catalog_filters_and_sorts_local_prospects_by_current_reference(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    repository = SqlAlchemyProspectCatalogRepository(engine)
    try:
        _confirm_dax(engine)
        alpha_id = _insert_prospect(
            engine,
            rank=1,
            display_name="Boulangerie Alpha",
            municipality="DAX",
            municipality_code="40088",
            longitude=DAX_LONGITUDE,
            latitude=DAX_LATITUDE,
        )
        alpha_observation_id = _attach_sirene_provenance(engine, alpha_id)
        _attach_contacts(
            engine,
            alpha_id,
            layer="SOURCE",
            source_observation_id=alpha_observation_id,
            contacts=(
                ("EMAIL", "bonjour@alpha.example", "bonjour@alpha.example", "LOCAL"),
                ("WEBSITE", "https://alpha.example", "https://alpha.example/", "CENTRAL"),
            ),
        )
        _insert_prospect(
            engine,
            rank=2,
            display_name="Entrepôt Beta",
            municipality="SAINT-VINCENT-DE-TYROSSE",
            municipality_code="40284",
            longitude=-1.3074,
            latitude=43.6607,
            activity_code="52.10B",
            employee_band="22",
            organization_type="COMPANY",
        )
        _insert_prospect(
            engine,
            rank=3,
            display_name="Commerce Bayonne",
            municipality="BAYONNE",
            municipality_code="64102",
            longitude=-1.4748,
            latitude=43.4933,
        )
        unknown_id = _insert_prospect(
            engine,
            rank=4,
            display_name="Adresse inconnue",
            municipality="DAX",
            municipality_code="40088",
            longitude=None,
            latitude=None,
        )
        _insert_prospect(
            engine,
            rank=5,
            display_name="Fiche masquée",
            municipality="DAX",
            municipality_code="40088",
            longitude=DAX_LONGITUDE,
            latitude=DAX_LATITUDE,
            hidden=True,
        )
        _insert_prospect(
            engine,
            rank=6,
            display_name="Site fermé",
            municipality="DAX",
            municipality_code="40088",
            longitude=DAX_LONGITUDE,
            latitude=DAX_LATITUDE,
            closed=True,
        )

        default_page = repository.search(ProspectSearch())
        assert default_page.applied_radius_meters == 30_000
        assert default_page.total == 2
        assert [item.display_name for item in default_page.items] == [
            "Boulangerie Alpha",
            "Entrepôt Beta",
        ]
        assert default_page.items[0].id == alpha_id
        assert default_page.items[0].has_email is True
        assert default_page.items[0].has_phone is False
        assert default_page.items[0].has_website is True
        assert default_page.items[0].distance_meters == pytest.approx(0, abs=0.01)
        assert 20_000 < cast_float(default_page.items[1].distance_meters) < 30_000

        expanded = repository.search(ProspectSearch(max_distance_meters=50_000))
        assert expanded.total == 3

        searched = repository.search(ProspectSearch(text="tyrosse"))
        assert [item.display_name for item in searched.items] == ["Entrepôt Beta"]

        escaped_wildcard = repository.search(ProspectSearch(text="%"))
        assert escaped_wildcard.total == 0

        filtered = repository.search(
            ProspectSearch(
                organization_type="COMPANY",
                activity_code="52.10B",
                employee_band="22",
            )
        )
        assert [item.display_name for item in filtered.items] == ["Entrepôt Beta"]

        with_email = repository.search(ProspectSearch(has_email=True))
        assert [item.id for item in with_email.items] == [alpha_id]

        with_email_and_website = repository.search(ProspectSearch(has_email=True, has_website=True))
        assert [item.id for item in with_email_and_website.items] == [alpha_id]

        with_phone = repository.search(ProspectSearch(has_phone=True))
        assert with_phone.total == 0

        to_verify = repository.search(ProspectSearch(location="to_verify", sort="name"))
        assert to_verify.total == 1
        assert to_verify.items[0].id == unknown_id
        assert to_verify.items[0].distance_meters is None

        beyond_last_page = repository.search(ProspectSearch(limit=1, offset=10))
        assert beyond_last_page.total == 2
        assert beyond_last_page.items == ()
    finally:
        engine.dispose()


def test_catalog_detail_exposes_current_source_provenance(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    repository = SqlAlchemyProspectCatalogRepository(engine)
    try:
        _confirm_dax(engine)
        prospect_id = _insert_prospect(
            engine,
            rank=1,
            display_name="Boulangerie Alpha",
            municipality="DAX",
            municipality_code="40088",
            longitude=DAX_LONGITUDE,
            latitude=DAX_LATITUDE,
        )
        observation_id = _attach_sirene_provenance(engine, prospect_id)
        _attach_contacts(
            engine,
            prospect_id,
            layer="SOURCE",
            source_observation_id=observation_id,
            contacts=(("EMAIL", "bonjour@example.fr", "bonjour@example.fr", "LOCAL"),),
        )

        detail = repository.get(prospect_id)

        assert detail.summary.display_name == "Boulangerie Alpha"
        assert detail.siret == "00000000000001"
        assert detail.siren == "000000001"
        assert detail.summary.address.municipality == "DAX"
        assert detail.longitude == pytest.approx(DAX_LONGITUDE)
        assert detail.summary.has_email is True
        assert detail.contacts[0].type == "EMAIL"
        assert detail.contacts[0].value == "bonjour@example.fr"
        assert detail.contacts[0].scope == "LOCAL"
        assert detail.contacts[0].label == "Accueil"
        assert detail.sources[0].code == "SIRENE_API"
        assert detail.sources[0].authority == "INSEE"
        assert detail.sources[0].retrieved_at == NOW
    finally:
        engine.dispose()


def test_user_contact_set_replaces_source_contacts_for_filters_and_detail(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    repository = SqlAlchemyProspectCatalogRepository(engine)
    try:
        _confirm_dax(engine)
        prospect_id = _insert_prospect(
            engine,
            rank=1,
            display_name="Boulangerie Alpha",
            municipality="DAX",
            municipality_code="40088",
            longitude=DAX_LONGITUDE,
            latitude=DAX_LATITUDE,
        )
        observation_id = _attach_sirene_provenance(engine, prospect_id)
        _attach_contacts(
            engine,
            prospect_id,
            layer="SOURCE",
            source_observation_id=observation_id,
            contacts=(("EMAIL", "source@example.fr", "source@example.fr", "LOCAL"),),
        )
        _attach_contacts(
            engine,
            prospect_id,
            layer="USER",
            source_observation_id=None,
            contacts=(("PHONE", "05 58 00 00 00", "+33558000000", "LOCAL"),),
        )

        assert repository.search(ProspectSearch(has_email=True)).total == 0
        phone_page = repository.search(ProspectSearch(has_phone=True))
        assert [item.id for item in phone_page.items] == [prospect_id]
        assert phone_page.items[0].has_email is False
        assert phone_page.items[0].has_phone is True

        detail = repository.get(prospect_id)
        assert [(contact.type, contact.value) for contact in detail.contacts] == [
            ("PHONE", "05 58 00 00 00")
        ]
    finally:
        engine.dispose()


def cast_float(value: float | None) -> float:
    assert value is not None
    return value
