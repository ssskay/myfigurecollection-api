"""Fixtures are saved MFC pages, captured 2026-07-30.

Nothing in the default test run touches the network. Tests marked `live` do,
and are deselected unless you ask for them:

    python3 -m pytest -m live
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def item_html() -> str:
    """Item 287 — Aria, Alice Carroll & Maa, 1/6, Toy's Works."""
    return load("item_287.html")


@pytest.fixture(scope="session")
def item_404_html() -> str:
    return load("item_404.html")


@pytest.fixture(scope="session")
def collection_html() -> str:
    """Climbatize's owned collection, page 1 of 4."""
    return load("collection_owned_page1.html")


@pytest.fixture(scope="session")
def profile_html() -> str:
    return load("profile.html")


@pytest.fixture(scope="session")
def user_lists_html() -> str:
    """Tsunami3k's lists — 4 of them, single page."""
    return load("user_lists.html")


@pytest.fixture(scope="session")
def item_list_html() -> str:
    """List 2509, "Displayed", 326 items."""
    return load("item_list.html")


@pytest.fixture(scope="session")
def club_html() -> str:
    """Club 349 — MFC's own (dead) API club."""
    return load("club_349.html")


@pytest.fixture(scope="session")
def search_html() -> str:
    """Search for "nendoroid miku", page 1 of 12."""
    return load("search_items.html")


@pytest.fixture(scope="session")
def partner_listings_json() -> str:
    """The Buy window for item 287, which has a JAN — so it has real prices."""
    return load("partner_listings_287.json")


@pytest.fixture(scope="session")
def partner_listings_no_barcode_json() -> str:
    """The Buy window for item 2748700, which has no barcode registered."""
    return load("partner_listings_no_barcode.json")


@pytest.fixture(scope="session")
def shop_html() -> str:
    """Shop 12 — AmiAmi, an MFC partner."""
    return load("shop_12.html")


@pytest.fixture(scope="session")
def shops_html() -> str:
    """The shop directory, page 1 of 22."""
    return load("shops_page1.html")


@pytest.fixture(scope="session")
def barcode_no_match_html() -> str:
    """A barcode search that matched nothing — MFC stays on the search page."""
    return load("barcode_no_match.html")


def pytest_collection_modifyitems(config, items):
    if config.getoption("-m"):
        return
    skip_live = pytest.mark.skip(reason="live test; run with -m live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
