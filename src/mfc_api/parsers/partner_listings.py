"""Parser for the Buy window — MFC's partner shop listings for an item.

This is the one endpoint that is not a page. It is a form POST that answers
with JSON, and the markup lives in ``htmlValues.WINDOW``. That envelope is
tenji's discovery (``request/item/buy.py``); it still holds in 2026, though the
listing markup inside it has changed.

The important behaviour to know: **availability and price only appear for items
whose barcode MFC has.** For an item with no JAN, every partner comes back as
"Maybe available" with no price and ``itemId=0`` in the affiliate link.
"""

from __future__ import annotations

import json
import re

from bs4 import Tag

from ..exceptions import MFCParseError
from ..models import PartnerAvailability, PartnerListing, PartnerListings
from .base import Parser

_AVAILABILITY_CLASSES = {
    "item-is-available": PartnerAvailability.AVAILABLE,
    "item-maybe-available": PartnerAvailability.MAYBE_AVAILABLE,
    "item-is-not-available": PartnerAvailability.NOT_AVAILABLE,
}


class PartnerListingsParser(Parser):
    def __init__(self, body: str, *, item_id: int, url=None) -> None:
        super().__init__(self._unwrap(body, url), url=url)
        self.item_id = item_id

    @staticmethod
    def _unwrap(body: str, url: str | None) -> str:
        """Pull the window markup out of MFC's JSON envelope."""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise MFCParseError(
                f"the Buy window at {url or 'MFC'} did not return JSON — "
                "the endpoint has probably changed"
            ) from exc

        html = (payload.get("htmlValues") or {}).get("WINDOW")
        if not html:
            raise MFCParseError(f"the Buy window response for {url or 'MFC'} had no WINDOW markup")
        return html

    def parse(self) -> PartnerListings:
        listings: list[PartnerListing] = []
        jan = None

        for result in self.soup.select("div.result"):
            anchor = result.select_one("div.stamp-anchor a[href]") or result.select_one("a[href]")
            if anchor is None:
                continue

            href = anchor.get("href")
            jan = jan or (self.query_value(href, "jan") or None)
            availability, availability_text, price, currency = self._availability(result)

            listings.append(
                PartnerListing(
                    shop_name=anchor.get_text(" ", strip=True),
                    url=href,
                    partner_id=self.number(self.query_value(href, "partnerId")),
                    shop_icon=self.attr("img.stamp-icon", "src", result),
                    availability=availability,
                    availability_text=availability_text,
                    price=price,
                    currency=currency,
                )
            )

        return PartnerListings(item_id=self.item_id, jan=jan, listings=listings)

    def _availability(
        self, result: Tag
    ) -> tuple[PartnerAvailability, str | None, float | None, str | None]:
        chip = result.select_one("div.item-availability")
        if chip is None:
            return PartnerAvailability.UNKNOWN, None, None, None

        status = PartnerAvailability.UNKNOWN
        for cls in chip.get("class") or []:
            if cls in _AVAILABILITY_CLASSES:
                status = _AVAILABILITY_CLASSES[cls]
                break

        # "Available | 11,980 JPY" — the price sits in a <strong>, the currency
        # is the bare text after it.
        text = chip.get_text(" ", strip=True)
        label = text.split("|")[0].strip() or None

        price = self.decimal(self.text("strong", chip))
        currency = None
        match = re.search(r"([\d,]+(?:\.\d+)?)\s*([A-Z]{3})\b", text)
        if match:
            currency = match.group(2)
            if price is None:
                price = float(match.group(1).replace(",", ""))

        return status, label, price, currency
