"""Unit tests for the isolated Géoplateforme adapter."""

import json

import httpx2 as httpx
import pytest

from radar.geography.contracts import (
    AddressNotFoundError,
    AddressOutsideMetropolitanFranceError,
    GeocodingContractError,
    GeocodingUnavailableError,
)
from radar.providers.geoplatform import GEOCODING_URL, GeoPlatformGeocoder


def feature(
    *,
    citycode: str = "40088",
    longitude: float = -1.051952,
    latitude: float = 43.70884,
) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "label": "12 Rue Saint Pierre 40100 Dax",
            "score": 0.9653,
            "housenumber": "12",
            "id": "40088_1750_00012",
            "postcode": "40100",
            "citycode": citycode,
            "city": "Dax",
            "context": "40, Landes, Nouvelle-Aquitaine",
            "type": "housenumber",
            "street": "Rue Saint Pierre",
            "_type": "address",
        },
    }


def response(features: list[dict[str, object]]) -> dict[str, object]:
    return {"type": "FeatureCollection", "features": features, "query": "Dax"}


def adapter_for(payload: dict[str, object], status_code: int = 200) -> GeoPlatformGeocoder:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(GEOCODING_URL)
        assert request.url.params["index"] == "address"
        assert request.url.params["limit"] == "5"
        return httpx.Response(status_code, content=json.dumps(payload).encode(), request=request)

    return GeoPlatformGeocoder(httpx.Client(transport=httpx.MockTransport(handler)))


def test_returns_the_highest_ranked_metropolitan_address() -> None:
    geocoder = adapter_for(response([feature()]))

    result = geocoder.geocode("12 rue Saint-Pierre 40100 Dax")

    assert result.normalized_label == "12 Rue Saint Pierre 40100 Dax"
    assert result.municipality_code == "40088"
    assert result.ban_id == "40088_1750_00012"
    assert result.longitude == pytest.approx(-1.051952)
    assert result.latitude == pytest.approx(43.70884)
    assert result.structured_address.city == "Dax"


def test_rejects_results_outside_metropolitan_france() -> None:
    geocoder = adapter_for(response([feature(citycode="97105", longitude=-61.55, latitude=16.25)]))

    with pytest.raises(AddressOutsideMetropolitanFranceError):
        geocoder.geocode("Basse-Terre")


def test_reports_an_address_without_results() -> None:
    geocoder = adapter_for(response([]))

    with pytest.raises(AddressNotFoundError):
        geocoder.geocode("adresse introuvable")


def test_rejects_a_provider_schema_change() -> None:
    geocoder = adapter_for({"unexpected": "payload"})

    with pytest.raises(GeocodingContractError):
        geocoder.geocode("Dax")


def test_reports_non_successful_provider_status() -> None:
    geocoder = adapter_for(response([]), status_code=503)

    with pytest.raises(GeocodingUnavailableError):
        geocoder.geocode("Dax")
