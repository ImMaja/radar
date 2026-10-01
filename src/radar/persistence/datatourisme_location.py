"""Version the exact DATAtourisme location selected during PostGIS staging."""

import json
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from radar.events.projection import EventProjectionError

_RULE_VERSION = "datatourisme-nearest-metropolitan-v1"


@dataclass(frozen=True)
class SelectedEventLocation:
    """Source position and address belonging to the staged observation."""

    longitude: float
    latitude: float
    full_address: str | None
    structured_address: dict[str, object]
    municipality_code: str | None
    postcode: str | None
    diagnostics: dict[str, object]


def selected_event_location(payload: object, reason: object) -> SelectedEventLocation:
    """Read only the location whose one-based index was validated by staging."""

    if not isinstance(payload, dict) or not isinstance(reason, dict):
        raise EventProjectionError("a staged event location is malformed")
    locations = payload.get("locations")
    index = reason.get("selected_location_index")
    if (
        not isinstance(locations, list)
        or type(index) is not int
        or index < 1
        or index > len(locations)
    ):
        raise EventProjectionError("a staged event has no selected location")
    location = locations[index - 1]
    if not isinstance(location, dict):
        raise EventProjectionError("a selected event location is malformed")
    raw_longitude = location.get("longitude")
    raw_latitude = location.get("latitude")
    if (
        isinstance(raw_longitude, bool)
        or not isinstance(raw_longitude, (int, float))
        or isinstance(raw_latitude, bool)
        or not isinstance(raw_latitude, (int, float))
    ):
        raise EventProjectionError("a selected event location has invalid coordinates")
    longitude = float(raw_longitude)
    latitude = float(raw_latitude)
    if (
        not isfinite(longitude)
        or not isfinite(latitude)
        or not (-180 <= longitude <= 180 and -90 <= latitude <= 90)
    ):
        raise EventProjectionError("a selected event location has invalid coordinates")
    addresses = location.get("addresses")
    if not isinstance(addresses, list):
        raise EventProjectionError("a selected event location has malformed addresses")
    selected_address: dict[str, object] | None = None
    for address in addresses:
        if not isinstance(address, dict):
            raise EventProjectionError("a selected event address is malformed")
        if selected_address is None:
            selected_address = address
    postcode: str | None = None
    municipality: str | None = None
    municipality_code: str | None = None
    streets: list[str] = []
    if selected_address is not None:
        raw_streets = selected_address.get("streets")
        if not isinstance(raw_streets, list) or not all(
            isinstance(value, str) for value in raw_streets
        ):
            raise EventProjectionError("a selected event address is malformed")
        streets = [street.strip() for street in raw_streets if street.strip()]
        for key in ("postcode", "municipality", "municipality_code"):
            value = selected_address.get(key)
            if value is not None and not isinstance(value, str):
                raise EventProjectionError("a selected event address is malformed")
        postcode = _clean(selected_address.get("postcode"))
        municipality = _clean(selected_address.get("municipality"))
        municipality_code = _clean(selected_address.get("municipality_code"))
    address_parts = [*streets, " ".join(filter(None, (postcode, municipality)))]
    full_address = ", ".join(part for part in address_parts if part) or None
    return SelectedEventLocation(
        longitude=longitude,
        latitude=latitude,
        full_address=full_address,
        structured_address={"addresses": addresses},
        municipality_code=municipality_code,
        postcode=postcode,
        diagnostics={"selected_location_index": index},
    )


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def project_event_location(
    connection: Connection,
    opportunity_id: UUID,
    observation_id: UUID,
    payload: object,
    reason: object,
    now: datetime,
) -> bool:
    """Replace only a changed SOURCE location; leave any USER version untouched."""

    selected = selected_event_location(payload, reason)
    current = (
        connection.execute(
            text(
                """
                SELECT id, full_address, structured_address, municipality_code,
                       postcode, ST_X(point::geometry) AS longitude,
                       ST_Y(point::geometry) AS latitude, diagnostics,
                       position_origin, source_crs, precision, usability, rule_version
                FROM location_assertion
                WHERE opportunity_id = :opportunity_id AND layer = 'SOURCE' AND is_current
                FOR UPDATE
                """
            ),
            {"opportunity_id": opportunity_id},
        )
        .mappings()
        .one_or_none()
    )
    if current is not None and all(
        (
            current["full_address"] == selected.full_address,
            current["structured_address"] == selected.structured_address,
            current["municipality_code"] == selected.municipality_code,
            current["postcode"] == selected.postcode,
            current["longitude"] == selected.longitude,
            current["latitude"] == selected.latitude,
            current["diagnostics"] == selected.diagnostics,
            current["position_origin"] == "DATATOURISME",
            current["source_crs"] == "EPSG:4326",
            current["precision"] == "UNKNOWN",
            current["usability"] == "USABLE",
            current["rule_version"] == _RULE_VERSION,
        )
    ):
        return False
    if current is not None:
        connection.execute(
            text(
                """
                UPDATE location_assertion
                SET is_current = FALSE, retired_at = :now, updated_at = :now
                WHERE id = :id
                """
            ),
            {"id": current["id"], "now": now},
        )
    connection.execute(
        text(
            """
            INSERT INTO location_assertion (
                id, opportunity_id, layer, full_address, structured_address,
                municipality_code, postcode, country_code, point,
                position_origin, source_crs, precision, usability,
                address_observation_id, position_observation_id,
                rule_version, diagnostics, is_current, created_at, updated_at
            ) VALUES (
                :id, :opportunity_id, 'SOURCE', :full_address,
                CAST(:structured_address AS jsonb), :municipality_code,
                :postcode, 'FR',
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                'DATATOURISME', 'EPSG:4326', 'UNKNOWN', 'USABLE',
                :observation_id, :observation_id, :rule_version,
                CAST(:diagnostics AS jsonb), TRUE, :now, :now
            )
            """
        ),
        {
            "id": uuid4(),
            "opportunity_id": opportunity_id,
            "observation_id": observation_id,
            "full_address": selected.full_address,
            "structured_address": json.dumps(selected.structured_address, ensure_ascii=False),
            "municipality_code": selected.municipality_code,
            "postcode": selected.postcode,
            "longitude": selected.longitude,
            "latitude": selected.latitude,
            "rule_version": _RULE_VERSION,
            "diagnostics": json.dumps(selected.diagnostics),
            "now": now,
        },
    )
    return True
