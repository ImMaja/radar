"""Contract tests for the isolated DATAtourisme v1 event adapter."""

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

import httpx2 as httpx
import pytest

from radar.providers.datatourisme import (
    API_KEY_HEADER,
    EVENT_FIELDS,
    EVENT_PATH,
    EVENT_URL,
    PAGE_SIZE,
    DatatourismeAuthenticationError,
    DatatourismeClient,
    DatatourismeContractError,
    DatatourismePage,
    DatatourismeRequestError,
    DatatourismeTemporaryError,
)

API_KEY = "datatourisme-test-key-never-logged"


@dataclass
class FakeTime:
    current: float = 100.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds


def next_link(cursor: str = "opaque-cursor", **overrides: str) -> str:
    params = {
        "geo_distance": "43.708840,-1.051952,50000m",
        "page_size": "100",
        "lang": "fr",
        "fields": ",".join(EVENT_FIELDS),
        "crs": cursor,
        **overrides,
    }
    return str(httpx.URL(EVENT_URL, params=params))


def event(number: int, *, title: str | None = "Fête locale") -> dict[str, object]:
    identifier = str(UUID(int=number + 1))
    label = {} if title is None else {"@fr": title}
    return {
        "uuid": identifier,
        "uri": f"https://data.datatourisme.fr/{identifier}",
        "identifier": f"source-{number}",
        "label": label,
        "type": ["EntertainmentAndEvent", "Festival"],
        "isLocatedAt": [
            {
                "geo": {"latitude": 43.70884, "longitude": -1.051952},
                "address": [
                    {
                        "streetAddress": ["Place de la Mairie"],
                        "postalCode": "40100",
                        "addressLocality": "Dax",
                        "hasAddressCity": {"insee": "40088"},
                    }
                ],
            }
        ],
        "hasDescription": [
            {
                "shortDescription": {"@fr": "Une fête publique."},
                "description": {"@fr": "Une description plus complète."},
            }
        ],
        "takesPlaceAt": [
            {
                "startDate": "2027-07-12",
                "endDate": "2027-07-13",
                "startTime": "10:00:00",
                "endTime": "23:00:00",
            }
        ],
        "hasContact": [
            {
                "legalName": "Accueil",
                "telephone": ["+33500000000"],
                "homepage": ["https://example.test/event"],
            }
        ],
        "hasBookingContact": [
            {
                "legalName": "Réservation",
                "telephone": ["+33500000001"],
                "homepage": ["https://example.test/booking"],
            }
        ],
        "hasBeenCreatedBy": {
            "identifier": "producer-1",
            "legalName": "Producteur de données",
            "telephone": ["+33500000002"],
            "homepage": ["https://producer.example.test"],
        },
        "hasBeenPublishedBy": [{"legalName": "Diffuseur de données"}],
        "isOwnedBy": [{"legalName": "Propriétaire de données"}],
        "lastUpdate": "2026-09-29T12:00:00+00:00",
        "lastUpdateDatatourisme": "2026-09-29T13:00:00+00:00",
    }


def page_response(
    objects: list[dict[str, object]],
    *,
    total: int,
    page: int,
    total_pages: int,
    next_link: str | None,
) -> dict[str, object]:
    return {
        "objects": objects,
        "meta": {
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "total_pages": total_pages,
            "next": next_link,
            "previous": None,
        },
    }


def client_for(
    handler: Callable[[httpx.Request], httpx.Response],
    fake_time: FakeTime | None = None,
) -> DatatourismeClient:
    clock = fake_time or FakeTime()
    return DatatourismeClient(
        API_KEY,
        httpx.Client(transport=httpx.MockTransport(handler)),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        jitter=lambda: 0.0,
    )


def test_collects_safe_next_pages_and_normalizes_without_inferred_organizer() -> None:
    requests: list[httpx.Request] = []
    provider_next_link = f"{next_link()}&api_key=provider-leak"
    responses = [
        page_response(
            [event(index) for index in range(100)],
            total=101,
            page=1,
            total_pages=2,
            next_link=provider_next_link,
        ),
        page_response(
            [event(100)],
            total=101,
            page=2,
            total_pages=2,
            next_link=None,
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=responses.pop(0), request=request)

    pages: list[DatatourismePage] = []
    fake_time = FakeTime()
    summary = client_for(handler, fake_time).collect_events(
        43.70884,
        -1.051952,
        50_000,
        pages.append,
    )

    assert summary.announced_total == 101
    assert summary.received_count == 101
    assert summary.unique_uuid_count == 101
    assert summary.importable_count == 101
    assert summary.page_count == 2
    assert summary.rejection_counts == {}
    assert [page.received_count for page in pages] == [100, 1]
    assert pages[0].next_link_fingerprint is not None
    assert len(pages[0].next_link_fingerprint or "") == 64
    assert "opaque-cursor" not in (pages[0].next_link_fingerprint or "")
    assert pages[1].terminal is True

    candidate = pages[0].importable_candidates[0]
    assert candidate.title == "Fête locale"
    assert candidate.types == ("EntertainmentAndEvent", "Festival")
    assert candidate.locations[0].addresses[0].municipality_code == "40088"
    assert candidate.periods[0].start_date == "2027-07-12"
    assert [contact.role for contact in candidate.contacts] == ["GENERAL", "BOOKING"]
    assert [party.role for party in candidate.source_parties] == [
        "CREATOR",
        "PUBLISHER",
        "OWNER",
    ]
    assert not hasattr(candidate, "organizer")

    assert len(requests) == 2
    assert requests[0].headers[API_KEY_HEADER] == API_KEY
    assert API_KEY not in str(requests[0].url)
    assert requests[0].url.params["page_size"] == "100"
    assert requests[0].url.params["geo_distance"] == "43.708840,-1.051952,50000m"
    assert requests[0].url.params["lang"] == "fr"
    assert requests[0].url.params["fields"] == ",".join(EVENT_FIELDS)
    assert "start_date" not in requests[0].url.params
    assert requests[1].url.scheme == "https"
    assert requests[1].url.host == "api.datatourisme.fr"
    assert requests[1].url.path == EVENT_PATH
    assert "api_key" not in requests[1].url.params
    assert requests[1].headers[API_KEY_HEADER] == API_KEY
    assert fake_time.sleeps == pytest.approx([0.2])


def test_counts_missing_french_title_without_losing_completeness() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=page_response(
                [event(0, title=None)],
                total=1,
                page=1,
                total_pages=1,
                next_link=None,
            ),
            request=request,
        )

    pages: list[DatatourismePage] = []
    summary = client_for(handler).collect_events(43.7, -1.05, 30_000, pages.append)

    assert summary.received_count == 1
    assert summary.unique_uuid_count == 1
    assert summary.importable_count == 0
    assert summary.rejection_counts == {"missing_french_title": 1}
    assert pages[0].importable_candidates == ()


def test_accepts_an_empty_list_as_an_absent_short_description() -> None:
    item = event(0)
    descriptions = item["hasDescription"]
    assert isinstance(descriptions, list)
    description = descriptions[0]
    assert isinstance(description, dict)
    description["shortDescription"] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=page_response(
                [item],
                total=1,
                page=1,
                total_pages=1,
                next_link=None,
            ),
            request=request,
        )

    pages: list[DatatourismePage] = []
    summary = client_for(handler).collect_events(43.7, -1.05, 50_000, pages.append)

    assert summary.importable_count == 1
    assert pages[0].importable_candidates[0].descriptions[0].short is None
    assert pages[0].importable_candidates[0].descriptions[0].full is not None


@pytest.mark.parametrize(
    "next_link",
    (
        next_link().replace("https://", "http://", 1),
        next_link().replace("api.datatourisme.fr", "evil.example", 1),
        next_link().replace("api.datatourisme.fr", "api.datatourisme.fr:444", 1),
        next_link().replace(EVENT_PATH, "/v1/catalog", 1),
        next_link().replace("https://", "https://user:password@", 1),
    ),
)
def test_rejects_unsafe_next_links(next_link: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=page_response(
                [event(index) for index in range(100)],
                total=101,
                page=1,
                total_pages=2,
                next_link=next_link,
            ),
            request=request,
        )

    with pytest.raises(DatatourismeContractError, match="next link"):
        client_for(handler).collect_events(43.7, -1.05, 50_000, lambda _: None)


@pytest.mark.parametrize(
    "provider_next_link",
    (
        next_link(page_size="99"),
        next_link(lang="en"),
        next_link(geo_distance="43.7,-1.05,10m"),
        next_link(fields="uuid"),
        f"{next_link()}&start_date=2027-01-01",
    ),
)
def test_rejects_next_links_that_change_collection_parameters(
    provider_next_link: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=page_response(
                [event(index) for index in range(100)],
                total=101,
                page=1,
                total_pages=2,
                next_link=provider_next_link,
            ),
            request=request,
        )

    with pytest.raises(
        DatatourismeContractError,
        match=r"collection parameters|query parameters",
    ):
        client_for(handler).collect_events(43.70884, -1.051952, 50_000, lambda _: None)


def test_rejects_duplicates_incomplete_counts_and_link_loops() -> None:
    duplicate_response = page_response(
        [event(0), event(0)],
        total=2,
        page=1,
        total_pages=1,
        next_link=None,
    )

    def duplicate_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=duplicate_response, request=request)

    with pytest.raises(DatatourismeContractError, match="duplicate UUID"):
        client_for(duplicate_handler).collect_events(43.7, -1.05, 50_000, lambda _: None)

    incomplete_response = page_response(
        [event(0)],
        total=2,
        page=1,
        total_pages=1,
        next_link=None,
    )

    def incomplete_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=incomplete_response, request=request)

    with pytest.raises(DatatourismeContractError, match="count is incomplete"):
        client_for(incomplete_handler).collect_events(43.7, -1.05, 50_000, lambda _: None)

    repeated_link = next_link("same-cursor")
    loop_responses = [
        page_response(
            [event(index) for index in range(100)],
            total=201,
            page=1,
            total_pages=3,
            next_link=repeated_link,
        ),
        page_response(
            [event(100)],
            total=201,
            page=2,
            total_pages=3,
            next_link=repeated_link,
        ),
    ]

    def loop_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=loop_responses.pop(0), request=request)

    with pytest.raises(DatatourismeContractError, match="looped"):
        client_for(loop_handler).collect_events(
            43.70884,
            -1.051952,
            50_000,
            lambda _: None,
        )


def test_rejects_invalid_circle_and_response_schema_before_publishing_a_page() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"objects": [{}], "meta": {}}, request=request)

    adapter = client_for(handler)
    with pytest.raises(ValueError, match="latitude"):
        adapter.collect_events(float("nan"), -1.05, 50_000, lambda _: None)
    with pytest.raises(ValueError, match="radius"):
        adapter.collect_events(43.7, -1.05, 50_001, lambda _: None)
    assert calls == 0

    with pytest.raises(DatatourismeContractError, match="schema changed"):
        adapter.collect_events(43.7, -1.05, 50_000, lambda _: None)
    assert calls == 1


def test_retries_short_failures_but_not_authentication_redirects_or_long_waits() -> None:
    fake_time = FakeTime()
    calls = 0

    def retry_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, request=request)
        return httpx.Response(
            200,
            json=page_response([], total=0, page=1, total_pages=0, next_link=None),
            request=request,
        )

    summary = client_for(retry_handler, fake_time).collect_events(
        43.7,
        -1.05,
        50_000,
        lambda _: None,
    )
    assert summary.received_count == 0
    assert calls == 2
    assert fake_time.sleeps == [3.0]

    def authentication_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    with pytest.raises(DatatourismeAuthenticationError):
        client_for(authentication_handler).collect_events(43.7, -1.05, 50_000, lambda _: None)

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.example"}, request=request)

    with pytest.raises(DatatourismeRequestError):
        client_for(redirect_handler).collect_events(43.7, -1.05, 50_000, lambda _: None)

    long_wait_calls = 0

    def long_wait_handler(request: httpx.Request) -> httpx.Response:
        nonlocal long_wait_calls
        long_wait_calls += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "9" * 10_000},
            request=request,
        )

    with pytest.raises(DatatourismeTemporaryError) as captured:
        client_for(long_wait_handler).collect_events(43.7, -1.05, 50_000, lambda _: None)
    assert captured.value.retry_after_seconds == 86_400
    assert long_wait_calls == 1
