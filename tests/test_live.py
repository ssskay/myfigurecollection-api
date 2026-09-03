"""Live tests — these hit myfigurecollection.net.

Deselected by default. Run them when you suspect MFC changed its markup, or
when Cloudflare starts blocking again:

    python3 -m pytest -m live

They are deliberately few and rate-limited; do not add a loop here.
"""

import tempfile
from pathlib import Path

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


# -- the archive hook -----------------------------------------------------


def test_save_page_now_still_accepts_an_mfc_item_page():
    """One capture, of one page, on purpose.

    The canary for the whole snapshot layer: SPN2's contract is undocumented in
    the same way MFC's markup is, and what this watches for is the Archive
    changing its submit/poll shape or refusing our credentials.

    `force=True` bypasses the weekly ledger — otherwise running the canary twice
    in a week would pass without testing anything. It stays a single URL and a
    single capture; do not loop this.

    A `pending` result is a pass: the Archive queues captures, and "submitted
    and running" is the contract working. So is a `transient` failure, which
    means the Archive is busy and says nothing about our code.
    """
    from mfc_api.archive import Archiver, ArchiveLedger, read_credentials

    access, _secret = read_credentials()
    if not access:
        pytest.skip(
            "no Internet Archive S3 keys — set IA_ACCESS_KEY / IA_SECRET_KEY, or "
            "store them in the macOS Keychain as ia-s3-access / ia-s3-secret. "
            "Free keys: https://archive.org/account/s3.php"
        )

    url = "https://myfigurecollection.net/item/287"
    # A throwaway ledger, so the canary neither reads nor pollutes the real one.
    with Archiver(ledger=ArchiveLedger(Path(tempfile.mkdtemp()) / "ledger.json"),
                  timeout=90) as archiver:
        result = archiver.snapshot(url, force=True)

    if result.status == "failed" and result.error_kind == "transient":
        pytest.skip(f"the Internet Archive is throttling right now: {result.reason}")

    assert result.status in ("success", "already", "pending"), (
        f"Save Page Now refused an MFC item page: {result.status} — {result.reason}. "
        "Either the SPN2 request/response shape moved (see mfc_api.archive) or "
        "the IA credentials are no longer good."
    )
    if result.status in ("success", "already"):
        assert result.wayback_url, f"{result.status} but no archive URL came back"
        # The availability API answers over http, SPN2 over https. Same capture.
        assert result.wayback_url.split("://", 1)[-1].startswith("web.archive.org/web/"), (
            f"captured, but the archive URL is not on web.archive.org: {result.wayback_url}"
        )
