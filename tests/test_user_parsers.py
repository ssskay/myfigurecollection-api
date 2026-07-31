"""Collection, profile and list parsing."""

import datetime

import pytest

from mfc_api.models import CollectionStatus, ItemCategory
from mfc_api.parsers import CollectionParser, ItemListParser, ProfileParser, UserListsParser


@pytest.fixture(scope="module")
def collection(collection_html):
    return CollectionParser(
        collection_html, username="Climbatize", status=CollectionStatus.OWNED
    ).parse()


@pytest.fixture(scope="module")
def profile(profile_html):
    return ProfileParser(profile_html).parse()


# -- collection ---------------------------------------------------------


def test_collection_items(collection):
    assert len(collection.items) == 50
    first = collection.items[0]
    assert first.id == 38
    assert first.name.startswith("Fate/Hollow Ataraxia")
    assert first.category is ItemCategory.PREPAINTED
    assert first.release_date == "03/2006"
    assert first.barcode == "4582191962306"


def test_collection_stats_come_from_the_status_tabs(collection):
    # tenji read these from div.results-toggles, which now holds the
    # Figures/Goods/Media filter instead.
    assert collection.stats.owned == 167
    assert collection.stats.wished == 28
    # Empty buckets render a tab with no number.
    assert collection.stats.ordered == 0
    assert collection.stats.favorites == 0


def test_collection_pagination(collection):
    assert collection.pagination.current_page == 1
    assert collection.pagination.total_pages == 4
    assert collection.pagination.total_items == 167
    assert collection.pagination.has_next_page is True


def test_language_switcher_does_not_leak_into_stats(collection_html):
    # The language menu links carry status= too; only div.tab links count.
    parsed = CollectionParser(
        collection_html, username="Climbatize", status=CollectionStatus.OWNED
    ).parse()
    assert parsed.stats.owned == 167


# -- profile ------------------------------------------------------------


def test_profile_identity(profile):
    assert profile.username == "Climbatize"
    assert profile.url == "https://myfigurecollection.net/profile/Climbatize"
    assert profile.avatar.endswith(".png")
    assert profile.banner.startswith("https://static.myfigurecollection.net/")


def test_profile_timestamps(profile):
    assert profile.joined == datetime.datetime(
        2009, 1, 19, 19, 38, 30, tzinfo=datetime.timezone.utc
    )
    assert profile.joined_relative == "17 years ago"
    assert profile.last_login.year == 2026


def test_profile_stats(profile):
    assert profile.hits == 123260
    assert profile.rank == 257


def test_profile_about_fields(profile):
    assert profile.about["Level"] == "22"
    assert profile.about["Location"] == "Kawasaki"


def test_profile_collection_summary(profile):
    figures = next(s for s in profile.collection if s.group == "Figures")
    assert figures.total == 145
    assert figures.owned == 121
    assert figures.wished == 24
    assert figures.favorites == 14
    assert {s.group for s in profile.collection} == {"Figures", "Goods", "Media"}


# -- lists --------------------------------------------------------------


def test_user_lists(user_lists_html):
    lists = UserListsParser(user_lists_html, username="Tsunami3k").parse()
    assert lists.username == "Tsunami3k"
    assert len(lists.lists) == 4
    first = lists.lists[0]
    assert first.id == 301714
    assert first.name == "Canceled Wishlist"
    assert first.item_count == 6
    assert first.visibility == "Public"
    assert first.updated.year == 2024
    assert lists.pagination.has_next_page is False


def test_item_list(item_list_html):
    parsed = ItemListParser(item_list_html, list_id=2509).parse()
    assert parsed.name == "Displayed"
    assert parsed.owner == "Tsunami3k"
    assert parsed.item_count == 326
    assert parsed.comment_count == 0
    # A list page shows one page of its items as an icon grid.
    assert len(parsed.items) == 87
    assert parsed.items[0].id == 40
    assert parsed.pagination.total_pages == 4
