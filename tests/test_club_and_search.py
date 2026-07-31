"""Club and search parsing. Clubs are the endpoint tenji never had."""

import pytest

from mfc_api.models import ItemCategory
from mfc_api.parsers import ClubParser, SearchParser


@pytest.fixture(scope="module")
def club(club_html):
    return ClubParser(club_html, club_id=349).parse()


def test_club_identity(club):
    assert club.id == 349
    assert club.name == "MFC API Club"
    assert club.subtitle.startswith("Find all help and resources")
    assert club.category == "Off-topic"


def test_club_counts(club):
    assert club.member_count == 159
    assert club.comment_count == 31
    assert club.updated.year == 2015


def test_club_description_is_not_a_comment(club):
    assert club.description.startswith("Join this club")


def test_club_threads(club):
    assert len(club.threads) == 7
    thread = club.threads[0]
    assert thread.id == 17768
    assert thread.title == "API V4?"
    assert thread.status == "Open"
    assert thread.started_by == "Syntack"
    assert thread.last_poster == "LeonBlade"
    assert thread.replies == 5
    # The last post is more recent than the thread's creation.
    assert thread.last_post > thread.started


def test_club_comments(club):
    assert len(club.comments) == 10
    comment = club.comments[0]
    assert comment.username == "mindsignals"
    assert comment.body
    assert comment.posted.year == 2026


def test_club_staff_and_members(club):
    assert [s.username for s in club.staff] == ["Climbatize"]
    assert club.staff[0].role == "Admin"
    # The club page only shows a handful; get_club_members has the rest.
    assert len(club.members) == 5


def test_search(search_html):
    results = SearchParser(search_html, query="nendoroid miku").parse()
    assert results.query == "nendoroid miku"
    assert len(results.items) == 50
    assert results.pagination.total_items == 597
    assert results.pagination.total_pages == 12
    assert results.pagination.has_next_page is True

    first = results.items[0]
    assert first.id == 3657515
    assert first.category is ItemCategory.ACTION_DOLLS
    assert "Hatsune Miku" in first.name
