"""URL construction. These strings are the difference between 200 and 404."""

from mfc_api import urls
from mfc_api.models import CollectionStatus


def test_item_and_profile():
    assert urls.item(287) == "https://myfigurecollection.net/item/287"
    assert urls.profile("Climbatize") == "https://myfigurecollection.net/profile/Climbatize"


def test_collection_uses_the_v4_endpoint_with_output_0():
    url = urls.collection("Climbatize", status=int(CollectionStatus.OWNED), page=2)
    assert url.startswith("https://myfigurecollection.net/users.v4.php?")
    assert "tab=collection" in url
    assert "status=2" in url
    assert "page=2" in url
    # output=0 is what makes MFC render 50 parseable digest rows.
    assert "output=0" in url


def test_list_uses_the_modern_path():
    # itemlists.v4.php, which tenji used, now 404s.
    assert "itemlists.v4.php" not in urls.item_list(2509)
    assert urls.item_list(2509).startswith("https://myfigurecollection.net/list/2509/")
    assert "page=3" in urls.item_list(2509, page=3)


def test_search_uses_title_not_keywords():
    # `keywords` triggers the Quick search grid: no count, no pagination.
    url = urls.search_items("nendoroid miku", page=2)
    assert "title=nendoroid+miku" in url
    assert "keywords" not in url
    assert "output=0" in url
    assert "page=2" in url


def test_search_omits_empty_filters():
    assert "categoryId" not in urls.search_items("miku")
    assert "categoryId=1" in urls.search_items("miku", category_id=1)


def test_barcode_search_uses_the_barcode_param():
    url = urls.search_by_barcode("4543341130624")
    assert "barcode=4543341130624" in url
    assert "title=" not in url


def test_partner_listings_is_a_form_post():
    url, form = urls.partner_listings(287)
    assert url == "https://myfigurecollection.net/item/287"
    assert form == {"commit": "loadWindow", "window": "buyItem"}


def test_shop_urls():
    assert urls.shop(12) == "https://myfigurecollection.net/shop/12"
    assert "_tb=shop" in urls.search_shops()
    assert "keywords=Japan" in urls.search_shops("Japan")
    assert "isPartner=1" in urls.search_shops(partners_only=True)
    # The flag is omitted entirely rather than sent as 0.
    assert "isPartner" not in urls.search_shops(partners_only=False)


def test_club():
    assert urls.club(349) == "https://myfigurecollection.net/club/349"
    assert urls.club_members(349, page=2).startswith(
        "https://myfigurecollection.net/club/349/members/?"
    )
