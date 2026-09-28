"""Géoplateforme address geocoder adapter."""

import math
import re
import time
from collections.abc import Callable
from typing import Literal

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from radar.geography.contracts import (
    AddressNotFoundError,
    AddressOutsideMetropolitanFranceError,
    GeocodedAddress,
    GeocodingContractError,
    GeocodingFailureReason,
    GeocodingUnavailableError,
    StructuredAddress,
)

GEOCODING_URL = "https://data.geopf.fr/geocodage/search"
MAX_RESPONSE_BYTES = 1_000_000
MAX_HTTP_ATTEMPTS = 5
MAX_IN_PROCESS_RETRY_SECONDS = 60
MAX_RECORDED_RETRY_AFTER_SECONDS = 86_400
TEMPORARY_HTTP_STATUSES = frozenset({408, 425, 429})
_METROPOLITAN_CITY_CODE = re.compile(r"^(?:(?:0[1-9]|[1-8][0-9]|9[0-5])\d{3}|2[AB]\d{3})$")


class _Geometry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["Point"]
    coordinates: tuple[float, float]


class _Properties(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    label: str = Field(min_length=1, max_length=500)
    score: float | None = None
    housenumber: str | None = Field(default=None, max_length=32)
    id: str | None = Field(default=None, max_length=128)
    postcode: str | None = Field(default=None, max_length=16)
    citycode: str = Field(min_length=5, max_length=5)
    city: str | None = Field(default=None, max_length=200)
    context: str | None = Field(default=None, max_length=500)
    type: str | None = Field(default=None, max_length=64)
    street: str | None = Field(default=None, max_length=300)
    source_type: str | None = Field(default=None, alias="_type", max_length=64)


class _Feature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["Feature"]
    geometry: _Geometry
    properties: _Properties


class _FeatureCollection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["FeatureCollection"]
    features: list[_Feature] = Field(max_length=10)


def _is_metropolitan(feature: _Feature) -> bool:
    longitude, latitude = feature.geometry.coordinates
    return (
        _METROPOLITAN_CITY_CODE.fullmatch(feature.properties.citycode) is not None
        and math.isfinite(longitude)
        and math.isfinite(latitude)
        and -5.6 <= longitude <= 10.0
        and 41.0 <= latitude <= 51.6
    )


def _parse_retry_after(value: str | None) -> int | None:
    """Parse a bounded delta-seconds value without trusting provider-sized integers."""

    if value is None or not value.isdigit():
        return None
    if len(value) > 5:
        return MAX_RECORDED_RETRY_AFTER_SECONDS
    return min(int(value), MAX_RECORDED_RETRY_AFTER_SECONDS)


class GeoPlatformGeocoder:
    """Return the provider's highest-ranked metropolitan address result."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._owns_client = client is None
        self._sleeper = sleeper
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=10, read=20, write=10, pool=10),
            follow_redirects=False,
            headers={
                "Accept": "application/json",
                "User-Agent": "Radar/0.1 (private food-truck opportunity application)",
            },
        )

    def geocode(self, input_address: str) -> GeocodedAddress:
        """Query only the official address index and validate its GeoJSON response."""

        response = self._get_with_retry(input_address)
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise GeocodingContractError("the geocoder response is unexpectedly large")

        try:
            payload = _FeatureCollection.model_validate_json(response.content)
        except ValidationError as error:
            raise GeocodingContractError("the geocoder response schema changed") from error

        if not payload.features:
            raise AddressNotFoundError("no address matched the submitted text")

        candidate = next(
            (feature for feature in payload.features if _is_metropolitan(feature)), None
        )
        if candidate is None:
            raise AddressOutsideMetropolitanFranceError("no result belongs to metropolitan France")

        properties = candidate.properties
        longitude, latitude = candidate.geometry.coordinates
        if properties.score is not None and not 0 <= properties.score <= 1:
            raise GeocodingContractError("the geocoder score is outside its expected range")
        if properties.source_type not in {None, "address"}:
            raise GeocodingContractError("the geocoder returned a non-address result")

        return GeocodedAddress(
            normalized_label=properties.label,
            structured_address=StructuredAddress(
                house_number=properties.housenumber,
                street=properties.street,
                postcode=properties.postcode,
                city=properties.city,
                context=properties.context,
            ),
            longitude=longitude,
            latitude=latitude,
            municipality_code=properties.citycode,
            ban_id=properties.id,
            result_type=properties.type,
            score=properties.score,
            provider_name="Géoplateforme",
            provider_url=GEOCODING_URL,
        )

    def _get_with_retry(self, input_address: str) -> httpx.Response:
        """Retry short transient failures before delegating to the durable worker retry."""

        for attempt_index in range(MAX_HTTP_ATTEMPTS):
            attempts = attempt_index + 1
            retry_after_seconds: int | None = None
            try:
                response = self._client.get(
                    GEOCODING_URL,
                    params={"q": input_address, "limit": 5, "index": "address"},
                )
            except httpx.HTTPError as error:
                if attempts == MAX_HTTP_ATTEMPTS:
                    raise GeocodingUnavailableError(
                        "the geocoder request failed",
                        reason="network",
                        attempts=attempts,
                    ) from error
            else:
                if response.status_code == 200:
                    return response
                if (
                    response.status_code not in TEMPORARY_HTTP_STATUSES
                    and response.status_code < 500
                ):
                    raise GeocodingUnavailableError(
                        f"the geocoder returned HTTP {response.status_code}",
                        reason="request_rejected",
                        status_code=response.status_code,
                        attempts=attempts,
                    )
                retry_after = response.headers.get("Retry-After")
                retry_after_seconds = _parse_retry_after(retry_after)
                if attempts == MAX_HTTP_ATTEMPTS or (
                    retry_after_seconds is not None
                    and retry_after_seconds > MAX_IN_PROCESS_RETRY_SECONDS
                ):
                    if response.status_code == 429:
                        reason: GeocodingFailureReason = "rate_limited"
                    elif response.status_code >= 500:
                        reason = "server_error"
                    else:
                        reason = "temporary_http"
                    raise GeocodingUnavailableError(
                        f"the geocoder returned HTTP {response.status_code}",
                        reason=reason,
                        status_code=response.status_code,
                        retry_after_seconds=retry_after_seconds,
                        attempts=attempts,
                    )
            self._sleeper(max(float(2**attempt_index), float(retry_after_seconds or 0)))

        raise AssertionError("the bounded geocoder retry loop did not terminate")

    def close(self) -> None:
        """Close only the client created by this adapter."""

        if self._owns_client:
            self._client.close()
