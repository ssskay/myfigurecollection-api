"""The high-level client: one method per MFC page we understand."""

from __future__ import annotations

import logging

from . import urls
from .cache import DiskCache
from .models import (
    BarcodeMatch,
    Club,
    ClubMembers,
    Collection,
    CollectionStatus,
    Item,
    ItemList,
    PartnerListings,
    Profile,
    SearchResults,
    Shop,
    ShopSearchResults,
    UserLists,
)
from .parsers import (
    ClubMembersParser,
    ClubParser,
    CollectionParser,
    ItemListParser,
    ItemParser,
    PartnerListingsParser,
    ProfileParser,
    SearchParser,
    ShopParser,
    ShopsParser,
    UserListsParser,
)
from .transport import DEFAULT_IMPERSONATE, DEFAULT_RATE_LIMIT, Transport

log = logging.getLogger(__name__)


class MFCClient:
    """Read MyFigureCollection.

    This is an unofficial scraper. It is rate-limited to one request per second
    and caches to disk by default; please leave both alone.

        >>> with MFCClient() as mfc:
        ...     item = mfc.get_item(287)
        ...     item.name
        "Aria - Alice Carroll - Maa - 1/6 (Toy's Works)"
    """

    def __init__(
        self,
        *,
        impersonate: str = DEFAULT_IMPERSONATE,
        rate_limit: float = DEFAULT_RATE_LIMIT,
        cache_ttl: float = 3600.0,
        cache_dir: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.transport = transport or Transport(
            impersonate=impersonate,
            rate_limit=rate_limit,
            cache=DiskCache(cache_dir, ttl=cache_ttl),
        )

    # -- items ----------------------------------------------------------

    def get_item(self, item_id: int) -> Item:
        """A single figure/goods/media item by its MFC id."""
        url = urls.item(item_id)
        return ItemParser(self.transport.get(url), url=url).parse()

    def search_items(
        self,
        query: str,
        *,
        page: int = 1,
        category_id: int | None = None,
        sort: str = "insert",
        order: str = "desc",
    ) -> SearchResults:
        """Search items by title. 50 results per page."""
        url = urls.search_items(
            query, page=page, category_id=category_id, sort=sort, order=order
        )
        return SearchParser(self.transport.get(url), query=query, url=url).parse()

    def search_by_barcode(self, barcode: str) -> BarcodeMatch:
        """Look an item up by its JAN/UPC.

        MFC redirects a unique barcode straight to its item page, so a hit
        comes back fully populated in `item`. A miss (or a barcode matching
        several items) comes back as a list in `items`.
        """
        barcode = str(barcode).strip()
        url = urls.search_by_barcode(barcode)
        html = self.transport.get(url)

        parser = SearchParser(html, query=barcode, url=url)
        item_id = parser.looks_like_item_page()
        if item_id is not None:
            item = ItemParser(html, url=url).parse()
            return BarcodeMatch(barcode=barcode, matched=True, item=item)

        results = parser.parse()
        return BarcodeMatch(
            barcode=barcode, matched=bool(results.items), items=results.items
        )

    def get_partner_listings(self, item_id: int) -> PartnerListings:
        """Which partner shops carry an item, and at what price.

        Prices and real availability only come back for items MFC has a barcode
        for. Without one every shop reports "maybe available".
        """
        url, form = urls.partner_listings(item_id)
        body = self.transport.post(url, form)
        return PartnerListingsParser(body, item_id=item_id, url=url).parse()

    # -- shops ----------------------------------------------------------

    def get_shop(self, shop_id: int) -> Shop:
        url = urls.shop(shop_id)
        return ShopParser(self.transport.get(url), shop_id=shop_id, url=url).parse()

    def search_shops(
        self,
        keywords: str | None = None,
        *,
        page: int = 1,
        category_id: int | None = None,
        average_score: int | None = None,
        partners_only: bool = False,
    ) -> ShopSearchResults:
        """Browse the shop directory. 10 shops per page.

        `keywords` matches location as well as name, so "Japan" works.
        """
        url = urls.search_shops(
            keywords,
            page=page,
            category_id=category_id,
            average_score=average_score,
            partners_only=partners_only,
        )
        return ShopsParser(self.transport.get(url), url=url).parse()

    # -- users ----------------------------------------------------------

    def get_profile(self, username: str) -> Profile:
        url = urls.profile(username)
        return ProfileParser(self.transport.get(url), url=url).parse()

    def get_collection(
        self,
        username: str,
        *,
        status: CollectionStatus | int = CollectionStatus.OWNED,
        page: int = 1,
    ) -> Collection:
        """One page (50 items) of a user's collection."""
        status = CollectionStatus(status)
        url = urls.collection(username, status=int(status), page=page)
        return CollectionParser(
            self.transport.get(url), username=username, status=status, url=url
        ).parse()

    def iter_collection(
        self,
        username: str,
        *,
        status: CollectionStatus | int = CollectionStatus.OWNED,
        max_pages: int | None = None,
    ):
        """Yield every page of a collection, stopping at `max_pages` if given.

        Each page is a live request (subject to the rate limit), so a large
        collection takes a while on purpose.
        """
        page = 1
        while True:
            result = self.get_collection(username, status=status, page=page)
            yield result
            if not result.pagination.has_next_page:
                return
            if max_pages is not None and page >= max_pages:
                log.info("stopping at max_pages=%d for %s", max_pages, username)
                return
            page += 1

    def get_user_lists(self, username: str, *, page: int = 1) -> UserLists:
        url = urls.user_lists(username, page=page)
        return UserListsParser(self.transport.get(url), username=username, url=url).parse()

    def get_list(self, list_id: int, *, page: int = 1) -> ItemList:
        url = urls.item_list(list_id, page=page)
        return ItemListParser(self.transport.get(url), list_id=list_id, url=url).parse()

    # -- clubs ----------------------------------------------------------

    def get_club(self, club_id: int) -> Club:
        """A club's description, threads, recent comments, staff and members."""
        url = urls.club(club_id)
        return ClubParser(self.transport.get(url), club_id=club_id, url=url).parse()

    def get_club_members(self, club_id: int, *, page: int = 1) -> ClubMembers:
        url = urls.club_members(club_id, page=page)
        return ClubMembersParser(self.transport.get(url), club_id=club_id, url=url).parse()

    # -- housekeeping ---------------------------------------------------

    def clear_cache(self) -> int:
        return self.transport.cache.clear()

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "MFCClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
