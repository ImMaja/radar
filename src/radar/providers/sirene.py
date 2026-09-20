"""Strict read-only adapter for the Insee Sirene 3.11 establishment API."""

import hashlib
import math
import random
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from radar.prospects.contracts import (
    Activity,
    EstablishmentAddress,
    LambertCoordinates,
    ProspectCandidate,
)

SIRENE_BASE_URL = "https://api.insee.fr/api-sirene/3.11"
SIRET_URL = f"{SIRENE_BASE_URL}/siret"
INFORMATION_URL = f"{SIRENE_BASE_URL}/informations"
API_KEY_HEADER = "X-INSEE-Api-Key-Integration"
PAGE_SIZE = 1_000
MAX_MUNICIPALITIES_PER_BATCH = 30
MAX_RESPONSE_BYTES = 25_000_000

_MUNICIPALITY_CODE = re.compile(r"^(?:(?:0[1-9]|[1-8][0-9]|9[0-5])\d{3}|2[AB]\d{3})$")
MIN_REQUEST_INTERVAL_SECONDS = 2.0
MAX_HTTP_ATTEMPTS = 4
MAX_IN_PROCESS_RETRY_SECONDS = 60

SIRET_FIELDS: tuple[str, ...] = (
    "siret",
    "siren",
    "etablissementSiege",
    "statutDiffusionEtablissement",
    "trancheEffectifsEtablissement",
    "anneeEffectifsEtablissement",
    "dateCreationEtablissement",
    "dateDernierTraitementEtablissement",
    "identifiantAdresseEtablissement",
    "numeroVoieEtablissement",
    "indiceRepetitionEtablissement",
    "typeVoieEtablissement",
    "libelleVoieEtablissement",
    "complementAdresseEtablissement",
    "codePostalEtablissement",
    "libelleCommuneEtablissement",
    "codeCommuneEtablissement",
    "coordonneeLambertAbscisseEtablissement",
    "coordonneeLambertOrdonneeEtablissement",
    "dateDebut",
    "dateFin",
    "etatAdministratifEtablissement",
    "enseigne1Etablissement",
    "enseigne2Etablissement",
    "enseigne3Etablissement",
    "denominationUsuelleEtablissement",
    "activitePrincipaleEtablissement",
    "nomenclatureActivitePrincipaleEtablissement",
    "statutDiffusionUniteLegale",
    "etatAdministratifUniteLegale",
    "denominationUniteLegale",
    "denominationUsuelle1UniteLegale",
    "denominationUsuelle2UniteLegale",
    "denominationUsuelle3UniteLegale",
    "categorieJuridiqueUniteLegale",
    "dateDernierTraitementUniteLegale",
)


class SireneAdapterError(RuntimeError):
    """Base class for controlled failures that never contain the API key."""


class SireneRequestError(SireneAdapterError):
    """The request is invalid and must not be retried unchanged."""


class SireneAuthenticationError(SireneAdapterError):
    """The configured API subscription cannot access Sirene."""


class SireneTemporaryError(SireneAdapterError):
    """The provider or network is temporarily unavailable."""

    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class SireneContractError(SireneAdapterError):
    """The provider response no longer satisfies the validated contract."""


class _SireneModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _Header(_SireneModel):
    status: int = Field(alias="statut")
    message: str
    total: int = Field(ge=0)
    start: int = Field(alias="debut", ge=0)
    count: int = Field(alias="nombre", ge=0, le=PAGE_SIZE)
    cursor: str = Field(alias="curseur", min_length=1, max_length=20_000)
    next_cursor: str | None = Field(
        default=None,
        alias="curseurSuivant",
        max_length=20_000,
    )


class _Address(_SireneModel):
    address_identifier: str | None = Field(
        default=None,
        alias="identifiantAdresseEtablissement",
        max_length=128,
    )
    street_number: str | None = Field(
        default=None,
        alias="numeroVoieEtablissement",
        max_length=32,
    )
    repetition_index: str | None = Field(
        default=None,
        alias="indiceRepetitionEtablissement",
        max_length=16,
    )
    street_type: str | None = Field(
        default=None,
        alias="typeVoieEtablissement",
        max_length=64,
    )
    street_label: str | None = Field(
        default=None,
        alias="libelleVoieEtablissement",
        max_length=300,
    )
    address_complement: str | None = Field(
        default=None,
        alias="complementAdresseEtablissement",
        max_length=300,
    )
    postcode: str | None = Field(
        default=None,
        alias="codePostalEtablissement",
        max_length=16,
    )
    municipality_label: str | None = Field(
        default=None,
        alias="libelleCommuneEtablissement",
        max_length=200,
    )
    municipality_code: str | None = Field(
        default=None,
        alias="codeCommuneEtablissement",
        max_length=5,
    )
    lambert_x: str | None = Field(
        default=None,
        alias="coordonneeLambertAbscisseEtablissement",
        max_length=64,
    )
    lambert_y: str | None = Field(
        default=None,
        alias="coordonneeLambertOrdonneeEtablissement",
        max_length=64,
    )


class _Period(_SireneModel):
    started_on: str = Field(alias="dateDebut", pattern=r"^\d{4}-\d{2}-\d{2}$")
    ended_on: str | None = Field(
        default=None,
        alias="dateFin",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    administrative_state: Literal["A", "F"] = Field(alias="etatAdministratifEtablissement")
    usual_name: str | None = Field(
        default=None,
        alias="denominationUsuelleEtablissement",
        max_length=300,
    )
    trade_name_1: str | None = Field(
        default=None,
        alias="enseigne1Etablissement",
        max_length=300,
    )
    trade_name_2: str | None = Field(
        default=None,
        alias="enseigne2Etablissement",
        max_length=300,
    )
    trade_name_3: str | None = Field(
        default=None,
        alias="enseigne3Etablissement",
        max_length=300,
    )
    activity_code: str | None = Field(
        default=None,
        alias="activitePrincipaleEtablissement",
        max_length=16,
    )
    activity_nomenclature: str | None = Field(
        default=None,
        alias="nomenclatureActivitePrincipaleEtablissement",
        max_length=64,
    )


class _LegalUnit(_SireneModel):
    diffusion_status: Literal["O", "P"] = Field(alias="statutDiffusionUniteLegale")
    administrative_state: Literal["A", "C"] = Field(alias="etatAdministratifUniteLegale")
    legal_name: str | None = Field(
        default=None,
        alias="denominationUniteLegale",
        max_length=300,
    )
    usual_name_1: str | None = Field(
        default=None,
        alias="denominationUsuelle1UniteLegale",
        max_length=300,
    )
    usual_name_2: str | None = Field(
        default=None,
        alias="denominationUsuelle2UniteLegale",
        max_length=300,
    )
    usual_name_3: str | None = Field(
        default=None,
        alias="denominationUsuelle3UniteLegale",
        max_length=300,
    )
    legal_category: str | None = Field(
        default=None,
        alias="categorieJuridiqueUniteLegale",
        max_length=8,
    )
    processed_at: str | None = Field(
        default=None,
        alias="dateDernierTraitementUniteLegale",
        max_length=64,
    )


class _Establishment(_SireneModel):
    siret: str = Field(pattern=r"^\d{14}$")
    siren: str = Field(pattern=r"^\d{9}$")
    is_head_office: bool = Field(alias="etablissementSiege")
    diffusion_status: Literal["O", "P"] = Field(alias="statutDiffusionEtablissement")
    employee_band: str | None = Field(
        default=None,
        alias="trancheEffectifsEtablissement",
        max_length=8,
    )
    employee_year: int | None = Field(
        default=None,
        alias="anneeEffectifsEtablissement",
        ge=1800,
        le=2200,
    )
    created_on: str | None = Field(
        default=None,
        alias="dateCreationEtablissement",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    processed_at: str | None = Field(
        default=None,
        alias="dateDernierTraitementEtablissement",
        max_length=64,
    )
    address: _Address = Field(alias="adresseEtablissement")
    periods: list[_Period] = Field(alias="periodesEtablissement", min_length=1, max_length=10_000)
    legal_unit: _LegalUnit = Field(alias="uniteLegale")


class _SearchResponse(_SireneModel):
    header: _Header
    establishments: list[_Establishment] = Field(
        alias="etablissements",
        max_length=PAGE_SIZE,
    )


class _Freshness(_SireneModel):
    collection: str = Field(min_length=1, max_length=100)
    last_bulk_processing: str | None = Field(
        default=None,
        alias="dateDernierTraitementDeMasse",
        max_length=64,
    )
    latest_processing: str | None = Field(
        default=None,
        alias="dateDernierTraitementMaximum",
        max_length=64,
    )
    last_availability: str | None = Field(
        default=None,
        alias="dateDerniereMiseADisposition",
        max_length=64,
    )


class _InformationResponse(_SireneModel):
    service_state: str = Field(alias="etatService", min_length=1, max_length=100)
    service_version: str = Field(alias="versionService", min_length=1, max_length=100)
    freshness: list[_Freshness] = Field(alias="datesDernieresMisesAJourDesDonnees")


@dataclass(frozen=True)
class SireneServiceInformation:
    """Public version and source-freshness metadata captured at cycle start."""

    service_state: str
    service_version: str
    freshness: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class SirenePage:
    """One validated page without raw provider payload or rejected identifiers."""

    number: int
    announced_total: int
    received_count: int
    importable_candidates: tuple[ProspectCandidate, ...]
    rejection_counts: dict[str, int]
    next_cursor_fingerprint: str | None
    terminal: bool


@dataclass(frozen=True)
class SireneBatchSummary:
    """Completeness evidence for one disjoint municipality batch."""

    announced_total: int
    received_count: int
    unique_siret_count: int
    importable_count: int
    page_count: int
    rejection_counts: dict[str, int]


def build_establishment_query(municipality_codes: Sequence[str]) -> str:
    """Build the validated current-state selection for one bounded disjoint batch."""

    codes = tuple(municipality_codes)
    if not 1 <= len(codes) <= MAX_MUNICIPALITIES_PER_BATCH:
        raise ValueError("a Sirene batch must contain between 1 and 30 municipality codes")
    if len(set(codes)) != len(codes):
        raise ValueError("a Sirene batch cannot contain duplicate municipality codes")
    if any(_MUNICIPALITY_CODE.fullmatch(code) is None for code in codes):
        raise ValueError("a Sirene batch contains an invalid municipality code")
    municipality_filter = " OR ".join(f"codeCommuneEtablissement:{code}" for code in codes)
    return (
        f"({municipality_filter}) "
        "AND periode(etatAdministratifEtablissement:A) "
        "AND etatAdministratifUniteLegale:A "
        "AND statutDiffusionEtablissement:O "
        "AND statutDiffusionUniteLegale:O"
    )


def partition_municipalities(
    municipality_codes: Sequence[str],
) -> tuple[tuple[str, ...], ...]:
    """Create stable disjoint Sirene batches without silently removing duplicates."""

    codes = tuple(municipality_codes)
    if not codes:
        raise ValueError("at least one municipality is required for a Sirene collection")
    if len(set(codes)) != len(codes):
        raise ValueError("Sirene municipality batches must be disjoint")
    if any(_MUNICIPALITY_CODE.fullmatch(code) is None for code in codes):
        raise ValueError("a Sirene collection contains an invalid municipality code")
    return tuple(
        codes[index : index + MAX_MUNICIPALITIES_PER_BATCH]
        for index in range(0, len(codes), MAX_MUNICIPALITIES_PER_BATCH)
    )


def _non_empty(values: Sequence[str | None]) -> tuple[str, ...]:
    return tuple(value.strip() for value in values if value is not None and value.strip())


def _coordinates(address: _Address) -> LambertCoordinates | None:
    if address.lambert_x is None or address.lambert_y is None:
        return None
    try:
        x = float(address.lambert_x)
        y = float(address.lambert_y)
    except ValueError:
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return LambertCoordinates(x, y)


def _normalize_candidate(
    establishment: _Establishment,
    requested_codes: frozenset[str],
) -> tuple[ProspectCandidate | None, str | None]:
    if establishment.diffusion_status != "O" or establishment.legal_unit.diffusion_status != "O":
        return None, "partial_diffusion"
    current_periods = [period for period in establishment.periods if period.ended_on is None]
    if len(current_periods) != 1:
        return None, "invalid_current_period"
    current = current_periods[0]
    if current.administrative_state != "A":
        return None, "closed_establishment"
    if establishment.legal_unit.administrative_state != "A":
        return None, "ceased_legal_unit"
    municipality_code = establishment.address.municipality_code
    if municipality_code is None or municipality_code not in requested_codes:
        return None, "unexpected_municipality"
    activity = None
    if current.activity_code is not None and current.activity_nomenclature is not None:
        activity = Activity(current.activity_code, current.activity_nomenclature)
    elif current.activity_code is not None or current.activity_nomenclature is not None:
        return None, "incomplete_activity"

    return (
        ProspectCandidate(
            siret=establishment.siret,
            siren=establishment.siren,
            is_head_office=establishment.is_head_office,
            establishment_names=_non_empty(
                (
                    current.trade_name_1,
                    current.trade_name_2,
                    current.trade_name_3,
                    current.usual_name,
                )
            ),
            legal_name=establishment.legal_unit.legal_name,
            legal_usual_names=_non_empty(
                (
                    establishment.legal_unit.usual_name_1,
                    establishment.legal_unit.usual_name_2,
                    establishment.legal_unit.usual_name_3,
                )
            ),
            legal_category=establishment.legal_unit.legal_category,
            activity=activity,
            employee_band=establishment.employee_band,
            employee_year=establishment.employee_year,
            address=EstablishmentAddress(
                address_identifier=establishment.address.address_identifier,
                street_number=establishment.address.street_number,
                repetition_index=establishment.address.repetition_index,
                street_type=establishment.address.street_type,
                street_label=establishment.address.street_label,
                address_complement=establishment.address.address_complement,
                postcode=establishment.address.postcode,
                municipality_label=establishment.address.municipality_label,
                municipality_code=municipality_code,
                coordinates=_coordinates(establishment.address),
            ),
            establishment_created_on=establishment.created_on,
            current_period_started_on=current.started_on,
            establishment_processed_at=establishment.processed_at,
            legal_unit_processed_at=establishment.legal_unit.processed_at,
        ),
        None,
    )


class SireneClient:
    """Read and validate bounded Sirene pages without touching persistence."""

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = lambda: random.uniform(0, 0.25),
    ) -> None:
        if not api_key:
            raise ValueError("the Sirene API key cannot be empty")
        self._owns_client = client is None
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._jitter = jitter
        self._next_request_at = 0.0
        self._request_headers = {
            API_KEY_HEADER: api_key,
            "Accept": "application/json",
            "User-Agent": "Radar/0.1 (private food-truck opportunity application)",
        }
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=10, read=60, write=30, pool=10),
            follow_redirects=False,
        )

    def service_information(self) -> SireneServiceInformation:
        """Read version and freshness before beginning a collection cycle."""

        response = self._get(INFORMATION_URL)
        try:
            payload = _InformationResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise SireneContractError("the Sirene information schema changed") from error
        return SireneServiceInformation(
            service_state=payload.service_state,
            service_version=payload.service_version,
            freshness=tuple(
                (item.collection, item.last_availability) for item in payload.freshness
            ),
        )

    def collect_batch(
        self,
        municipality_codes: Sequence[str],
        at_date: str,
        on_page: Callable[[SirenePage], None],
    ) -> SireneBatchSummary:
        """Traverse from `*` to the empty terminal page and reconcile totals."""

        query = build_establishment_query(municipality_codes)
        try:
            parsed_date = date.fromisoformat(at_date)
        except ValueError as error:
            raise ValueError("the Sirene collection date must use YYYY-MM-DD") from error
        if parsed_date.isoformat() != at_date:
            raise ValueError("the Sirene collection date must use YYYY-MM-DD")
        requested_codes = frozenset(municipality_codes)
        cursor = "*"
        seen_cursors = {cursor}
        seen_sirets: set[str] = set()
        announced_total: int | None = None
        received_count = 0
        importable_count = 0
        page_number = 0
        rejection_counts: Counter[str] = Counter()

        while True:
            response = self._get(
                SIRET_URL,
                params={
                    "q": query,
                    "date": at_date,
                    "nombre": PAGE_SIZE,
                    "curseur": cursor,
                    "champs": ",".join(SIRET_FIELDS),
                },
            )
            payload = self._search_payload(response)
            if announced_total is None:
                announced_total = payload.header.total
            elif payload.header.total != announced_total:
                raise SireneContractError("the announced Sirene total changed within one batch")
            header_total = response.headers.get("X-Total-Count")
            if header_total is not None:
                try:
                    response_total = int(header_total)
                except ValueError as error:
                    raise SireneContractError("the Sirene HTTP total is invalid") from error
                if response_total != payload.header.total:
                    raise SireneContractError("the Sirene body and HTTP totals disagree")

            establishments = payload.establishments
            page_number += 1
            if not establishments:
                on_page(
                    SirenePage(
                        number=page_number,
                        announced_total=announced_total,
                        received_count=0,
                        importable_candidates=(),
                        rejection_counts={},
                        next_cursor_fingerprint=None,
                        terminal=True,
                    )
                )
                if received_count != announced_total:
                    raise SireneContractError("the terminal Sirene count is incomplete")
                break

            page_rejections: Counter[str] = Counter()
            candidates: list[ProspectCandidate] = []
            for establishment in establishments:
                if establishment.siret in seen_sirets:
                    raise SireneContractError("Sirene returned a duplicate SIRET in one batch")
                seen_sirets.add(establishment.siret)
                candidate, rejection = _normalize_candidate(establishment, requested_codes)
                if candidate is not None:
                    candidates.append(candidate)
                elif rejection is not None:
                    page_rejections[rejection] += 1
            received_count += len(establishments)
            importable_count += len(candidates)
            rejection_counts.update(page_rejections)
            next_cursor = payload.header.next_cursor
            if next_cursor is None or not next_cursor:
                raise SireneContractError("a non-terminal Sirene page has no next cursor")
            on_page(
                SirenePage(
                    number=page_number,
                    announced_total=announced_total,
                    received_count=len(establishments),
                    importable_candidates=tuple(candidates),
                    rejection_counts=dict(page_rejections),
                    next_cursor_fingerprint=hashlib.sha256(next_cursor.encode()).hexdigest(),
                    terminal=False,
                )
            )

            if next_cursor in seen_cursors:
                raise SireneContractError("the Sirene cursor looped before its terminal page")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        assert announced_total is not None
        return SireneBatchSummary(
            announced_total=announced_total,
            received_count=received_count,
            unique_siret_count=len(seen_sirets),
            importable_count=importable_count,
            page_count=page_number,
            rejection_counts=dict(rejection_counts),
        )

    def _search_payload(self, response: httpx.Response) -> _SearchResponse:
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise SireneContractError("the Sirene response is unexpectedly large")
        try:
            payload = _SearchResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise SireneContractError("the Sirene establishment schema changed") from error
        if payload.header.status != 200:
            raise SireneContractError("the Sirene response header does not report success")
        if payload.header.count != len(payload.establishments):
            raise SireneContractError("the Sirene page count is inconsistent")
        return payload

    def _get(
        self,
        url: str,
        params: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> httpx.Response:
        last_temporary_error: SireneTemporaryError | None = None
        for attempt in range(MAX_HTTP_ATTEMPTS):
            self._wait_for_rate_limit()
            try:
                response = self._client.get(url, params=params, headers=self._request_headers)
            except httpx.HTTPError:
                last_temporary_error = SireneTemporaryError("the Sirene request failed")
            else:
                if response.status_code in {401, 403}:
                    raise SireneAuthenticationError(
                        "the Sirene API rejected its configured subscription"
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = response.headers.get("Retry-After")
                    retry_seconds = (
                        int(retry_after) if retry_after and retry_after.isdigit() else None
                    )
                    last_temporary_error = SireneTemporaryError(
                        f"the Sirene API returned HTTP {response.status_code}",
                        retry_after_seconds=retry_seconds,
                    )
                elif response.status_code != 200:
                    raise SireneRequestError(f"the Sirene API returned HTTP {response.status_code}")
                else:
                    if len(response.content) > MAX_RESPONSE_BYTES:
                        raise SireneContractError("the Sirene response is unexpectedly large")
                    return response

            assert last_temporary_error is not None
            retry_after_seconds = last_temporary_error.retry_after_seconds
            if attempt == MAX_HTTP_ATTEMPTS - 1 or (
                retry_after_seconds is not None
                and retry_after_seconds > MAX_IN_PROCESS_RETRY_SECONDS
            ):
                raise last_temporary_error
            backoff = 2**attempt + self._jitter()
            self._sleeper(max(backoff, float(retry_after_seconds or 0)))

        raise AssertionError("the bounded Sirene retry loop did not terminate")

    def _wait_for_rate_limit(self) -> None:
        remaining = self._next_request_at - self._monotonic()
        if remaining > 0:
            self._sleeper(remaining)
        self._next_request_at = self._monotonic() + MIN_REQUEST_INTERVAL_SECONDS

    def close(self) -> None:
        """Close only the HTTP client created by this adapter."""

        if self._owns_client:
            self._client.close()
