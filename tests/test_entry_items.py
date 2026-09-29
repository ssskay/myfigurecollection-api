"""Listing every item under one entry (origin/character/company).

Fixture captured live 2026-09-19 through the library's own transport:
``/?_tb=item&orEntries[]=237138&output=0&sort=insert&order=asc&page=2``.
"""

from mfc_api import MFCClient, urls
from mfc_api.models import EntryItems


class _CannedTransport:
    def __init__(self, html):
        self.html, self.seen = html, []

    def get(self, url, **_):
        self.seen.append(url)
        return self.html

    def close(self):
        pass


def test_entry_items_url():
    url = urls.entry_items(237138, page=3)
    assert "orEntries%5B%5D=237138" in url
    assert "output=0" in url and "page=3" in url
    assert "sort=insert" in url and "order=asc" in url
    assert "rootId" not in url
    assert "rootId=0" in urls.entry_items(237138, root_id=0)


def test_get_entry_items_parses_the_browse_page(entry_items_html):
    transport = _CannedTransport(entry_items_html)
    mfc = MFCClient(transport=transport)
    page = mfc.get_entry_items(237138, 2)

    assert isinstance(page, EntryItems)
    assert page.entry_id == 237138
    assert len(page.items) == 50
    assert page.pagination.current_page == 2
    assert page.pagination.total_pages == 145
    assert page.pagination.total_items == 7247
    assert page.pagination.has_next_page is True

    first = page.items[0]
    assert first.id == 1292691
    assert first.url == "https://myfigurecollection.net/item/1292691"
    assert first.thumbnail and "/upload/items/" in first.thumbnail
    assert len({i.id for i in page.items}) == 50
    assert "page=2" in transport.seen[0]
