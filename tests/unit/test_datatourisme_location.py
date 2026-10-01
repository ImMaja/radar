"""Selection of a published event location from staged PostGIS evidence."""

import pytest

from radar.events.projection import EventProjectionError
from radar.persistence.datatourisme_location import selected_event_location


def test_uses_exact_one_based_location_selected_during_staging() -> None:
    payload = {
        "locations": [
            {"longitude": -1.2, "latitude": 43.7, "addresses": []},
            {
                "longitude": -1.05,
                "latitude": 43.71,
                "addresses": [
                    {
                        "streets": [" Place de la Mairie "],
                        "postcode": "40100",
                        "municipality": "Dax",
                        "municipality_code": "40088",
                    }
                ],
            },
        ]
    }

    selected = selected_event_location(payload, {"selected_location_index": 2})

    assert selected.longitude == -1.05
    assert selected.latitude == 43.71
    assert selected.full_address == "Place de la Mairie, 40100 Dax"
    assert selected.structured_address == {"addresses": payload["locations"][1]["addresses"]}
    assert selected.municipality_code == "40088"
    assert selected.diagnostics == {"selected_location_index": 2}


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"locations": []}, {"selected_location_index": 1}),
        (
            {"locations": [{"longitude": 0, "latitude": 0, "addresses": []}]},
            {"selected_location_index": True},
        ),
        (
            {"locations": [{"longitude": float("inf"), "latitude": 0, "addresses": []}]},
            {"selected_location_index": 1},
        ),
        (
            {"locations": [{"longitude": 181, "latitude": 0, "addresses": []}]},
            {"selected_location_index": 1},
        ),
        (
            {"locations": [{"longitude": 0, "latitude": 0, "addresses": "bad"}]},
            {"selected_location_index": 1},
        ),
    ],
)
def test_rejects_missing_or_corrupt_selected_location(
    payload: dict[str, object], reason: dict[str, object]
) -> None:
    with pytest.raises(EventProjectionError):
        selected_event_location(payload, reason)
