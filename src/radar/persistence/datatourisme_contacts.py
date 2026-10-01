"""Version public DATAtourisme event contacts without inferring an organizer."""

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from radar.events.projection import EventProjectionError


@dataclass(frozen=True)
class EventSourceContact:
    """One normalized public channel with an explicit, unconfirmed role."""

    type: str
    display_value: str
    normalized_value: str
    scope: str
    label: str
    source_reference: str


def _phone_key(value: str) -> str:
    compact = re.sub(r"[\s()./\-]", "", value)
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    if compact.startswith("+330") and len(compact) == 13 and compact[1:].isdigit():
        compact = "+33" + compact[4:]
    if compact.startswith("0") and len(compact) == 10 and compact.isdigit():
        return "+33" + compact[1:]
    if compact.startswith("+") and compact[1:].isdigit() and 8 <= len(compact[1:]) <= 15:
        return compact
    return " ".join(value.split())


def _website_key(value: str) -> str | None:
    if not value or any(character.isspace() for character in value) or value.startswith("//"):
        return None
    candidate = value if "://" in value else "https://" + value
    try:
        parts = urlsplit(candidate)
        hostname = parts.hostname
        port = parts.port
        if parts.username is not None or parts.password is not None:
            return None
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or hostname is None or "." not in hostname:
        return None
    netloc = hostname.lower()
    if port is not None and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        netloc += f":{port}"
    return urlunsplit(
        (parts.scheme.lower(), netloc, parts.path or "/", parts.query, parts.fragment)
    )


def event_source_contacts(payload: object) -> tuple[EventSourceContact, ...]:
    """Extract deduplicated channels from explicitly declared contact roles."""

    if not isinstance(payload, dict) or not isinstance(payload.get("contacts"), list):
        raise EventProjectionError("a staged event has malformed contacts")
    result: list[EventSourceContact] = []
    seen: set[tuple[str, str, str]] = set()
    for contact_index, item in enumerate(payload["contacts"]):
        if not isinstance(item, dict) or item.get("role") not in ("GENERAL", "BOOKING"):
            raise EventProjectionError("a staged event contact has an invalid role")
        legal_name = item.get("legal_name")
        phones = item.get("phones")
        websites = item.get("websites")
        if (
            (legal_name is not None and not isinstance(legal_name, str))
            or not isinstance(phones, list)
            or not all(isinstance(value, str) for value in phones)
            or not isinstance(websites, list)
            or not all(isinstance(value, str) for value in websites)
        ):
            raise EventProjectionError("a staged event contact is malformed")
        label = "Contact réservation" if item["role"] == "BOOKING" else "Contact général"
        if legal_name and legal_name.strip():
            label += " — " + legal_name.strip()
        for kind, values, field in (
            ("PHONE", phones, "phones"),
            ("WEBSITE", websites, "websites"),
        ):
            for value_index, raw_value in enumerate(values):
                display_value = raw_value.strip()
                if not display_value:
                    continue
                normalized_value = (
                    _phone_key(display_value) if kind == "PHONE" else _website_key(display_value)
                )
                if normalized_value is None:
                    continue
                key = (kind, normalized_value, "UNKNOWN")
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    EventSourceContact(
                        type=kind,
                        display_value=display_value,
                        normalized_value=normalized_value,
                        scope="UNKNOWN",
                        label=label,
                        source_reference=f"contacts[{contact_index}].{field}[{value_index}]",
                    )
                )
    return tuple(result)


def project_event_contacts(
    connection: Connection,
    opportunity_id: UUID,
    observation_id: UUID,
    payload: object,
    now: datetime,
) -> bool:
    """Replace only a changed SOURCE set, preserving any USER contact set."""

    contacts = event_source_contacts(payload)
    current_id = connection.execute(
        text(
            """
            SELECT id FROM contact_set
            WHERE opportunity_id = :opportunity_id AND layer = 'SOURCE' AND is_current
            FOR UPDATE
            """
        ),
        {"opportunity_id": opportunity_id},
    ).scalar_one_or_none()
    if current_id is not None:
        rows = (
            connection.execute(
                text(
                    """
                SELECT type, display_value, normalized_value, scope, label,
                       source_reference
                FROM contact_point WHERE contact_set_id = :set_id
                ORDER BY display_order
                """
                ),
                {"set_id": current_id},
            )
            .mappings()
            .all()
        )
        previous = tuple(
            EventSourceContact(
                type=row["type"],
                display_value=row["display_value"],
                normalized_value=row["normalized_value"],
                scope=row["scope"],
                label=row["label"],
                source_reference=row["source_reference"],
            )
            for row in rows
        )
        if previous == contacts:
            return False
        connection.execute(
            text(
                """
                UPDATE contact_set SET is_current = FALSE, retired_at = :now
                WHERE id = :set_id
                """
            ),
            {"set_id": current_id, "now": now},
        )
    set_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO contact_set (
                id, opportunity_id, layer, source_observation_id, is_current, created_at
            ) VALUES (:set_id, :opportunity_id, 'SOURCE', :observation_id, TRUE, :now)
            """
        ),
        {
            "set_id": set_id,
            "opportunity_id": opportunity_id,
            "observation_id": observation_id,
            "now": now,
        },
    )
    for order, contact in enumerate(contacts):
        connection.execute(
            text(
                """
                INSERT INTO contact_point (
                    id, contact_set_id, type, display_value, normalized_value,
                    scope, label, source_reference, display_order, created_at
                ) VALUES (
                    :id, :set_id, :type, :display_value, :normalized_value,
                    :scope, :label, :source_reference, :display_order, :now
                )
                """
            ),
            {
                "id": uuid4(),
                "set_id": set_id,
                "type": contact.type,
                "display_value": contact.display_value,
                "normalized_value": contact.normalized_value,
                "scope": contact.scope,
                "label": contact.label,
                "source_reference": contact.source_reference,
                "display_order": order,
                "now": now,
            },
        )
    return True
