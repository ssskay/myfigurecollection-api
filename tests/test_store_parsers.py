"""Partner listings, shops, and barcode lookup."""

import pytest

from mfc_api.exceptions import MFCParseError
from mfc_api.models import PartnerAvailability
from mfc_api.parsers import PartnerListingsParser, SearchParser, ShopParser, ShopsParser


# -- partner listings ---------------------------------------------------


@pytest.fixture(scope="module")
def listings(partner_listings_json):
    return PartnerListingsParser(partner_listings_json, item_id=287).parse()


def test_every_partner_is_listed(listings):
    assert len(listings.listings) == 32
    assert listings.item_id == 287


def test_the_barcode_is_recovered_from_the_affiliate_links(listings):
    assert listings.jan == "4543341130624"


def test_an_in_stock_listing_has_a_price(listings):
    amiami = next(l for l in listings.listings if l.shop_name == "AmiAmi")
    assert amiami.availability is PartnerAvailability.AVAILABLE
    assert amiami.availability_text == "Available"
    assert amiami.price == 11980.0
    assert amiami.currency == "JPY"
    assert amiami.partner_id == 62
    assert "itemId=287" in amiami.url


def test_an_out_of_stock_listing_has_no_price(listings):
    solaris = next(l for l in listings.listings if l.shop_name.startswith("Solaris"))
    assert solaris.availability is PartnerAvailability.NOT_AVAILABLE
    assert solaris.price is None


def test_available_helper(listings):
    assert [l.shop_name for l in listings.available] == ["AmiAmi"]


def test_without_a_barcode_nothing_is_really_known(partner_listings_no_barcode_json):
    # MFC cannot match stock without a JAN, so every shop says "maybe".
    parsed = PartnerListingsParser(partner_listings_no_barcode_json, item_id=2748700).parse()
    assert parsed.jan is None
    assert len(parsed.listings) == 32
    assert parsed.available == []
    assert {l.availability for l in parsed.listings} == {PartnerAvailability.MAYBE_AVAILABLE}
    assert all(l.price is None for l in parsed.listings)


def test_a_non_json_response_is_a_parse_error():
    with pytest.raises(MFCParseError, match="did not return JSON"):
        PartnerListingsParser("<html>nope</html>", item_id=287)


def test_json_without_window_markup_is_a_parse_error():
    with pytest.raises(MFCParseError, match="no WINDOW markup"):
        PartnerListingsParser('{"htmlValues": {}}', item_id=287)


# -- shops --------------------------------------------------------------


@pytest.fixture(scope="module")
def shop(shop_html):
    return ShopParser(shop_html, shop_id=12).parse()


def test_shop_identity(shop):
    assert shop.id == 12
    assert shop.name == "AmiAmi"
    assert shop.url == "https://myfigurecollection.net/shop/12"
    assert shop.is_partner is True


def test_shop_details(shop):
    assert shop.homepage == "https://www.amiami.com/eng/"
    assert shop.username == "amiami_com"
    assert shop.location == "Japan"
    assert shop.shipping == "Is shipping worldwide"
    assert shop.category == "Web Shop"
    assert shop.since == 1999


def test_shop_ratings(shop):
    assert shop.rating == 4.2
    assert shop.rating_count == 277
    assert shop.review_count == 277
    assert shop.likes == 195


def test_abbreviated_item_count_is_expanded(shop):
    # MFC prints "11.6k items"; a naive integer parse would read 11.
    assert shop.item_count == 11600


def test_shop_directory(shops_html):
    results = ShopsParser(shops_html).parse()
    assert len(results.shops) == 10
    assert results.pagination.total_items == 220
    assert results.pagination.total_pages == 22

    first = results.shops[0]
    assert first.id == 57
    assert first.name == "ABCTOY4ME"
    assert first.category == "Web Shop"
    assert first.location == "USA"
    assert first.score == 2.8
    assert first.review_count == 9
    assert first.status == "Out of business"


def test_location_chip_is_not_mistaken_for_the_category(shops_html):
    results = ShopsParser(shops_html).parse()
    # Both are a.meta.category; only the category carries shop-category-N.
    assert all(s.category != s.location for s in results.shops if s.category and s.location)


# -- barcode ------------------------------------------------------------


def test_a_barcode_hit_is_recognised_as_an_item_page(item_html):
    # MFC redirects a unique barcode to the item, so the parser has to notice
    # it is looking at an item page rather than a result list.
    assert SearchParser(item_html, query="4543341130624").looks_like_item_page() == 287


def test_a_barcode_miss_is_an_empty_result_page(barcode_no_match_html):
    parser = SearchParser(barcode_no_match_html, query="0000000000000")
    assert parser.looks_like_item_page() is None
    assert parser.parse().items == []


def test_a_result_page_is_not_mistaken_for_an_item(search_html):
    assert SearchParser(search_html, query="nendoroid miku").looks_like_item_page() is None
