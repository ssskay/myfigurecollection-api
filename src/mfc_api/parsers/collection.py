"""Parser for a user's collection tab (``users.v4.php?tab=collection``)."""

from __future__ import annotations

from ..models import Collection, CollectionStats, CollectionStatus
from .base import Parser

_STATUS_ATTR = {
    CollectionStatus.WISHED: "wished",
    CollectionStatus.ORDERED: "ordered",
    CollectionStatus.OWNED: "owned",
    CollectionStatus.FAVORITES: "favorites",
}


class CollectionParser(Parser):
    def __init__(self, html: str, *, username: str, status: CollectionStatus, url=None) -> None:
        super().__init__(html, url=url)
        self.username = username
        self.status = status

    def parse(self) -> Collection:
        return Collection(
            username=self.username,
            status=self.status,
            items=self.item_summaries(),
            stats=self._stats(),
            pagination=self.pagination(),
        )

    def _stats(self) -> CollectionStats:
        """Counts come from the Owned/Ordered/Wished/Favorites tab labels.

        tenji read these from ``div.results-toggles``, which today holds the
        Figures/Goods/Media root filter instead. The tab links are scoped to
        ``div.tab`` so the language switcher — whose hrefs also carry
        ``status=`` — cannot leak in.
        """
        stats = CollectionStats()
        for tab in self.soup.select("div.tab > a[href]"):
            raw_status = self.query_value(tab.get("href"), "status")
            if raw_status is None:
                continue
            try:
                status = CollectionStatus(int(raw_status))
            except ValueError:
                continue
            attr = _STATUS_ATTR[status]
            if getattr(stats, attr) is None:
                # A tab with no number means that bucket is empty.
                setattr(stats, attr, self.number(tab.get_text(" ", strip=True)) or 0)
        return stats
