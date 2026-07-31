"""Transport behaviour (rate limiting, cache, Cloudflare detection) and the client.

None of this touches the network — the transport is driven with a fake session.
"""

import time

import pytest

from mfc_api.cache import DiskCache
from mfc_api.client import MFCClient
from mfc_api.exceptions import MFCBlockedError, MFCNotFoundError, MFCTransportError
from mfc_api.models import CollectionStatus
from mfc_api.transport import RateLimiter, Transport

CHALLENGE = "<html><head><title>Just a moment...</title></head><body></body></html>"


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class FakeSession:
    """Stands in for curl_cffi's Session. Serves queued responses in order."""

    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.requested: list[str] = []
        self.posted: list[tuple[str, dict]] = []

    def _next(self) -> FakeResponse:
        return self.responses.pop(0) if self.responses else FakeResponse(200, "<html></html>")

    def get(self, url, timeout=None):
        self.requested.append(url)
        return self._next()

    def post(self, url, data=None, timeout=None):
        self.requested.append(url)
        self.posted.append((url, data or {}))
        return self._next()

    def close(self):
        pass


def make_transport(tmp_path, *responses, **kwargs) -> Transport:
    transport = Transport(
        rate_limit=0,
        cache=DiskCache(tmp_path / "cache", ttl=kwargs.pop("ttl", 3600)),
        **kwargs,
    )
    transport._session = FakeSession(*responses)
    return transport


# -- cache --------------------------------------------------------------


def test_cache_round_trip(tmp_path):
    cache = DiskCache(tmp_path, ttl=60)
    cache.set("https://example.test/a", "<html>a</html>")
    assert cache.get("https://example.test/a") == "<html>a</html>"
    assert cache.get("https://example.test/b") is None


def test_cache_respects_ttl(tmp_path):
    cache = DiskCache(tmp_path, ttl=0.01)
    cache.set("k", "v")
    time.sleep(0.05)
    assert cache.get("k") is None


def test_ttl_zero_disables_the_cache(tmp_path):
    cache = DiskCache(tmp_path, ttl=0)
    cache.set("k", "v")
    assert cache.get("k") is None
    assert cache.enabled is False


def test_cache_clear(tmp_path):
    cache = DiskCache(tmp_path, ttl=60)
    cache.set("a", "1")
    cache.set("b", "2")
    assert cache.clear() == 2
    assert cache.get("a") is None


# -- rate limiting ------------------------------------------------------


def test_rate_limiter_spaces_calls_out():
    limiter = RateLimiter(0.05)
    start = time.monotonic()
    limiter.wait()
    limiter.wait()
    assert time.monotonic() - start >= 0.05


def test_rate_limiter_of_zero_does_not_sleep():
    limiter = RateLimiter(0)
    start = time.monotonic()
    for _ in range(5):
        limiter.wait()
    assert time.monotonic() - start < 0.05


# -- transport ----------------------------------------------------------


def test_second_get_is_served_from_cache(tmp_path):
    transport = make_transport(tmp_path, FakeResponse(200, "<html>ok</html>"))
    assert transport.get("https://example.test/x") == "<html>ok</html>"
    assert transport.get("https://example.test/x") == "<html>ok</html>"
    assert len(transport._session.requested) == 1


def test_use_cache_false_always_refetches(tmp_path):
    transport = make_transport(
        tmp_path, FakeResponse(200, "<html>1</html>"), FakeResponse(200, "<html>2</html>")
    )
    assert transport.get("https://example.test/x", use_cache=False) == "<html>1</html>"
    assert transport.get("https://example.test/x", use_cache=False) == "<html>2</html>"


def test_cloudflare_challenge_is_recognised(tmp_path):
    transport = make_transport(tmp_path, FakeResponse(403, CHALLENGE))
    with pytest.raises(MFCBlockedError, match="Cloudflare"):
        transport.get("https://example.test/x")


def test_challenge_with_a_200_status_still_raises(tmp_path):
    # Cloudflare sometimes returns the interstitial with a 200.
    transport = make_transport(tmp_path, FakeResponse(200, CHALLENGE))
    with pytest.raises(MFCBlockedError):
        transport.get("https://example.test/x")


def test_404_raises_not_found(tmp_path):
    transport = make_transport(tmp_path, FakeResponse(404, "<html>gone</html>"))
    with pytest.raises(MFCNotFoundError):
        transport.get("https://example.test/x")


def test_server_errors_are_retried_then_reported(tmp_path):
    transport = make_transport(
        tmp_path,
        FakeResponse(500, ""),
        FakeResponse(500, ""),
        FakeResponse(500, ""),
        max_retries=2,
    )
    with pytest.raises(MFCTransportError):
        transport.get("https://example.test/x")
    assert len(transport._session.requested) == 3


def test_a_retry_can_succeed(tmp_path):
    transport = make_transport(
        tmp_path, FakeResponse(503, ""), FakeResponse(200, "<html>ok</html>")
    )
    assert transport.get("https://example.test/x") == "<html>ok</html>"


def test_failed_requests_are_not_cached(tmp_path):
    transport = make_transport(tmp_path, FakeResponse(404, ""))
    with pytest.raises(MFCNotFoundError):
        transport.get("https://example.test/x")
    assert transport.cache.get("https://example.test/x") is None


def test_post_sends_the_form_and_caches_the_reply(tmp_path):
    transport = make_transport(tmp_path, FakeResponse(200, '{"ok": 1}'))
    form = {"commit": "loadWindow", "window": "buyItem"}
    assert transport.post("https://example.test/item/287", form) == '{"ok": 1}'
    assert transport.post("https://example.test/item/287", form) == '{"ok": 1}'
    assert len(transport._session.requested) == 1
    assert transport._session.posted[0][1] == form


def test_post_cache_key_includes_the_form_fields(tmp_path):
    # Same URL, different form -> different response, so it must not collide.
    transport = make_transport(
        tmp_path, FakeResponse(200, '{"a": 1}'), FakeResponse(200, '{"b": 2}')
    )
    url = "https://example.test/item/287"
    assert transport.post(url, {"window": "buyItem"}) == '{"a": 1}'
    assert transport.post(url, {"window": "collectedBy"}) == '{"b": 2}'


def test_post_and_get_to_the_same_url_do_not_share_a_cache_entry(tmp_path):
    transport = make_transport(
        tmp_path, FakeResponse(200, "<html>page</html>"), FakeResponse(200, '{"json": 1}')
    )
    url = "https://example.test/item/287"
    assert transport.get(url) == "<html>page</html>"
    assert transport.post(url, {"window": "buyItem"}) == '{"json": 1}'


# -- client -------------------------------------------------------------


def test_client_requests_the_right_url(tmp_path, item_html):
    transport = make_transport(tmp_path, FakeResponse(200, item_html))
    with MFCClient(transport=transport) as mfc:
        item = mfc.get_item(287)
    assert item.id == 287
    assert transport._session.requested == ["https://myfigurecollection.net/item/287"]


def test_client_accepts_a_status_int(tmp_path, collection_html):
    transport = make_transport(tmp_path, FakeResponse(200, collection_html))
    with MFCClient(transport=transport) as mfc:
        collection = mfc.get_collection("Climbatize", status=2)
    assert collection.status is CollectionStatus.OWNED


def test_client_barcode_hit_returns_the_item(tmp_path, item_html):
    # MFC redirects the barcode search to the item page.
    transport = make_transport(tmp_path, FakeResponse(200, item_html))
    with MFCClient(transport=transport) as mfc:
        match = mfc.search_by_barcode("4543341130624")
    assert match.matched is True
    assert match.item.id == 287
    assert match.items == []
    assert "barcode=4543341130624" in transport._session.requested[0]


def test_client_barcode_miss_returns_no_items(tmp_path, barcode_no_match_html):
    transport = make_transport(tmp_path, FakeResponse(200, barcode_no_match_html))
    with MFCClient(transport=transport) as mfc:
        match = mfc.search_by_barcode("0000000000000")
    assert match.matched is False
    assert match.item is None
    assert match.items == []


def test_client_barcode_strips_whitespace(tmp_path, item_html):
    transport = make_transport(tmp_path, FakeResponse(200, item_html))
    with MFCClient(transport=transport) as mfc:
        assert mfc.search_by_barcode("  4543341130624 ").barcode == "4543341130624"


def test_client_partner_listings_posts_the_buy_window(tmp_path, partner_listings_json):
    transport = make_transport(tmp_path, FakeResponse(200, partner_listings_json))
    with MFCClient(transport=transport) as mfc:
        listings = mfc.get_partner_listings(287)
    assert len(listings.listings) == 32
    url, form = transport._session.posted[0]
    assert url == "https://myfigurecollection.net/item/287"
    assert form == {"commit": "loadWindow", "window": "buyItem"}


def test_client_shop_search_passes_filters(tmp_path, shops_html):
    transport = make_transport(tmp_path, FakeResponse(200, shops_html))
    with MFCClient(transport=transport) as mfc:
        mfc.search_shops("Japan", partners_only=True, average_score=4)
    requested = transport._session.requested[0]
    assert "keywords=Japan" in requested
    assert "isPartner=1" in requested
    assert "averageScore=4" in requested


def test_iter_collection_stops_at_max_pages(tmp_path, collection_html):
    # The fixture reports 4 pages; max_pages caps how many we actually fetch.
    transport = make_transport(tmp_path, *[FakeResponse(200, collection_html)] * 4)
    with MFCClient(transport=transport) as mfc:
        pages = list(mfc.iter_collection("Climbatize", max_pages=2))
    assert len(pages) == 2
    assert [
        transport.cache.get(url) is not None for url in transport._session.requested
    ] == [True, True]
