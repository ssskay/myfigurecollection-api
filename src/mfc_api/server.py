"""MCP server exposing MyFigureCollection as agent-callable tools.

Runs over stdio, so it works with Claude Desktop, Claude Code, and anything
else that speaks MCP. Every tool returns a plain dict (a dumped Pydantic
model), so the agent sees typed, predictable structures.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from .client import MFCClient
from .exceptions import MFCError
from .models import CollectionStatus
from .transport import DEFAULT_RATE_LIMIT

log = logging.getLogger(__name__)

mcp = FastMCP("myfigurecollection")

_client: MFCClient | None = None


def get_client() -> MFCClient:
    """One shared client, so the rate limiter and cache are global to the process."""
    global _client
    if _client is None:
        _client = MFCClient(
            rate_limit=float(os.environ.get("MFC_API_RATE_LIMIT", DEFAULT_RATE_LIMIT)),
            cache_ttl=float(os.environ.get("MFC_API_CACHE_TTL", 3600.0)),
            cache_dir=os.environ.get("MFC_API_CACHE_DIR"),
        )
    return _client


def _call(fn, *args, **kwargs) -> dict:
    """Run a client call, turning our exceptions into readable tool errors."""
    try:
        return fn(*args, **kwargs).model_dump(mode="json")
    except MFCError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def get_item(item_id: int) -> dict:
    """Get a single MyFigureCollection item by id.

    Returns the full item page: name, category, picture, origins, characters,
    companies, artists, releases (date/edition/price/barcode), scale, height,
    rating, and how many users own/ordered/wished it.
    """
    return _call(get_client().get_item, item_id)


@mcp.tool()
def search_items(query: str, page: int = 1, category_id: int | None = None) -> dict:
    """Search MFC items by title. 50 results per page.

    `category_id` optionally narrows by MFC category (1 = Prepainted,
    2 = Action/Dolls, 3 = Trading, 10 = Model Kits, 21 = Books, ...).
    """
    return _call(get_client().search_items, query, page=page, category_id=category_id)


@mcp.tool()
def search_by_barcode(barcode: str) -> dict:
    """Find an MFC item by its JAN/UPC barcode.

    This is the join key for matching an item across stores. A unique barcode
    returns the full item under `item` with `matched: true`; no match returns
    `matched: false` with an empty `items` list.

    Note that MFC does not have a barcode for every item — plenty of items,
    especially Western releases, have none recorded, and cannot be found this way.
    """
    return _call(get_client().search_by_barcode, barcode)


@mcp.tool()
def get_partner_listings(item_id: int) -> dict:
    """Get the partner shops that sell an item, with prices where MFC has them.

    Returns every MFC partner shop with an availability of `available`,
    `not_available` or `maybe_available`, plus `price` and `currency` for the
    ones in stock. The `url` is MFC's affiliate redirect, not the shop's own
    product page.

    Important: real availability and prices only come back for items MFC has a
    barcode for. For an item with no barcode every shop reports
    `maybe_available` with no price — that means "not checked", not "in stock".
    """
    return _call(get_client().get_partner_listings, item_id)


@mcp.tool()
def get_shop(shop_id: int) -> dict:
    """Get a shop: homepage, location, shipping, rating, review and item counts."""
    return _call(get_client().get_shop, shop_id)


@mcp.tool()
def search_shops(
    keywords: str | None = None,
    page: int = 1,
    average_score: int | None = None,
    partners_only: bool = False,
) -> dict:
    """Browse MFC's shop directory. 10 shops per page.

    `keywords` matches location as well as name, so "Japan" works.
    `average_score` filters to shops rated at least that (1-5).
    `partners_only` restricts to MFC partner shops — the same set that appears
    in get_partner_listings.
    """
    return _call(
        get_client().search_shops,
        keywords,
        page=page,
        average_score=average_score,
        partners_only=partners_only,
    )


@mcp.tool()
def get_profile(username: str) -> dict:
    """Get a user's public profile: join date, hits, rank, about fields, and
    per-category collection counts."""
    return _call(get_client().get_profile, username)


@mcp.tool()
def get_collection(username: str, status: str = "owned", page: int = 1) -> dict:
    """Get one page (50 items) of a user's collection.

    `status` is one of: owned, ordered, wished, favorites.
    Check `pagination.has_next_page` and call again with page+1 for more.
    """
    try:
        parsed = CollectionStatus[status.strip().upper()]
    except KeyError:
        valid = ", ".join(s.name.lower() for s in CollectionStatus)
        raise ValueError(f"unknown status {status!r}; expected one of: {valid}")
    return _call(get_client().get_collection, username, status=parsed, page=page)


@mcp.tool()
def get_user_lists(username: str, page: int = 1) -> dict:
    """Get the item lists a user has published, with item counts and ids."""
    return _call(get_client().get_user_lists, username, page=page)


@mcp.tool()
def get_list(list_id: int, page: int = 1) -> dict:
    """Get an item list by id: its owner, description, tags, and items."""
    return _call(get_client().get_list, list_id, page=page)


@mcp.tool()
def get_club(club_id: int) -> dict:
    """Get an MFC club: description, member and comment counts, discussion
    threads, recent comments, staff, and a sample of members."""
    return _call(get_client().get_club, club_id)


@mcp.tool()
def get_club_members(club_id: int, page: int = 1) -> dict:
    """Get the full, paginated member roster for a club."""
    return _call(get_client().get_club_members, club_id, page=page)


def main() -> None:
    """Console-script entry point: start the MCP server on stdio."""
    logging.basicConfig(
        level=os.environ.get("MFC_API_LOG_LEVEL", "WARNING").upper(),
        format="%(levelname)s %(name)s: %(message)s",
        # stdout is the MCP channel; logs must go to stderr.
        stream=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
