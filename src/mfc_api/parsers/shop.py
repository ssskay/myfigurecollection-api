"""Parsers for the shop directory (``/shop/``) and shop pages (``/shop/{id}``).

tenji had both. Its selectors are gone — the directory now renders
``div.dgst.shop-dgst`` digests, and shop pages use the same
``div.data-field`` layout as items and profiles rather than ``div.form-label``.
"""

from __future__ import annotations

import re

from bs4 import Tag

from ..models import Shop, ShopSearchResults, ShopSummary
from .base import Parser


class ShopsParser(Parser):
    """The paginated shop directory."""

    def parse(self) -> ShopSearchResults:
        shops: list[ShopSummary] = []
        for dgst in self.soup.select("div.dgst.shop-dgst"):
            anchor = dgst.select_one("div.dgst-anchor a[href]")
            if anchor is None:
                continue
            shop_id = self.trailing_id(anchor.get("href"))
            if shop_id is None:
                continue

            reviews = dgst.select_one("a.meta[href*='/reviews/']")
            status = dgst.select_one("span.meta.inline-error")
            category = dgst.select_one("a.meta.category[class*=shop-category-]")
            # The location chip is a keyword link with no category class.
            location = next(
                (
                    a.get_text(" ", strip=True)
                    for a in dgst.select("a.meta.category")
                    if not any(c.startswith("shop-category-") for c in (a.get("class") or []))
                ),
                None,
            )

            shops.append(
                ShopSummary(
                    id=shop_id,
                    name=anchor.get_text(" ", strip=True),
                    url=self.absolute(anchor.get("href")),
                    icon=self.attr("a.dgst-icon img", "src", dgst),
                    category=category.get_text(" ", strip=True) if category else None,
                    location=location,
                    score=self.decimal(self.text("span.shop-score", dgst)),
                    review_count=self.number(reviews.get_text(" ", strip=True)) if reviews else None,
                    status=status.get_text(" ", strip=True) if status else None,
                )
            )

        return ShopSearchResults(shops=shops, pagination=self.pagination())


class ShopParser(Parser):
    """A single shop page."""

    def __init__(self, html: str, *, shop_id: int | None = None, url=None) -> None:
        super().__init__(html, url=url)
        self.shop_id = shop_id

    def parse(self) -> Shop:
        shop_id = self.shop_id or self.number(self.text("a.current"))
        if shop_id is None:
            self.require(None, "the shop id")

        name = self.text("h1.title")
        if name is None:
            self.require(None, "the shop headline")

        fields = self.data_fields()
        location = fields.get("Location")
        homepage = fields.get("Homepage")
        user = fields.get("User")

        category, since = self._category_and_year()
        stats = self.soup.select_one("div.object-stats")

        return Shop(
            id=shop_id,
            name=name,
            url=f"https://myfigurecollection.net/shop/{shop_id}",
            logo=self.attr("div.content-icon img", "src"),
            category=category,
            since=since,
            # Each of these is scoped to its own field — passing a missing
            # field through as `parent=None` would search the whole page.
            homepage=self.attr("a", "href", homepage) if homepage else None,
            username=self.text("a", user) if user else None,
            location=self.text("span.shop-location", location) if location else None,
            shipping=self.text("small", location) if location else None,
            is_partner=self.soup.select_one("span.flag.icon-diamond") is not None,
            rating=self.decimal(self.text("[itemprop=ratingValue]")),
            rating_count=self.number(self.attr("[itemprop=ratingCount]", "content")),
            review_count=self._stat(stats, "/reviews/"),
            item_count=self._stat(stats, "/items/"),
            likes=self._likes(stats),
        )

    def _category_and_year(self) -> tuple[str | None, int | None]:
        """The last category chip reads like "Web Shop since 1999"."""
        for chip in reversed(self.soup.select("div.categories span.category")):
            text = chip.get_text(" ", strip=True)
            if not text or chip.has_attr("itemprop"):
                continue
            since = self.number(self.text("strong", chip))
            label = re.sub(r"\s*since\s+\d{4}\s*$", "", text).strip()
            return label or None, since
        return None, None

    def _stat(self, stats: Tag | None, href_fragment: str) -> int | None:
        if stats is None:
            return None
        link = stats.select_one(f"a[href*='{href_fragment}']")
        return self.abbreviated_number(link.get_text(" ", strip=True)) if link else None

    def _likes(self, stats: Tag | None) -> int | None:
        if stats is None:
            return None
        for link in stats.select("a"):
            text = link.get_text(" ", strip=True)
            if "like" in text:
                return self.abbreviated_number(text)
        return None
