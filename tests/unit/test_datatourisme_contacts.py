"""DATAtourisme contact-role and normalization rules."""

import pytest

from radar.events.projection import EventProjectionError
from radar.persistence.datatourisme_contacts import event_source_contacts


def test_extracts_unknown_scope_relays_without_organizer_or_email_inference() -> None:
    payload = {
        "contacts": [
            {
                "role": "GENERAL",
                "legal_name": "Office de tourisme",
                "phones": ["05 58 12 34 56"],
                "websites": ["HTTPS://EXAMPLE.FR/contact", "javascript:alert(1)"],
            },
            {
                "role": "BOOKING",
                "legal_name": None,
                "phones": ["+33 5 58 12 34 56", "+33 6 11 22 33 44"],
                "websites": ["example.fr/reservation"],
            },
        ],
        "source_parties": [{"role": "CREATOR", "phones": ["+33500000000"], "websites": []}],
    }

    contacts = event_source_contacts(payload)

    assert [contact.type for contact in contacts] == ["PHONE", "WEBSITE", "PHONE", "WEBSITE"]
    assert [contact.normalized_value for contact in contacts] == [
        "+33558123456",
        "https://example.fr/contact",
        "+33611223344",
        "https://example.fr/reservation",
    ]
    assert all(contact.scope == "UNKNOWN" for contact in contacts)
    assert contacts[0].label == "Contact général — Office de tourisme"
    assert contacts[2].label == "Contact réservation"
    assert contacts[0].source_reference == "contacts[0].phones[0]"
    assert contacts[2].source_reference == "contacts[1].phones[1]"
    assert not any(contact.type == "EMAIL" for contact in contacts)


def test_empty_contact_list_is_a_valid_source_set() -> None:
    assert event_source_contacts({"contacts": []}) == ()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"contacts": "invalid"},
        {"contacts": [{"role": "ORGANIZER", "phones": [], "websites": []}]},
        {"contacts": [{"role": "GENERAL", "phones": "bad", "websites": []}]},
        {"contacts": [{"role": "BOOKING", "phones": [], "websites": [10]}]},
    ],
)
def test_rejects_malformed_staged_contacts(payload: dict[str, object]) -> None:
    with pytest.raises(EventProjectionError):
        event_source_contacts(payload)
