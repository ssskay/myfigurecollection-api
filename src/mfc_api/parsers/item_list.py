"""Parser for ``/list/{id}`` pages.

tenji fetched these through ``itemlists.v4.php``, which now returns 404. The
modern page renders its items as an icon grid rather than as digest rows, so
this parser reads ``span.item-icon`` anchors.
"""

from __future__ import annotations

from ..models import ItemList
from .base import Parser


class ItemListParser(Parser):
    def __init__(self, html: str, *, list_id: int, url=None) -> None:
        super().__init__(html, url=url)
        self.list_id = list_id

    def parse(self) -> ItemList:
        name = self.text("h1.title")
        if name is None:
            self.require(None, "the list headline")

        stats = self.soup.select_one("div.object-stats")
        comment_count = None
        if stats is not None:
            comment_link = stats.select_one("a[href*='/comments/']")
            comment_count = self.number(comment_link.get_text(" ", strip=True)) if comment_link else None

        description = self.text("div.bbcode")

        return ItemList(
            id=self.list_id,
            name=name,
            url=f"https://myfigurecollection.net/list/{self.list_id}",
            owner=self.text("a.user-anchor"),
            icon=self.attr("div.content-icon img", "src"),
            description=description or None,
            item_count=self.number(self.text("div.results-count-value")),
            comment_count=comment_count,
            tags=[tag.get_text(" ", strip=True) for tag in self.soup.select("div.object-tag a")],
            items=self.icon_item_summaries(),
            pagination=self.pagination(),
        )
