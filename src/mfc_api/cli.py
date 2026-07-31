"""The `mfc-api` command.

With no arguments it starts the MCP server on stdio, which is what an MCP
client invokes. With a subcommand it acts as a plain CLI, which is how you
check the scraper by hand:

    mfc-api item 287
    mfc-api collection Climbatize --status owned
    mfc-api club 349
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .client import MFCClient
from .exceptions import MFCError
from .models import CollectionStatus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mfc-api",
        description=(
            "Unofficial MyFigureCollection reader. Prints JSON. "
            "With no subcommand, starts the MCP server on stdio."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log requests to stderr")
    parser.add_argument("--no-cache", action="store_true", help="bypass the on-disk cache")
    # Not required: bare `mfc-api` is the MCP server entry point.
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="start the MCP server on stdio (the default)")

    p = sub.add_parser("item", help="fetch an item by id")
    p.add_argument("item_id", type=int)

    p = sub.add_parser("search", help="search items by title")
    p.add_argument("query")
    p.add_argument("--page", type=int, default=1)

    p = sub.add_parser("barcode", help="look an item up by JAN/UPC")
    p.add_argument("barcode")

    p = sub.add_parser("listings", help="partner shop listings and prices for an item")
    p.add_argument("item_id", type=int)

    p = sub.add_parser("shop", help="fetch a shop by id")
    p.add_argument("shop_id", type=int)

    p = sub.add_parser("shops", help="browse the shop directory")
    p.add_argument("keywords", nargs="?", help="matches name or location")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--min-score", type=int, choices=range(1, 6), help="minimum average score")
    p.add_argument("--partners", action="store_true", help="MFC partner shops only")

    p = sub.add_parser("profile", help="fetch a user profile")
    p.add_argument("username")

    p = sub.add_parser("collection", help="fetch a page of a user's collection")
    p.add_argument("username")
    p.add_argument(
        "--status",
        default="owned",
        choices=[s.name.lower() for s in CollectionStatus],
    )
    p.add_argument("--page", type=int, default=1)

    p = sub.add_parser("lists", help="fetch a user's item lists")
    p.add_argument("username")
    p.add_argument("--page", type=int, default=1)

    p = sub.add_parser("list", help="fetch an item list by id")
    p.add_argument("list_id", type=int)
    p.add_argument("--page", type=int, default=1)

    p = sub.add_parser("club", help="fetch a club by id")
    p.add_argument("club_id", type=int)

    p = sub.add_parser("members", help="fetch a club's member roster")
    p.add_argument("club_id", type=int)
    p.add_argument("--page", type=int, default=1)

    sub.add_parser("clear-cache", help="delete every cached page")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command in (None, "serve"):
        # Bare `mfc-api` is how MCP clients launch us. Import here so the CLI
        # path does not pay for loading the MCP SDK.
        from .server import main as serve

        serve()
        return 0

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    client = MFCClient(cache_ttl=0 if args.no_cache else 3600.0)
    try:
        if args.command == "clear-cache":
            print(f"removed {client.clear_cache()} cached pages", file=sys.stderr)
            return 0

        result = {
            "item": lambda: client.get_item(args.item_id),
            "search": lambda: client.search_items(args.query, page=args.page),
            "barcode": lambda: client.search_by_barcode(args.barcode),
            "listings": lambda: client.get_partner_listings(args.item_id),
            "shop": lambda: client.get_shop(args.shop_id),
            "shops": lambda: client.search_shops(
                args.keywords,
                page=args.page,
                average_score=args.min_score,
                partners_only=args.partners,
            ),
            "profile": lambda: client.get_profile(args.username),
            "collection": lambda: client.get_collection(
                args.username,
                status=CollectionStatus[args.status.upper()],
                page=args.page,
            ),
            "lists": lambda: client.get_user_lists(args.username, page=args.page),
            "list": lambda: client.get_list(args.list_id, page=args.page),
            "club": lambda: client.get_club(args.club_id),
            "members": lambda: client.get_club_members(args.club_id, page=args.page),
        }[args.command]()
    except MFCError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    json.dump(result.model_dump(mode="json"), sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
