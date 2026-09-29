"""Parser for ``/item/{id}`` pages."""

from __future__ import annotations

import json
import re
from urllib.parse import unquote

from bs4 import Tag

from ..models import Entry, Item, Release
from .base import Parser

# Data-field labels we lift into typed attributes. Anything else lands in `extra`.
_ENTRY_FIELDS = {
    "Origin": "origins",
    "Origins": "origins",
    "Character": "characters",
    "Characters": "characters",
    "Company": "companies",
    "Companies": "companies",
    "Artist": "artists",
    "Artists": "artists",
    "Classification": "classifications",
    "Classifications": "classifications",
}

_COUNT_FIELDS = {
    "Owned by": "owned_by",
    "Ordered by": "ordered_by",
    "Wished by": "wished_by",
    "Listed in": "listed_in",
}

_HANDLED = set(_ENTRY_FIELDS) | set(_COUNT_FIELDS) | {
    "Category",
    "Releases",
    "Release",
    "Materials",
    "Material",
    "Dimensions",
    "Average rating",
    "Added by",
    "Last edited by",
}


class ItemParser(Parser):
    def parse(self) -> Item:
        fields = self.data_fields()

        item_id = self.number(self.text("a.current"))
        if item_id is None:
            item_id = self.trailing_id(self.attr("link[rel=canonical]", "href"))
        if item_id is None:
            item_id = self.trailing_id(self.url)
        if item_id is None:
            self.require(None, "the item id")

        name = self.text("h1.title")
        if name is None:
            self.require(None, "the item title")

        # The category id lives on a <span class="item-category-N"> inside the
        # Category field. Scope the lookup to that field — related-item stamps
        # elsewhere on the page carry the same class for *their* categories.
        category = category_name = None
        if "Category" in fields:
            category, category_name = self.category_from_classes(
                fields["Category"].select_one("[class*=item-category-]")
            )
            category_name = category_name or fields["Category"].get_text(" ", strip=True)

        item = Item(
            id=item_id,
            name=name,
            url=f"https://myfigurecollection.net/item/{item_id}",
            picture=self.attr("div.item-picture img", "src"),
            thumbnail=self.attr("img.thumbnail", "src"),
            category=category,
            category_name=category_name,
        )

        item.picture_large, item.gallery = self._gallery()

        for label, value in fields.items():
            if label in _ENTRY_FIELDS:
                getattr(item, _ENTRY_FIELDS[label]).extend(self._entries(value))
            elif label in _COUNT_FIELDS:
                setattr(item, _COUNT_FIELDS[label], self.number(value.get_text(" ", strip=True)))
            elif label in ("Materials", "Material"):
                item.materials = [
                    part.strip()
                    for part in value.get_text(",", strip=True).split(",")
                    if part.strip()
                ]
            elif label in ("Releases", "Release"):
                item.releases = self._releases(value)
            elif label == "Dimensions":
                item.scale, item.height_mm = self._dimensions(value)
            elif label == "Average rating":
                item.rating = self.decimal(self.text("[itemprop=ratingValue]", value))
                item.rating_count = self.number(
                    self.attr("[itemprop=ratingCount]", "content", value)
                )
            elif label == "Added by":
                item.added_by = self.text("a", value) or value.get_text(" ", strip=True)
            elif label == "Last edited by":
                item.last_edited_by = self.text("a", value)
            elif label not in _HANDLED:
                item.extra[label] = value.get_text(" ", strip=True)

        return item

    # -- field parsers ---------------------------------------------------

    def _gallery(self) -> tuple[str | None, list[str]]:
        """The PhotoSwipe data beside the main picture: a URL-encoded JSON list
        of ``{src, w, h}``. Entry 0 is the main picture at full size
        (``upload/items/2/``); the rest are official-gallery pictures."""
        raw = self.attr("div.item-picture meta[content]", "content")
        if not raw:
            return None, []
        try:
            entries = json.loads(unquote(raw))
            sources = [e["src"] for e in entries if isinstance(e, dict) and e.get("src")]
        except (ValueError, TypeError):
            return None, []
        if sources and "/upload/items/" in sources[0]:
            return sources[0], sources[1:]
        return None, sources

    def _entries(self, value: Tag) -> list[Entry]:
        entries: list[Entry] = []
        for anchor in value.select("a.item-entry"):
            image = anchor.select_one("img")
            label = anchor.select_one("span")
            entries.append(
                Entry(
                    id=self.trailing_id(anchor.get("href")),
                    name=(
                        label.get_text(" ", strip=True)
                        if label
                        else (image.get("alt") if image else anchor.get_text(" ", strip=True))
                    ),
                    name_alt=label.get("switch") if label and label.has_attr("switch") else None,
                    url=self.absolute(anchor.get("href")),
                    image=image.get("src") if image else None,
                    role=self._role_after(anchor),
                )
            )
        return entries

    @staticmethod
    def _role_after(anchor: Tag) -> str | None:
        """MFC prints roles as ``<small class="light">as <em>Sculptor</em></small>``
        immediately after the entry (or group of entries) they apply to."""
        for sibling in anchor.next_siblings:
            if isinstance(sibling, Tag):
                if sibling.name == "a" and "item-entry" in (sibling.get("class") or []):
                    return None
                em = sibling.select_one("em") if sibling.name == "small" else None
                if em is not None:
                    return em.get_text(" ", strip=True)
        return None

    def _releases(self, value: Tag) -> list[Release]:
        """One release per ``<br>``-delimited run of nodes."""
        groups: list[list] = [[]]
        for node in value.children:
            if isinstance(node, Tag) and node.name == "br":
                groups.append([])
            else:
                groups[-1].append(node)

        releases: list[Release] = []
        pending: Release | None = None
        for group in groups:
            text = "".join(
                node.get_text(" ", strip=True) if isinstance(node, Tag) else str(node)
                for node in group
            ).strip()
            if not text:
                continue

            date = None
            edition = None
            barcode = None
            for node in group:
                if not isinstance(node, Tag):
                    continue
                if date is None and "time" in (node.get("class") or []):
                    date = node.get_text(" ", strip=True)
                if edition is None and node.name == "small":
                    em = node.select_one("em")
                    if em is not None:
                        edition = em.get_text(" ", strip=True)
                if barcode is None:
                    for link in [node] + node.select("a"):
                        title = link.get("title") or "" if isinstance(link, Tag) else ""
                        if title.startswith("Buy ("):
                            barcode = link.get_text(strip=True) or None
                            break

            price, currency = self._price(text)

            # A release's date line and its price line are separated by a <br>,
            # so a group with no date continues the release before it.
            if date is None and pending is not None:
                pending.price = pending.price or price
                pending.currency = pending.currency or currency
                pending.barcode = pending.barcode or barcode
                continue

            pending = Release(
                date=date, edition=edition, price=price, currency=currency, barcode=barcode
            )
            releases.append(pending)
        return releases

    @staticmethod
    def _price(text: str) -> tuple[float | None, str | None]:
        match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([A-Z]{3})\b", text)
        if not match:
            return None, None
        return float(match.group(1).replace(",", "")), match.group(2)

    def _dimensions(self, value: Tag) -> tuple[str | None, int | None]:
        scale_node = value.select_one("a.item-scale")
        scale = scale_node.get_text("", strip=True).replace(" ", "") if scale_node else None
        height = self.number(self.text("strong", value))
        return scale, height
