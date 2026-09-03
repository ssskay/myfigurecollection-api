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


@pytest.fixture(scope="session")
def spn2_submit_job_json() -> str:
    """`POST /save/` accepted the capture and handed back a job to poll."""
    return load("spn2_submit_job.json")


@pytest.fixture(scope="session")
def spn2_submit_dedup_json() -> str:
    """`POST /save/` declined: a capture already exists inside the window.

    Note there is no `job_id` and no `status` field — the whole signal is the
    wording of `message`, which is why the parser matches on it.
    """
    return load("spn2_submit_dedup.json")


@pytest.fixture(scope="session")
def spn2_submit_error_json() -> str:
    """`POST /save/` refused outright — a candidate-dead target."""
    return load("spn2_submit_error.json")


@pytest.fixture(scope="session")
def spn2_status_pending_json() -> str:
    return load("spn2_status_pending.json")


@pytest.fixture(scope="session")
def spn2_status_success_json() -> str:
    """A finished capture. `timestamp` is what builds the citable URL."""
    return load("spn2_status_success.json")


@pytest.fixture(scope="session")
def spn2_status_error_json() -> str:
    """A capture that failed on the Archive's side, transiently."""
    return load("spn2_status_error.json")


@pytest.fixture(scope="session")
def wayback_available_json() -> str:
    """`archive.org/wayback/available` — how a dedup answer gets a URL."""
    return load("wayback_available.json")


def pytest_collection_modifyitems(config, items):
    if config.getoption("-m"):
        return
    skip_live = pytest.mark.skip(reason="live test; run with -m live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
