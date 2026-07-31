"""Live tests — these hit myfigurecollection.net.

Deselected by default. Run them when you suspect MFC changed its markup, or
when Cloudflare starts blocking again:

    python3 -m pytest -m live

They are deliberately few and rate-limited; do not add a loop here.
"""

import pytest

from mfc_api import MFCClient
from mfc_api.exceptions import MFCNotFoundError

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client():
    # No cache, so these actually test the live site.
    with MFCClient(cache_ttl=0) as mfc:
        yield mfc


def test_cloudflare_still_lets_us_through(client):
    item = client.get_item(287)
    assert item.name == "Aria - Alice Carroll - Maa - 1/6 (Toy's Works)"
    assert item.releases and item.releases[0].currency == "JPY"


def test_collection_markup_is_still_what_we_expect(client):
    collection = client.get_collection("Climbatize")
    assert collection.items, "no items parsed — MFC's collection markup changed"
    assert collection.stats.owned


def test_club_markup_is_still_what_we_expect(client):
    club = client.get_club(349)
    assert club.name == "MFC API Club"
    assert club.threads, "no threads parsed — MFC's club markup changed"


def test_search_still_paginates(client):
    results = client.search_items("nendoroid miku")
    assert len(results.items) > 1
    assert results.pagination.total_items


def test_missing_item(client):
    with pytest.raises(MFCNotFoundError):
        client.get_item(999999999)


def test_the_buy_window_still_returns_json_with_prices(client):
    listings = client.get_partner_listings(287)
    assert len(listings.listings) > 10, "the Buy window returned almost nothing"
    assert listings.jan == "4543341130624"
    priced = [l for l in listings.listings if l.price is not None]
    assert priced, "no partner reported a price — MFC may have dropped the partner program"
    assert all(l.currency for l in priced)


def test_barcode_lookup_still_redirects_to_the_item(client):
    match = client.search_by_barcode("4543341130624")
    assert match.matched is True
    assert match.item.id == 287


def test_an_unknown_barcode_matches_nothing(client):
    match = client.search_by_barcode("0000000000000")
    assert match.matched is False
    assert match.item is None


def test_shop_page_markup_is_still_what_we_expect(client):
    shop = client.get_shop(12)
    assert shop.name == "AmiAmi"
    assert shop.homepage, "no homepage parsed — the shop data fields changed"
    assert shop.rating


def test_shop_directory_still_paginates(client):
    results = client.search_shops(partners_only=True)
    assert results.shops, "no shops parsed — the directory markup changed"
    assert results.pagination.total_items
