"""Parser for ``/profile/{username}`` pages."""

from __future__ import annotations

from ..models import CollectionSummary, Profile
from .base import Parser

_COLLECTION_GROUPS = ("Figures", "Goods", "Media")
_ACTION_ATTR = {
    "Owned": "owned",
    "Ordered": "ordered",
    "Wished": "wished",
    "Favorites": "favorites",
}


class ProfileParser(Parser):
    def parse(self) -> Profile:
        username = self.text("h1.title")
        if username is None:
            self.require(None, "the profile headline")

        stats = self.soup.select_one("div.object-stats")
        times = stats.select("span[title]") if stats else []
        last_login = times[0] if len(times) > 0 else None
        joined = times[1] if len(times) > 1 else None

        hits = None
        rank = None
        if stats is not None:
            hit_node = next(
                (s for s in stats.select("span[title]") if "hits" in (s.get("title") or "")),
                None,
            )
            hits = self.number(hit_node.get("title")) if hit_node else None
            rank = self.number(self.text("span.light", stats))

        return Profile(
            username=username,
            url=f"https://myfigurecollection.net/profile/{username}",
            subtitle=self.text("div.subtitle") or None,
            avatar=self.attr("img.the-avatar", "src"),
            banner=self.background_image(self.attr("div.the-banner", "style")),
            last_login=self.timestamp(last_login),
            last_login_relative=last_login.get_text(" ", strip=True) if last_login else None,
            joined=self.timestamp(joined),
            joined_relative=joined.get_text(" ", strip=True) if joined else None,
            hits=hits,
            rank=rank,
            about={
                label: value.get_text(" ", strip=True)
                for label, value in self.data_fields().items()
            },
            collection=self._collection_summary(),
        )

    def _collection_summary(self) -> list[CollectionSummary]:
        """The Figures / Goods / Media section headers carry per-status counts."""
        summaries: list[CollectionSummary] = []
        for section in self.soup.select("section"):
            heading = section.select_one("h2")
            if heading is None:
                continue
            group = next(
                (g for g in _COLLECTION_GROUPS if heading.get_text(" ", strip=True).startswith(g)),
                None,
            )
            if group is None:
                continue

            summary = CollectionSummary(
                group=group,
                total=self.number(self.text("nav.actions a.count", heading)),
            )
            for action in heading.select("nav.actions a"):
                count = action.select_one("span.action-count")
                if count is None:
                    continue
                label = action.get_text(" ", strip=True).replace(
                    count.get_text(" ", strip=True), ""
                ).strip()
                if label in _ACTION_ATTR:
                    setattr(summary, _ACTION_ATTR[label], self.number(count.get_text(strip=True)))
            summaries.append(summary)
        return summaries
