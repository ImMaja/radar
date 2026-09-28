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
    geocoder = adapter_for(response([]), status_code=400)

    with pytest.raises(GeocodingUnavailableError) as captured:
        geocoder.geocode("Dax")

    assert captured.value.reason == "request_rejected"
    assert captured.value.status_code == 400
    assert captured.value.attempts == 1


def test_retries_short_temporary_failures_and_honors_retry_after() -> None:
    statuses = [503, 429, 200]
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        status = statuses.pop(0)
        headers = {"Retry-After": "3"} if status == 429 else None
        return httpx.Response(
            status,
            json=response([feature()]),
            headers=headers,
            request=request,
        )

    geocoder = GeoPlatformGeocoder(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=sleeps.append,
    )

    result = geocoder.geocode("Dax")

    assert result.municipality_code == "40088"
    assert calls == 3
    assert sleeps == [1.0, 3.0]


def test_stops_short_retries_when_provider_requests_a_long_wait() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "120"}, request=request)

    geocoder = GeoPlatformGeocoder(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(GeocodingUnavailableError) as captured:
        geocoder.geocode("Dax")

    assert calls == 1
    assert captured.value.reason == "rate_limited"
    assert captured.value.status_code == 429
    assert captured.value.retry_after_seconds == 120
    assert captured.value.attempts == 1


def test_bounds_an_untrusted_retry_after_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "9" * 10_000},
            request=request,
        )

    geocoder = GeoPlatformGeocoder(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(GeocodingUnavailableError) as captured:
        geocoder.geocode("Dax")

    assert captured.value.reason == "rate_limited"
    assert captured.value.retry_after_seconds == 86_400
    assert captured.value.attempts == 1


def test_retries_a_transient_network_failure() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary failure", request=request)
        return httpx.Response(200, json=response([feature()]), request=request)

    geocoder = GeoPlatformGeocoder(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=sleeps.append,
    )

    result = geocoder.geocode("Dax")

    assert result.municipality_code == "40088"
    assert calls == 2
    assert sleeps == [1.0]


def test_exhausts_a_bounded_number_of_short_retries() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    geocoder = GeoPlatformGeocoder(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=sleeps.append,
    )

    with pytest.raises(GeocodingUnavailableError) as captured:
        geocoder.geocode("Dax")

    assert calls == 5
    assert sleeps == [1.0, 2.0, 4.0, 8.0]
    assert captured.value.reason == "server_error"
    assert captured.value.status_code == 503
    assert captured.value.attempts == 5


def test_reports_network_diagnostics_after_exhausting_short_retries() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("temporary failure", request=request)

    geocoder = GeoPlatformGeocoder(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=sleeps.append,
    )

    with pytest.raises(GeocodingUnavailableError) as captured:
        geocoder.geocode("Dax")

    assert calls == 5
    assert sleeps == [1.0, 2.0, 4.0, 8.0]
    assert captured.value.reason == "network"
    assert captured.value.status_code is None
    assert captured.value.attempts == 5
