"""Contract tests for the isolated Sirene 3.11 read adapter."""

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx2 as httpx
import pytest

from radar.providers.sirene import (
    API_KEY_HEADER,
    INFORMATION_URL,
    MAX_MUNICIPALITIES_PER_BATCH,
    SIRET_URL,
    SireneAuthenticationError,
    SireneClient,
    SireneContractError,
    SirenePage,
    SireneTemporaryError,
    build_establishment_query,
    partition_municipalities,
)

API_KEY = "test-key-never-logged"


@dataclass
class FakeTime:
    current: float = 100.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds


def establishment(
    *,
    siret: str = "12345678901234",
    municipality_code: str = "40088",
    establishment_state: str = "A",
    establishment_diffusion: str = "O",
    legal_state: str = "A",
    legal_diffusion: str = "O",
) -> dict[str, object]:
    return {
        "siret": siret,
        "siren": siret[:9],
        "etablissementSiege": True,
        "statutDiffusionEtablissement": establishment_diffusion,
        "trancheEffectifsEtablissement": "12",
        "anneeEffectifsEtablissement": "2024",
        "dateCreationEtablissement": "2014-05-06",
        "dateDernierTraitementEtablissement": "2026-09-18T10:15:00",
        "adresseEtablissement": {
            "identifiantAdresseEtablissement": "40088_example",
            "numeroVoieEtablissement": "12",
            "typeVoieEtablissement": "RUE",
            "libelleVoieEtablissement": "SAINT PIERRE",
            "codePostalEtablissement": "40100",
            "libelleCommuneEtablissement": "DAX",
            "codeCommuneEtablissement": municipality_code,
            "coordonneeLambertAbscisseEtablissement": "376512.25",
            "coordonneeLambertOrdonneeEtablissement": "6301188.75",
        },
        "periodesEtablissement": [
            {
                "dateDebut": "2025-01-01",
                "dateFin": None,
                "etatAdministratifEtablissement": establishment_state,
                "enseigne1Etablissement": "ATELIER TEST",
                "denominationUsuelleEtablissement": "SITE DE DAX",
                "activitePrincipaleEtablissement": "56.10C",
                "nomenclatureActivitePrincipaleEtablissement": "NAFRev2",
            }
        ],
        "uniteLegale": {
            "statutDiffusionUniteLegale": legal_diffusion,
            "etatAdministratifUniteLegale": legal_state,
            "denominationUniteLegale": "ENTREPRISE TEST",
            "denominationUsuelle1UniteLegale": "TEST",
            "categorieJuridiqueUniteLegale": "5710",
            "dateDernierTraitementUniteLegale": "2026-09-18T09:00:00",
            "nomUniteLegale": "PERSONAL NAME MUST BE IGNORED",
            "prenomUsuelUniteLegale": "IGNORED",
        },
    }


def search_response(
    establishments: list[dict[str, object]],
    *,
    total: int,
    cursor: str,
    next_cursor: str | None,
) -> dict[str, object]:
    return {
        "header": {
            "statut": 200,
            "message": "OK",
            "total": total,
            "debut": 0,
            "nombre": len(establishments),
            "curseur": cursor,
            "curseurSuivant": next_cursor,
        },
        "etablissements": establishments,
    }


def information_response() -> dict[str, object]:
    return {
        "header": {"statut": 200, "message": "OK"},
        "etatService": "UP",
        "versionService": "3.11.95",
        "journalDesModifications": "not retained",
        "datesDernieresMisesAJourDesDonnees": [
            {
                "collection": "Établissements",
                "dateDernierTraitementDeMasse": "2026-09-19T00:00:00",
                "dateDernierTraitementMaximum": "2026-09-20T06:00:00",
                "dateDerniereMiseADisposition": "2026-09-20T07:44:27",
            }
        ],
    }


def client_for(
    handler: Callable[[httpx.Request], httpx.Response],
    fake_time: FakeTime | None = None,
) -> SireneClient:
    clock = fake_time or FakeTime()
    return SireneClient(
        API_KEY,
        httpx.Client(transport=httpx.MockTransport(handler)),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        jitter=lambda: 0.0,
    )


def test_builds_the_validated_query_and_bounds_municipality_batches() -> None:
    query = build_establishment_query(("40088", "40192"))

    assert query == (
        "(codeCommuneEtablissement:40088 OR codeCommuneEtablissement:40192) "
        "AND periode(etatAdministratifEtablissement:A) "
        "AND etatAdministratifUniteLegale:A "
        "AND statutDiffusionEtablissement:O "
        "AND statutDiffusionUniteLegale:O"
    )
    with pytest.raises(ValueError):
        build_establishment_query(())
    with pytest.raises(ValueError):
        build_establishment_query(tuple("40088" for _ in range(2)))
    with pytest.raises(ValueError):
        build_establishment_query(tuple(f"40{index:03d}" for index in range(31)))
    with pytest.raises(ValueError):
        build_establishment_query(("97105",))
    assert "2A004" in build_establishment_query(("2A004",))
    assert MAX_MUNICIPALITIES_PER_BATCH == 30


def test_partitions_municipalities_into_stable_disjoint_batches_of_thirty() -> None:
    codes = tuple(f"40{index:03d}" for index in range(65))

    batches = partition_municipalities(codes)

    assert [len(batch) for batch in batches] == [30, 30, 5]
    assert tuple(code for batch in batches for code in batch) == codes
    with pytest.raises(ValueError, match="disjoint"):
        partition_municipalities(("40088", "40088"))


def test_collects_until_the_empty_page_and_normalizes_only_useful_public_fields() -> None:
    requests: list[httpx.Request] = []
    responses = [
        search_response(
            [establishment()],
            total=1,
            cursor="*",
            next_cursor="opaque-next-cursor",
        ),
        search_response([], total=1, cursor="opaque-next-cursor", next_cursor=None),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = responses.pop(0)
        return httpx.Response(
            200,
            json=payload,
            headers={"X-Total-Count": "1"},
            request=request,
        )

    pages: list[SirenePage] = []
    fake_time = FakeTime()
    adapter = client_for(handler, fake_time)
    summary = adapter.collect_batch(("40088",), "2026-09-20", pages.append)

    assert summary.announced_total == 1
    assert summary.received_count == 1
    assert summary.unique_siret_count == 1
    assert summary.importable_count == 1
    assert summary.page_count == 2
    assert len(pages) == 2
    candidate = pages[0].importable_candidates[0]
    assert candidate.siret == "12345678901234"
    assert candidate.establishment_names == ("ATELIER TEST", "SITE DE DAX")
    assert candidate.legal_name == "ENTREPRISE TEST"
    assert candidate.activity is not None
    assert candidate.activity.code == "56.10C"
    assert candidate.activity.nomenclature == "NAFRev2"
    assert candidate.address.coordinates is not None
    assert candidate.address.coordinates.crs == "EPSG:2154"
    assert not hasattr(candidate, "personal_name")
    assert pages[0].terminal is False
    assert pages[0].next_cursor_fingerprint is not None
    assert "opaque-next-cursor" not in pages[0].next_cursor_fingerprint
    assert pages[1].terminal is True
    assert pages[1].received_count == 0

    assert len(requests) == 2
    assert requests[0].headers[API_KEY_HEADER] == API_KEY
    assert API_KEY not in str(requests[0].url)
    assert requests[0].url == httpx.URL(SIRET_URL, params=requests[0].url.params)
    assert requests[0].url.params["date"] == "2026-09-20"
    assert requests[0].url.params["nombre"] == "1000"
    assert requests[0].url.params["curseur"] == "*"
    assert "nomUniteLegale" not in requests[0].url.params["champs"]
    assert requests[1].url.params["curseur"] == "opaque-next-cursor"
    assert fake_time.sleeps == [2.0]


def test_rejects_an_invalid_date_before_any_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, request=request)

    adapter = client_for(handler)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        adapter.collect_batch(("40088",), "20/09/2026", lambda _: None)
    assert calls == 0


def test_counts_a_concurrent_closed_object_without_exposing_it_as_a_candidate() -> None:
    responses = [
        search_response(
            [establishment(establishment_state="F")],
            total=1,
            cursor="*",
            next_cursor="terminal",
        ),
        search_response([], total=1, cursor="terminal", next_cursor=None),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0), request=request)

    pages: list[SirenePage] = []
    summary = client_for(handler).collect_batch(("40088",), "2026-09-20", pages.append)

    assert summary.received_count == 1
    assert summary.importable_count == 0
    assert summary.rejection_counts == {"closed_establishment": 1}
    assert pages[0].importable_candidates == ()


def test_rejects_duplicates_cursor_loops_and_incoherent_totals() -> None:
    duplicate_payload = search_response(
        [establishment(), establishment()],
        total=2,
        cursor="*",
        next_cursor="next",
    )

    def duplicate_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=duplicate_payload, request=request)

    with pytest.raises(SireneContractError, match="duplicate SIRET"):
        client_for(duplicate_handler).collect_batch(("40088",), "2026-09-20", lambda _: None)

    loop_payload = search_response(
        [establishment()],
        total=1,
        cursor="*",
        next_cursor="*",
    )

    def loop_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=loop_payload, request=request)

    with pytest.raises(SireneContractError, match="cursor looped"):
        client_for(loop_handler).collect_batch(("40088",), "2026-09-20", lambda _: None)

    incomplete_responses = [
        search_response(
            [establishment()],
            total=2,
            cursor="*",
            next_cursor="terminal",
        ),
        search_response([], total=2, cursor="terminal", next_cursor=None),
    ]

    def incomplete_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=incomplete_responses.pop(0), request=request)

    with pytest.raises(SireneContractError, match="count is incomplete"):
        client_for(incomplete_handler).collect_batch(
            ("40088",),
            "2026-09-20",
            lambda _: None,
        )


def test_reads_service_freshness_without_retaining_the_journal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == INFORMATION_URL
        return httpx.Response(200, json=information_response(), request=request)

    information = client_for(handler).service_information()

    assert information.service_state == "UP"
    assert information.service_version == "3.11.95"
    assert information.freshness == (("Établissements", "2026-09-20T07:44:27"),)
    assert not hasattr(information, "journal")


def test_retries_short_temporary_failures_but_not_authentication_or_long_waits() -> None:
    fake_time = FakeTime()
    calls = 0

    def retry_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, request=request)
        return httpx.Response(200, json=information_response(), request=request)

    information = client_for(retry_handler, fake_time).service_information()
    assert information.service_version == "3.11.95"
    assert calls == 2
    assert fake_time.sleeps == [3.0]

    def authentication_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    with pytest.raises(SireneAuthenticationError):
        client_for(authentication_handler).service_information()

    long_wait_calls = 0

    def long_wait_handler(request: httpx.Request) -> httpx.Response:
        nonlocal long_wait_calls
        long_wait_calls += 1
        return httpx.Response(429, headers={"Retry-After": "120"}, request=request)

    with pytest.raises(SireneTemporaryError) as captured:
        client_for(long_wait_handler).service_information()
    assert captured.value.retry_after_seconds == 120
    assert long_wait_calls == 1
