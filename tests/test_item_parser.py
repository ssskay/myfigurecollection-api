"""Item page parsing, against a saved copy of /item/287."""

import pytest

from mfc_api.exceptions import MFCNotFoundError
from mfc_api.models import ItemCategory
from mfc_api.parsers import ItemParser


@pytest.fixture(scope="module")
def item(item_html):
    return ItemParser(item_html, url="https://myfigurecollection.net/item/287").parse()


def test_identity(item):
    assert item.id == 287
    assert item.name == "Aria - Alice Carroll - Maa - 1/6 (Toy's Works)"
    assert item.url == "https://myfigurecollection.net/item/287"


def test_category(item):
    assert item.category is ItemCategory.PREPAINTED
    assert item.category_name == "Prepainted"


def test_pictures(item):
    assert item.picture.endswith("287-5585f.jpg")
    assert item.thumbnail.endswith("287-5585f.jpg")
    # The full picture and the thumbnail are different sizes of the same upload.
    assert item.picture != item.thumbnail


def test_origins_and_characters(item):
    assert [o.name for o in item.origins] == ["Aria"]
    assert item.origins[0].id == 213
    assert item.origins[0].name_alt == "アリア"

    assert [c.name for c in item.characters] == ["Alice Carroll", "Maa"]
    assert [c.id for c in item.characters] == [2767, 2779]


def test_roles_are_attached_to_the_right_entry(item):
    assert item.companies[0].name == "Toy's Works"
    assert item.companies[0].role == "Manufacturer"
    assert item.artists[0].role == "Sculptor"


def test_release(item):
    assert len(item.releases) == 1
    release = item.releases[0]
    assert release.date == "02/26/2007"
    assert release.edition == "Standard (Japan)"
    assert release.price == 6980.0
    assert release.currency == "JPY"
    assert release.barcode == "4543341130624"


def test_dimensions_and_materials(item):
    assert item.scale == "1/6"
    assert item.height_mm == 280
    assert item.materials == ["ABS", "ATBC-PVC"]


def test_counts_and_rating(item):
    assert item.owned_by == 79
    assert item.ordered_by == 1
    assert item.wished_by == 118
    assert item.listed_in == 32
    assert item.rating == 8.81
    assert item.rating_count == 16


def test_contributors(item):
    assert item.added_by == "Merlin"
    assert item.last_edited_by == "Kaneel"


def test_missing_item_raises_not_found(item_404_html):
    # MFC serves a styled 404 body, so the parser has to notice it.
    with pytest.raises(MFCNotFoundError):
        ItemParser(item_404_html, url="https://myfigurecollection.net/item/999999999")


def test_full_size_picture_and_gallery(item_html):
    from mfc_api.parsers import ItemParser

    item = ItemParser(item_html).parse()
    assert item.picture.endswith("/upload/items/1/287-5585f.jpg")
    assert item.picture_large == "https://static.myfigurecollection.net/upload/items/2/287-5585f.jpg"
    assert len(item.gallery) == 6
    assert all("/upload/pictures/" in url for url in item.gallery)
