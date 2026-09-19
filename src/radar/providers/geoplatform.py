"""Géoplateforme address geocoder adapter."""

import math
import re
from typing import Literal

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from radar.geography.contracts import (
    AddressNotFoundError,
    AddressOutsideMetropolitanFranceError,
    GeocodedAddress,
    GeocodingContractError,
    GeocodingUnavailableError,
    StructuredAddress,
)

GEOCODING_URL = "https://data.geopf.fr/geocodage/search"
MAX_RESPONSE_BYTES = 1_000_000
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


class GeoPlatformGeocoder:
    """Return the provider's highest-ranked metropolitan address result."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=10, read=60, write=30, pool=10),
            follow_redirects=False,
            headers={
                "Accept": "application/json",
                "User-Agent": "Radar/0.1 (private food-truck opportunity application)",
            },
        )

    def geocode(self, input_address: str) -> GeocodedAddress:
        """Query only the official address index and validate its GeoJSON response."""

        try:
            response = self._client.get(
                GEOCODING_URL,
                params={"q": input_address, "limit": 5, "index": "address"},
            )
        except httpx.HTTPError as error:
            raise GeocodingUnavailableError("the geocoder request failed") from error

        if response.status_code != 200:
            raise GeocodingUnavailableError(f"the geocoder returned HTTP {response.status_code}")
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

    def close(self) -> None:
        """Close only the client created by this adapter."""

        if self._owns_client:
            self._client.close()
