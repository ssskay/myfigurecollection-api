"""Parser for a user's lists tab (``users.v4.php?tab=lists``)."""

from __future__ import annotations

from ..models import UserLists, UserListSummary
from .base import Parser


class UserListsParser(Parser):
    def __init__(self, html: str, *, username: str, url=None) -> None:
        super().__init__(html, url=url)
        self.username = username

    def parse(self) -> UserLists:
        lists: list[UserListSummary] = []
        for dgst in self.soup.select("div.dgst.list-dgst"):
            anchor = dgst.select_one("div.dgst-anchor a[href]")
            if anchor is None:
                continue
            list_id = self.trailing_id(anchor.get("href"))
            if list_id is None:
                continue

            updated = dgst.select_one("div.dgst-meta span[title]")
            lists.append(
                UserListSummary(
                    id=list_id,
                    name=anchor.get("title") or anchor.get_text(" ", strip=True),
                    url=self.absolute(anchor.get("href")),
                    icon=self.attr("a.dgst-icon img", "src", dgst),
                    item_count=self.number(self.text("div.dgst-meta span.meta", dgst)),
                    visibility=self.text("span.meta.category", dgst),
                    updated=self.timestamp(updated),
                    updated_relative=updated.get_text(" ", strip=True) if updated else None,
                )
            )

        return UserLists(
            username=self.username, lists=lists, pagination=self.pagination()
        )
