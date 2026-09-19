"""SQLAlchemy persistence for reference geography and local radii."""

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text

from radar.geography.contracts import (
    GeocodedAddress,
    GeographySettings,
    ReferenceCandidateNotFoundError,
    ReferencePosition,
    StructuredAddress,
)

SINGLETON_KEY = "primary"

_SETTINGS_QUERY = text(
    """
    SELECT
        settings.collection_radius_meters,
        settings.search_radius_meters,
        settings.updated_at AS settings_updated_at,
        reference.id AS reference_id,
        reference.input_address,
        reference.normalized_label,
        reference.structured_address,
        ST_X(reference.point::geometry) AS longitude,
        ST_Y(reference.point::geometry) AS latitude,
        reference.municipality_code,
        reference.ban_id,
        reference.result_type,
        reference.score,
        reference.provider_name,
        reference.provider_url,
        reference.geocoded_at,
        reference.confirmed_at
    FROM application_setting AS settings
    LEFT JOIN reference_position AS reference
        ON reference.id = settings.current_reference_position_id
    WHERE settings.singleton_key = :singleton_key
    """
)


def _structured_address(value: object) -> StructuredAddress:
    data = cast(Mapping[str, object], value)

    def optional_string(key: str) -> str | None:
        candidate = data.get(key)
        return candidate if isinstance(candidate, str) else None

    return StructuredAddress(
        house_number=optional_string("house_number"),
        street=optional_string("street"),
        postcode=optional_string("postcode"),
        city=optional_string("city"),
        context=optional_string("context"),
    )


def _reference_from_row(row: RowMapping) -> ReferencePosition | None:
    reference_id = row["reference_id"]
    if reference_id is None:
        return None
    return ReferencePosition(
        id=cast(UUID, reference_id),
        input_address=cast(str, row["input_address"]),
        normalized_label=cast(str, row["normalized_label"]),
        structured_address=_structured_address(row["structured_address"]),
        longitude=cast(float, row["longitude"]),
        latitude=cast(float, row["latitude"]),
        municipality_code=cast(str, row["municipality_code"]),
        ban_id=cast(str | None, row["ban_id"]),
        result_type=cast(str | None, row["result_type"]),
        score=cast(float | None, row["score"]),
        provider_name=cast(str, row["provider_name"]),
        provider_url=cast(str, row["provider_url"]),
        geocoded_at=cast(datetime, row["geocoded_at"]),
        confirmed_at=cast(datetime | None, row["confirmed_at"]),
    )


def _settings_from_row(row: RowMapping) -> GeographySettings:
    return GeographySettings(
        reference_position=_reference_from_row(row),
        collection_radius_meters=cast(int, row["collection_radius_meters"]),
        search_radius_meters=cast(int, row["search_radius_meters"]),
        updated_at=cast(datetime, row["settings_updated_at"]),
    )


class SqlAlchemyGeographyRepository:
    """Keep geographic-setting transactions inside the persistence adapter."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save_candidate(
        self,
        input_address: str,
        candidate: GeocodedAddress,
        now: datetime,
    ) -> ReferencePosition:
        """Persist one provider result without changing the current position."""

        candidate_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO reference_position (
                        id,
                        input_address,
                        normalized_label,
                        structured_address,
                        point,
                        municipality_code,
                        ban_id,
                        result_type,
                        score,
                        provider_name,
                        provider_url,
                        geocoded_at,
                        confirmed_at,
                        country_code,
                        is_metropolitan_france,
                        created_at,
                        updated_at
                    ) VALUES (
                        :id,
                        :input_address,
                        :normalized_label,
                        CAST(:structured_address AS jsonb),
                        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                        :municipality_code,
                        :ban_id,
                        :result_type,
                        :score,
                        :provider_name,
                        :provider_url,
                        :geocoded_at,
                        NULL,
                        'FR',
                        TRUE,
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "id": candidate_id,
                    "input_address": input_address,
                    "normalized_label": candidate.normalized_label,
                    "structured_address": json.dumps(candidate.structured_address.as_dict()),
                    "longitude": candidate.longitude,
                    "latitude": candidate.latitude,
                    "municipality_code": candidate.municipality_code,
                    "ban_id": candidate.ban_id,
                    "result_type": candidate.result_type,
                    "score": candidate.score,
                    "provider_name": candidate.provider_name,
                    "provider_url": candidate.provider_url,
                    "geocoded_at": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )

        return ReferencePosition(
            id=candidate_id,
            input_address=input_address,
            normalized_label=candidate.normalized_label,
            structured_address=candidate.structured_address,
            longitude=candidate.longitude,
            latitude=candidate.latitude,
            municipality_code=candidate.municipality_code,
            ban_id=candidate.ban_id,
            result_type=candidate.result_type,
            score=candidate.score,
            provider_name=candidate.provider_name,
            provider_url=candidate.provider_url,
            geocoded_at=now,
            confirmed_at=None,
        )

    def get_settings(self) -> GeographySettings:
        """Load the singleton settings and current confirmed position."""

        with self._engine.connect() as connection:
            return self._load_settings(connection)

    def confirm_candidate(self, candidate_id: UUID, now: datetime) -> GeographySettings:
        """Atomically confirm one pending result and select it as current."""

        with self._engine.begin() as connection:
            locked_id = connection.execute(
                text(
                    """
                    SELECT id
                    FROM reference_position
                    WHERE id = :candidate_id AND confirmed_at IS NULL
                    FOR UPDATE
                    """
                ),
                {"candidate_id": candidate_id},
            ).scalar_one_or_none()
            if locked_id is None:
                raise ReferenceCandidateNotFoundError(
                    "the reference-position candidate does not exist or is already confirmed"
                )

            connection.execute(
                text(
                    """
                    UPDATE reference_position
                    SET confirmed_at = :now, updated_at = :now
                    WHERE id = :candidate_id
                    """
                ),
                {"candidate_id": candidate_id, "now": now},
            )
            connection.execute(
                text(
                    """
                    UPDATE application_setting
                    SET current_reference_position_id = :candidate_id, updated_at = :now
                    WHERE singleton_key = :singleton_key
                    """
                ),
                {
                    "candidate_id": candidate_id,
                    "now": now,
                    "singleton_key": SINGLETON_KEY,
                },
            )
            return self._load_settings(connection)

    def update_radii(
        self,
        collection_radius_meters: int,
        search_radius_meters: int,
        now: datetime,
    ) -> GeographySettings:
        """Update both local radii without touching positions or collections."""

        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE application_setting
                    SET
                        collection_radius_meters = :collection_radius_meters,
                        search_radius_meters = :search_radius_meters,
                        updated_at = :now
                    WHERE singleton_key = :singleton_key
                    """
                ),
                {
                    "collection_radius_meters": collection_radius_meters,
                    "search_radius_meters": search_radius_meters,
                    "now": now,
                    "singleton_key": SINGLETON_KEY,
                },
            )
            return self._load_settings(connection)

    @staticmethod
    def _load_settings(connection: Connection) -> GeographySettings:
        row = (
            connection.execute(
                _SETTINGS_QUERY,
                {"singleton_key": SINGLETON_KEY},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RuntimeError("the application settings singleton is missing")
        return _settings_from_row(row)
