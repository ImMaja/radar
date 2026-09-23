"""PostgreSQL/PostGIS reads for the local prospect catalogue."""

from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.prospects.catalog import (
    ProspectAddress,
    ProspectCatalogUnavailableError,
    ProspectContact,
    ProspectContactScope,
    ProspectContactType,
    ProspectDetail,
    ProspectLocationFilter,
    ProspectNotFoundError,
    ProspectPage,
    ProspectReferencePositionRequiredError,
    ProspectSearch,
    ProspectSource,
    ProspectSummary,
)

_EFFECTIVE_READ_CTES = """
effective_location AS (
    SELECT DISTINCT ON (location.opportunity_id)
        location.*
    FROM location_assertion AS location
    WHERE location.is_current
    ORDER BY
        location.opportunity_id,
        CASE location.layer WHEN 'USER' THEN 0 ELSE 1 END
),
effective_contact_set AS (
    SELECT DISTINCT ON (contact_set.opportunity_id)
        contact_set.id,
        contact_set.opportunity_id
    FROM contact_set
    WHERE contact_set.is_current
    ORDER BY
        contact_set.opportunity_id,
        CASE contact_set.layer WHEN 'USER' THEN 0 ELSE 1 END
),
effective_contacts AS (
    SELECT
        contact_set.opportunity_id,
        bool_or(contact.type = 'EMAIL') AS has_email,
        bool_or(contact.type = 'PHONE') AS has_phone,
        bool_or(contact.type = 'WEBSITE') AS has_website
    FROM effective_contact_set AS contact_set
    LEFT JOIN contact_point AS contact
      ON contact.contact_set_id = contact_set.id
    GROUP BY contact_set.opportunity_id
)
"""

_VISIBLE_PROSPECT_FROM = """
FROM prospect
JOIN opportunity
  ON opportunity.id = prospect.id
 AND opportunity.kind = 'PROSPECT'
 AND opportunity.hidden_at IS NULL
JOIN establishment
  ON establishment.id = prospect.establishment_id
 AND establishment.administrative_state <> 'CLOSED'
 AND establishment.diffusion_status = 'FULL'
LEFT JOIN organization
  ON organization.id = establishment.organization_id
 AND organization.administrative_state <> 'CEASED'
 AND organization.diffusion_status = 'FULL'
JOIN effective_location AS location
  ON location.opportunity_id = prospect.id
LEFT JOIN effective_contacts AS contacts
  ON contacts.opportunity_id = prospect.id
CROSS JOIN reference_position AS reference
WHERE prospect.eligibility = 'ELIGIBLE'
  AND (establishment.organization_id IS NULL OR organization.id IS NOT NULL)
  AND reference.id = :reference_position_id
  AND (
      CAST(:location_filter AS text) = 'located'
      AND location.usability = 'USABLE'
      AND location.point IS NOT NULL
      AND ST_DWithin(location.point, reference.point, :radius_meters)
      OR CAST(:location_filter AS text) = 'to_verify'
      AND (location.usability <> 'USABLE' OR location.point IS NULL)
  )
  AND (
      CAST(:search_pattern AS text) IS NULL
      OR prospect.source_display_name ILIKE :search_pattern ESCAPE '\\'
      OR organization.legal_name ILIKE :search_pattern ESCAPE '\\'
      OR establishment.siret ILIKE :search_pattern ESCAPE '\\'
      OR location.structured_address #>> '{municipality_label}'
            ILIKE :search_pattern ESCAPE '\\'
      OR location.postcode ILIKE :search_pattern ESCAPE '\\'
  )
  AND (
      CAST(:organization_type AS text) IS NULL
      OR prospect.source_organization_type = :organization_type
  )
  AND (
      CAST(:activity_code AS text) IS NULL
      OR establishment.activity_code = :activity_code
  )
  AND (
      CAST(:employee_band AS text) IS NULL
      OR establishment.employee_band = :employee_band
  )
  AND (NOT CAST(:has_email AS boolean) OR COALESCE(contacts.has_email, FALSE))
  AND (NOT CAST(:has_phone AS boolean) OR COALESCE(contacts.has_phone, FALSE))
  AND (NOT CAST(:has_website AS boolean) OR COALESCE(contacts.has_website, FALSE))
"""

_LIST_COLUMNS = """
SELECT
    prospect.id,
    prospect.source_display_name,
    prospect.source_organization_type,
    establishment.activity_code,
    establishment.activity_nomenclature,
    establishment.activity_label,
    establishment.employee_band,
    establishment.employee_year,
    establishment.employee_scope,
    COALESCE(contacts.has_email, FALSE) AS has_email,
    COALESCE(contacts.has_phone, FALSE) AS has_phone,
    COALESCE(contacts.has_website, FALSE) AS has_website,
    location.full_address,
    location.structured_address,
    location.postcode,
    location.municipality_code,
    CASE
        WHEN location.usability = 'USABLE' AND location.point IS NOT NULL
        THEN ST_Distance(location.point, reference.point)
        ELSE NULL
    END AS distance_meters,
    CASE
        WHEN location.usability = 'USABLE' AND location.point IS NOT NULL
        THEN 'located'
        ELSE 'to_verify'
    END AS location_status,
    location.precision AS location_precision,
    prospect.last_observed_at
"""

_ORDER_BY = """
ORDER BY
    CASE
        WHEN CAST(:sort AS text) = 'distance' AND CAST(:direction AS text) = 'asc'
        THEN CASE
            WHEN location.usability = 'USABLE' AND location.point IS NOT NULL
            THEN ST_Distance(location.point, reference.point)
            ELSE NULL
        END
    END ASC NULLS LAST,
    CASE
        WHEN CAST(:sort AS text) = 'distance' AND CAST(:direction AS text) = 'desc'
        THEN CASE
            WHEN location.usability = 'USABLE' AND location.point IS NOT NULL
            THEN ST_Distance(location.point, reference.point)
            ELSE NULL
        END
    END DESC NULLS LAST,
    CASE
        WHEN CAST(:sort AS text) = 'name' AND CAST(:direction AS text) = 'asc'
        THEN lower(prospect.source_display_name)
    END ASC,
    CASE
        WHEN CAST(:sort AS text) = 'name' AND CAST(:direction AS text) = 'desc'
        THEN lower(prospect.source_display_name)
    END DESC,
    lower(prospect.source_display_name) ASC,
    prospect.id ASC
"""


class SqlAlchemyProspectCatalogRepository:
    """Read effective prospect values with all filtering performed by PostgreSQL."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def search(self, query: ProspectSearch) -> ProspectPage:
        """Return one visible page using the current confirmed reference position."""

        try:
            with self._engine.connect() as connection:
                reference_position_id, configured_radius = self._reference_settings(connection)
                applied_radius = query.max_distance_meters or configured_radius
                parameters = self._search_parameters(
                    query,
                    reference_position_id,
                    applied_radius,
                )
                total = connection.execute(
                    text(
                        f"""
                        WITH {_EFFECTIVE_READ_CTES}
                        SELECT count(*)
                        {_VISIBLE_PROSPECT_FROM}
                        """
                    ),
                    parameters,
                ).scalar_one()
                rows = connection.execute(
                    text(
                        f"""
                        WITH {_EFFECTIVE_READ_CTES}
                        {_LIST_COLUMNS}
                        {_VISIBLE_PROSPECT_FROM}
                        {_ORDER_BY}
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    parameters,
                ).mappings()
                items = tuple(self._summary_from_row(row) for row in rows)
        except (ProspectReferencePositionRequiredError, ValueError):
            raise
        except SQLAlchemyError as error:
            raise ProspectCatalogUnavailableError(
                "cannot query the local prospect catalogue"
            ) from error

        return ProspectPage(
            items=items,
            total=int(total),
            limit=query.limit,
            offset=query.offset,
            applied_radius_meters=applied_radius,
        )

    def get(self, prospect_id: UUID) -> ProspectDetail:
        """Return one detailed fiche and its source freshness."""

        try:
            with self._engine.connect() as connection:
                row = (
                    connection.execute(
                        text(
                            f"""
                        WITH {_EFFECTIVE_READ_CTES},
                        current_reference AS (
                            SELECT reference.point
                            FROM application_setting AS settings
                            JOIN reference_position AS reference
                              ON reference.id = settings.current_reference_position_id
                            WHERE settings.singleton_key = 'primary'
                        )
                        SELECT
                            prospect.id,
                            prospect.source_display_name,
                            prospect.source_organization_type,
                            prospect.source_description,
                            prospect.eligibility,
                            prospect.eligibility_reason,
                            prospect.first_observed_at,
                            prospect.last_observed_at,
                            establishment.siret,
                            establishment.is_head_office,
                            establishment.activity_code,
                            establishment.activity_nomenclature,
                            establishment.activity_label,
                            establishment.employee_band,
                            establishment.employee_year,
                            establishment.employee_scope,
                            COALESCE(contacts.has_email, FALSE) AS has_email,
                            COALESCE(contacts.has_phone, FALSE) AS has_phone,
                            COALESCE(contacts.has_website, FALSE) AS has_website,
                            establishment.established_on,
                            establishment.current_period_started_on,
                            organization.siren,
                            organization.legal_name,
                            organization.usual_name,
                            organization.legal_category,
                            location.full_address,
                            location.structured_address,
                            location.postcode,
                            location.municipality_code,
                            location.position_origin,
                            location.quality_code,
                            location.match_score,
                            location.precision AS location_precision,
                            location.usability,
                            CASE
                                WHEN location.usability = 'USABLE'
                                  AND location.point IS NOT NULL
                                THEN ST_Distance(
                                    location.point,
                                    (SELECT point FROM current_reference)
                                )
                                ELSE NULL
                            END AS distance_meters,
                            CASE
                                WHEN location.usability = 'USABLE'
                                  AND location.point IS NOT NULL
                                THEN 'located'
                                ELSE 'to_verify'
                            END AS location_status,
                            CASE WHEN location.point IS NOT NULL
                                THEN ST_X(location.point::geometry)
                                ELSE NULL
                            END AS longitude,
                            CASE WHEN location.point IS NOT NULL
                                THEN ST_Y(location.point::geometry)
                                ELSE NULL
                            END AS latitude
                        FROM prospect
                        JOIN opportunity
                          ON opportunity.id = prospect.id
                         AND opportunity.kind = 'PROSPECT'
                        JOIN establishment
                          ON establishment.id = prospect.establishment_id
                        LEFT JOIN organization
                          ON organization.id = establishment.organization_id
                        LEFT JOIN effective_location AS location
                          ON location.opportunity_id = prospect.id
                        LEFT JOIN effective_contacts AS contacts
                          ON contacts.opportunity_id = prospect.id
                        WHERE prospect.id = :prospect_id
                          AND prospect.eligibility <> 'RESTRICTED'
                        """
                        ),
                        {"prospect_id": prospect_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise ProspectNotFoundError
                contacts = self._contacts(connection, prospect_id)
                sources = self._sources(connection, prospect_id)
                return self._detail_from_row(row, contacts, sources)
        except ProspectNotFoundError:
            raise
        except SQLAlchemyError as error:
            raise ProspectCatalogUnavailableError(
                "cannot query the local prospect catalogue"
            ) from error

    @staticmethod
    def _reference_settings(connection: Connection) -> tuple[UUID, int]:
        row = connection.execute(
            text(
                """
                SELECT current_reference_position_id, search_radius_meters
                FROM application_setting
                WHERE singleton_key = 'primary'
                """
            )
        ).one()
        if not isinstance(row[0], UUID):
            raise ProspectReferencePositionRequiredError
        return row[0], int(row[1])

    @staticmethod
    def _search_parameters(
        query: ProspectSearch,
        reference_position_id: UUID,
        applied_radius: int,
    ) -> dict[str, object]:
        if not 1 <= applied_radius <= 50_000:
            raise ValueError("prospect search radius must be between 1 and 50000 metres")
        if not 1 <= query.limit <= 100 or query.offset < 0:
            raise ValueError("prospect pagination is outside its accepted bounds")
        return {
            "reference_position_id": reference_position_id,
            "radius_meters": applied_radius,
            "search_pattern": (
                SqlAlchemyProspectCatalogRepository._like_pattern(query.text)
                if query.text is not None
                else None
            ),
            "organization_type": query.organization_type,
            "activity_code": query.activity_code,
            "employee_band": query.employee_band,
            "has_email": query.has_email,
            "has_phone": query.has_phone,
            "has_website": query.has_website,
            "location_filter": query.location,
            "sort": query.sort,
            "direction": query.direction,
            "limit": query.limit,
            "offset": query.offset,
        }

    @staticmethod
    def _like_pattern(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    @staticmethod
    def _address_from_row(row: RowMapping) -> ProspectAddress:
        structured = cast(dict[str, object], row["structured_address"] or {})

        def string(key: str) -> str | None:
            value = structured.get(key)
            return value if isinstance(value, str) else None

        return ProspectAddress(
            full_address=cast(str | None, row["full_address"]),
            street_number=string("street_number"),
            repetition_index=string("repetition_index"),
            street_type=string("street_type"),
            street_label=string("street_label"),
            address_complement=string("address_complement"),
            postcode=cast(str | None, row["postcode"]),
            municipality=string("municipality_label"),
            municipality_code=cast(str | None, row["municipality_code"]),
        )

    @classmethod
    def _summary_from_row(cls, row: RowMapping) -> ProspectSummary:
        return ProspectSummary(
            id=cast(UUID, row["id"]),
            display_name=cast(str, row["source_display_name"]),
            organization_type=cast(str, row["source_organization_type"]),
            activity_code=cast(str | None, row["activity_code"]),
            activity_nomenclature=cast(str | None, row["activity_nomenclature"]),
            activity_label=cast(str | None, row["activity_label"]),
            employee_band=cast(str | None, row["employee_band"]),
            employee_year=cast(int | None, row["employee_year"]),
            employee_scope=cast(str, row["employee_scope"]),
            has_email=cast(bool, row["has_email"]),
            has_phone=cast(bool, row["has_phone"]),
            has_website=cast(bool, row["has_website"]),
            address=cls._address_from_row(row),
            distance_meters=(
                float(row["distance_meters"]) if row["distance_meters"] is not None else None
            ),
            location_status=cast(ProspectLocationFilter, row["location_status"]),
            location_precision=cast(str, row["location_precision"] or "UNKNOWN"),
            last_observed_at=cast(datetime, row["last_observed_at"]),
        )

    @staticmethod
    def _contacts(connection: Connection, prospect_id: UUID) -> tuple[ProspectContact, ...]:
        rows = connection.execute(
            text(
                """
                SELECT
                    contact.type,
                    contact.display_value,
                    contact.scope,
                    contact.label,
                    contact.source_reference
                FROM contact_point AS contact
                WHERE contact.contact_set_id = (
                    SELECT contact_set.id
                    FROM contact_set
                    WHERE contact_set.opportunity_id = :prospect_id
                      AND contact_set.is_current
                    ORDER BY CASE contact_set.layer WHEN 'USER' THEN 0 ELSE 1 END
                    LIMIT 1
                )
                ORDER BY contact.display_order, contact.type, contact.normalized_value
                """
            ),
            {"prospect_id": prospect_id},
        ).mappings()
        return tuple(
            ProspectContact(
                type=cast(ProspectContactType, row["type"]),
                value=cast(str, row["display_value"]),
                scope=cast(ProspectContactScope, row["scope"]),
                label=cast(str | None, row["label"]),
                source_reference=cast(str | None, row["source_reference"]),
            )
            for row in rows
        )

    @staticmethod
    def _sources(connection: Connection, prospect_id: UUID) -> tuple[ProspectSource, ...]:
        rows = connection.execute(
            text(
                """
                SELECT
                    source.code,
                    source.name,
                    source.authority,
                    binding.producer_name,
                    binding.state,
                    binding.first_observed_at,
                    binding.last_observed_at,
                    observation.retrieved_at,
                    observation.source_updated_at
                FROM source_binding AS binding
                JOIN data_source AS source
                  ON source.code = binding.data_source_code
                JOIN source_observation AS observation
                  ON observation.id = binding.current_observation_id
                WHERE binding.opportunity_id = :prospect_id
                ORDER BY source.code
                """
            ),
            {"prospect_id": prospect_id},
        ).mappings()
        return tuple(
            ProspectSource(
                code=cast(str, row["code"]),
                name=cast(str, row["name"]),
                authority=cast(str, row["authority"]),
                producer_name=cast(str | None, row["producer_name"]),
                state=cast(str, row["state"]),
                first_observed_at=cast(datetime, row["first_observed_at"]),
                last_observed_at=cast(datetime, row["last_observed_at"]),
                retrieved_at=cast(datetime, row["retrieved_at"]),
                source_updated_at=cast(datetime | None, row["source_updated_at"]),
            )
            for row in rows
        )

    @classmethod
    def _detail_from_row(
        cls,
        row: RowMapping,
        contacts: tuple[ProspectContact, ...],
        sources: tuple[ProspectSource, ...],
    ) -> ProspectDetail:
        summary = cls._summary_from_row(row)
        return ProspectDetail(
            summary=summary,
            description=cast(str | None, row["source_description"]),
            siret=cast(str | None, row["siret"]),
            siren=cast(str | None, row["siren"]),
            legal_name=cast(str | None, row["legal_name"]),
            usual_name=cast(str | None, row["usual_name"]),
            legal_category=cast(str | None, row["legal_category"]),
            is_head_office=cast(bool | None, row["is_head_office"]),
            eligibility=cast(str, row["eligibility"]),
            eligibility_reason=cast(str, row["eligibility_reason"]),
            established_on=cast(date | None, row["established_on"]),
            current_period_started_on=cast(date | None, row["current_period_started_on"]),
            longitude=(float(row["longitude"]) if row["longitude"] is not None else None),
            latitude=(float(row["latitude"]) if row["latitude"] is not None else None),
            location_origin=cast(str, row["position_origin"] or "OTHER"),
            location_quality_code=cast(str | None, row["quality_code"]),
            location_match_score=(
                float(row["match_score"]) if row["match_score"] is not None else None
            ),
            first_observed_at=cast(datetime, row["first_observed_at"]),
            contacts=contacts,
            sources=sources,
        )
