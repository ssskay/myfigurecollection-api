"""Shared parsing helpers.

The overall design — a parser class per page, given raw HTML, returning a
model — is ported from Nate Shoffner's MIT-licensed `tenji` package. The
selectors are not: MFC's markup moved on since tenji's last release, so every
selector here was re-derived from live pages on 2026-07-30.
"""

from __future__ import annotations

import datetime
import logging
import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ..exceptions import MFCNotFoundError, MFCParseError
from ..models import ItemCategory, ItemSummary, Pagination
from ..urls import BASE_URL

log = logging.getLogger(__name__)

# MFC renders timestamps in title attributes as "12/21/2017, 13:01:50" (UTC).
_TIME_FORMAT = "%m/%d/%Y, %H:%M:%S"


class Parser:
    """Base for page parsers. Subclasses implement :meth:`parse`."""

    def __init__(self, html: str, *, url: str | None = None) -> None:
        self.html = html
        self.url = url
        self.soup = BeautifulSoup(html, "html.parser")
        self._raise_if_error_page()

    def parse(self):  # pragma: no cover - interface only
        raise NotImplementedError

    # -- error pages ----------------------------------------------------

    def _raise_if_error_page(self) -> None:
        """MFC serves a styled 404 page, not a bare status code, for missing objects."""
        heading = self.soup.select_one("h1.title")
        if heading is not None and heading.get_text(strip=True) == "404":
            raise MFCNotFoundError(f"MFC has no such object: {self.url or '(unknown url)'}")

    def looks_like_item_page(self) -> int | None:
        """Return the item id if this HTML is an item page, else None.

        A barcode search redirects to the matched item, so the only way to tell
        what came back is to look at the markup. The breadcrumb reads
        "Item #287" on an item page and "Search" on a results page.
        """
        current = self.soup.select_one("a.current")
        if current is None:
            return None
        match = re.fullmatch(r"Item\s*#\s*(\d+)", current.get_text(" ", strip=True))
        return int(match.group(1)) if match else None

    def require(self, tag: Tag | None, what: str) -> Tag:
        if tag is None:
            raise MFCParseError(
                f"could not find {what} on {self.url or 'page'} — "
                "MFC's markup has probably changed"
            )
        return tag

    # -- small helpers --------------------------------------------------

    def text(self, selector: str, parent: Tag | None = None, default: str | None = None):
        node = (parent or self.soup).select_one(selector)
        return node.get_text(" ", strip=True) if node else default

    def attr(
        self,
        selector: str,
        name: str,
        parent: Tag | None = None,
        default: str | None = None,
    ):
        node = (parent or self.soup).select_one(selector)
        if node is None:
            return default
        value = node.get(name)
        return value if value is not None else default

    @staticmethod
    def number(text: str | None) -> int | None:
        """First integer in `text`, ignoring thousands separators."""
        if not text:
            return None
        match = re.search(r"\d[\d,]*", text)
        return int(match.group(0).replace(",", "")) if match else None

    @staticmethod
    def decimal(text: str | None) -> float | None:
        if not text:
            return None
        match = re.search(r"\d[\d,]*(?:\.\d+)?", text)
        return float(match.group(0).replace(",", "")) if match else None

    @classmethod
    def abbreviated_number(cls, text: str | None) -> int | None:
        """Like :meth:`number`, but understands MFC's "11.6k items" shorthand.

        Plain :meth:`number` would read that as 11.
        """
        if not text:
            return None
        match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM])\b", text)
        if match:
            scale = 1_000 if match.group(2).lower() == "k" else 1_000_000
            return int(float(match.group(1).replace(",", "")) * scale)
        return cls.number(text)

    @staticmethod
    def absolute(href: str | None) -> str | None:
        return urljoin(BASE_URL, href) if href else None

    @staticmethod
    def query_value(url: str | None, key: str) -> str | None:
        if not url:
            return None
        values = parse_qs(urlparse(url).query).get(key)
        return values[0] if values else None

    @staticmethod
    def trailing_id(href: str | None) -> int | None:
        """``/item/287`` or ``/list/2509/?page=2`` -> the numeric id."""
        if not href:
            return None
        match = re.search(r"/(\d+)(?:/|$|\?)", href)
        return int(match.group(1)) if match else None

    @staticmethod
    def timestamp(node: Tag | None) -> datetime.datetime | None:
        """Read the absolute time out of a ``<span title="MM/DD/YYYY, HH:MM:SS">``."""
        if node is None:
            return None
        raw = node.get("title") if node.has_attr("title") else None
        if not raw:
            return None
        try:
            parsed = datetime.datetime.strptime(raw, _TIME_FORMAT)
        except ValueError:
            log.debug("unrecognised MFC timestamp: %r", raw)
            return None
        return parsed.replace(tzinfo=datetime.timezone.utc)

    @staticmethod
    def background_image(style: str | None) -> str | None:
        if not style:
            return None
        match = re.search(r"url\(([^)]+)\)", style)
        return match.group(1).strip("'\"") if match else None

    @staticmethod
    def category_from_classes(node: Tag | None) -> tuple[ItemCategory | None, str | None]:
        """Read ``item-category-N`` off an element, plus its label text."""
        if node is None:
            return None, None
        for cls in node.get("class", []):
            match = re.fullmatch(r"item-category-(\d+)", cls)
            if not match:
                continue
            label = node.get_text(" ", strip=True) or None
            try:
                return ItemCategory(int(match.group(1))), label
            except ValueError:
                log.debug("unknown MFC category id %s", match.group(1))
                return None, label
        return None, node.get_text(" ", strip=True) or None

    # -- structures shared across pages ---------------------------------

    def data_fields(self, parent: Tag | None = None) -> dict[str, Tag]:
        """Map of ``div.data-label`` text -> its sibling ``div.data-value`` tag.

        Used by item and profile pages, which both render their metadata as a
        flat list of label/value pairs.
        """
        fields: dict[str, Tag] = {}
        for field in (parent or self.soup).select("div.data-field"):
            label = field.select_one("div.data-label")
            value = field.select_one("div.data-value")
            if label is None or value is None:
                continue
            fields[label.get_text(" ", strip=True)] = value
        return fields

    def pagination(self, parent: Tag | None = None) -> Pagination:
        """Parse ``div.results-count``.

        MFC dropped the old ``nav-next`` / ``nav-last`` classes; today the page
        links are plain ``a.nav-page`` and the current one carries
        ``nav-current``. The highest-numbered link is the last page.
        """
        box = (parent or self.soup).select_one("div.results-count")
        if box is None:
            return Pagination()

        total_items = self.number(self.text("div.results-count-value", box))
        links = box.select("div.results-count-pages a.nav-page")
        if not links:
            return Pagination(current_page=1, total_pages=1, total_items=total_items)

        current = self.number(self.text("a.nav-current", box)) or 1
        numbers = [n for n in (self.number(a.get_text(strip=True)) for a in links) if n]
        total_pages = max(numbers) if numbers else current
        return Pagination(
            current_page=current,
            total_pages=total_pages,
            total_items=total_items,
            has_next_page=current < total_pages,
        )

    def item_summaries(self, parent: Tag | None = None) -> list[ItemSummary]:
        """Parse ``div.dgst.item-dgst`` blocks.

        Collection pages, search results and any other ``output=0`` listing all
        share this markup, so they share this parser.
        """
        items: list[ItemSummary] = []
        for dgst in (parent or self.soup).select("div.dgst.item-dgst"):
            anchor = dgst.select_one("div.dgst-anchor a[href]")
            if anchor is None:
                continue
            item_id = self.trailing_id(anchor.get("href"))
            if item_id is None:
                continue

            name = anchor.get("title") or anchor.get_text(" ", strip=True)
            category, category_name = self.category_from_classes(
                dgst.select_one("a.meta.category")
            )
            metas = [m.get_text(" ", strip=True) for m in dgst.select("div.dgst-meta span.meta")]
            barcode = next((m for m in metas if m.isdigit() and len(m) >= 8), None)

            items.append(
                ItemSummary(
                    id=item_id,
                    name=name,
                    url=self.absolute(anchor.get("href")),
                    thumbnail=self.attr("a.dgst-icon img", "src", dgst),
                    category=category,
                    category_name=category_name,
                    release_date=self.text("span.meta.time", dgst),
                    barcode=barcode,
                )
            )
        return items

    def icon_item_summaries(self, parent: Tag | None = None) -> list[ItemSummary]:
        """Parse ``span.item-icon`` grids, used by list pages and quick search."""
        items: list[ItemSummary] = []
        for icon in (parent or self.soup).select("span.item-icon > a[href]"):
            item_id = self.trailing_id(icon.get("href"))
            if item_id is None:
                continue
            image = icon.select_one("img")
            category, category_name = self.category_from_classes(icon)
            items.append(
                ItemSummary(
                    id=item_id,
                    name=(image.get("alt") if image else None) or f"Item #{item_id}",
                    url=self.absolute(icon.get("href")),
                    thumbnail=image.get("src") if image else None,
                    category=category,
                    category_name=category_name,
                )
            )
        return items
