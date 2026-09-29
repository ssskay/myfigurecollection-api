"""Pydantic models for everything the parsers return."""

from __future__ import annotations

import datetime
from enum import Enum, IntEnum

from pydantic import BaseModel, Field


class ItemCategory(IntEnum):
    """MFC's ``categoryId`` values, as used in ``item-category-N`` CSS classes."""

    PREPAINTED = 1
    ACTION_DOLLS = 2
    TRADING = 3
    GARAGE_KITS = 4
    PLUSHES = 5
    ACCESSORIES = 6
    MODEL_KITS = 10
    LINENS = 13
    DISHES = 14
    HANGED_UP = 15
    MISC = 16
    APPAREL = 17
    ON_WALLS = 18
    STATIONERIES = 20
    BOOKS = 21
    MUSIC = 22
    VIDEO = 26
    GAMES = 28
    SOFTWARE = 29


class CollectionStatus(IntEnum):
    """The ``status`` query parameter on a user's collection tab."""

    WISHED = 0
    ORDERED = 1
    OWNED = 2
    FAVORITES = 3


class ArchiveResult(BaseModel):
    """What came back from a Save Page Now attempt.

    Present on an :class:`Item` only when it was read with ``archive=True``.
    Never an exception: a page that could not be captured is a row with
    ``status="failed"`` and a ``reason``, so a read still succeeds when the
    Internet Archive is down.

    ``status``
        ``success``  a new capture completed; ``wayback_url`` is set.
        ``already``  a capture inside the cadence window already existed, so
                     the Archive declined to make another. A preservation
                     success, not a failure; ``wayback_url`` is set.
        ``skipped``  not attempted — the kill switch, the weekly ledger, the
                     per-run cap, or the public-URL guard. ``wayback_url`` may
                     still be set, from the ledger.
        ``pending``  submitted and still capturing when we stopped waiting.
                     ``job_id`` is set; no ``wayback_url`` yet.
        ``failed``   the attempt failed. ``reason`` says how.
    """

    status: str = Field(description="success | already | skipped | pending | failed")
    source_url: str | None = Field(default=None, description="What was asked for")
    wayback_url: str | None = Field(
        default=None, description="The immutable web.archive.org capture, when there is one"
    )
    timestamp: str | None = Field(
        default=None, description="The Archive's own capture stamp, YYYYMMDDhhmmss"
    )
    archived_at: str | None = Field(
        default=None, description="When this result was produced, ISO-8601 UTC"
    )
    job_id: str | None = Field(default=None, description="SPN2 job id, for a pending capture")
    reason: str | None = Field(default=None, description="Why it was skipped or failed")
    error_kind: str | None = Field(
        default=None,
        description=(
            "For a failure: 'transient' (the Archive is busy — says nothing "
            "about the page), 'blocked' (the site's WAF refused the Archive's "
            "crawler — retrying will not help), 'dead' (the page itself "
            "answered badly), or 'unknown'."
        ),
    )

    @property
    def ok(self) -> bool:
        """True when a capture exists to cite, however it got there."""
        return self.wayback_url is not None


class Pagination(BaseModel):
    current_page: int = 1
    total_pages: int = 1
    total_items: int | None = None
    has_next_page: bool = False


class Entry(BaseModel):
    """A linked MFC entry: an origin, character, company, artist or classification."""

    id: int | None = None
    name: str
    name_alt: str | None = Field(default=None, description="Japanese name, when MFC has one")
    url: str | None = None
    image: str | None = None
    role: str | None = Field(default=None, description='e.g. "Manufacturer", "Sculptor"')


class Release(BaseModel):
    date: str | None = Field(default=None, description="As printed, e.g. 02/26/2007 or 03/2006")
    edition: str | None = None
    price: float | None = None
    currency: str | None = None
    barcode: str | None = None


class ItemSummary(BaseModel):
    """An item as it appears in a result list (collection, search, list page)."""

    id: int
    name: str
    url: str
    thumbnail: str | None = None
    category: ItemCategory | None = None
    category_name: str | None = None
    release_date: str | None = None
    barcode: str | None = None


class Item(BaseModel):
    """A full item page."""

    id: int
    name: str
    url: str
    picture: str | None = Field(
        default=None, description="The on-page preview, upload/items/1/ — longest side 256px"
    )
    picture_large: str | None = Field(
        default=None,
        description=(
            "The full-size main picture, upload/items/2/ (e.g. 600x600, 500x750), "
            "read from the page's gallery data. Verified 2026-09-19: /0/ is a "
            "~64px thumbnail, /1/ a 256px preview, /2/ the original upload."
        ),
    )
    gallery: list[str] = Field(
        default_factory=list,
        description="Further official-gallery picture URLs from the same gallery data",
    )
    thumbnail: str | None = None
    category: ItemCategory | None = None
    category_name: str | None = None
    origins: list[Entry] = []
    characters: list[Entry] = []
    companies: list[Entry] = []
    artists: list[Entry] = []
    classifications: list[Entry] = []
    materials: list[str] = []
    releases: list[Release] = []
    scale: str | None = None
    height_mm: int | None = None
    owned_by: int | None = None
    ordered_by: int | None = None
    wished_by: int | None = None
    listed_in: int | None = None
    rating: float | None = None
    rating_count: int | None = None
    added_by: str | None = None
    last_edited_by: str | None = None
    extra: dict[str, str] = Field(
        default_factory=dict,
        description="Any data field we do not model explicitly, as label -> text",
    )
    archive: ArchiveResult | None = Field(
        default=None,
        description=(
            "Set only when the item was read with `archive=True`. Carries the "
            "web.archive.org capture of the public item page, which is what "
            "makes a price row citable."
        ),
    )


class CollectionStats(BaseModel):
    owned: int | None = None
    ordered: int | None = None
    wished: int | None = None
    favorites: int | None = None


class Collection(BaseModel):
    username: str
    status: CollectionStatus
    items: list[ItemSummary] = []
    stats: CollectionStats = CollectionStats()
    pagination: Pagination = Pagination()


class CollectionSummary(BaseModel):
    """The per-root-category counts shown on a profile page."""

    group: str = Field(description='"Figures", "Goods" or "Media"')
    total: int | None = None
    owned: int | None = None
    ordered: int | None = None
    wished: int | None = None
    favorites: int | None = None


class Profile(BaseModel):
    username: str
    url: str
    subtitle: str | None = None
    avatar: str | None = None
    banner: str | None = None
    last_login: datetime.datetime | None = None
    last_login_relative: str | None = None
    joined: datetime.datetime | None = None
    joined_relative: str | None = None
    hits: int | None = None
    rank: int | None = None
    about: dict[str, str] = Field(
        default_factory=dict,
        description='Free-form profile fields, e.g. {"Level": "22", "Location": "Kawasaki"}',
    )
    collection: list[CollectionSummary] = []


class UserListSummary(BaseModel):
    id: int
    name: str
    url: str
    icon: str | None = None
    item_count: int | None = None
    visibility: str | None = Field(default=None, description='e.g. "Public"')
    updated: datetime.datetime | None = None
    updated_relative: str | None = None


class UserLists(BaseModel):
    username: str
    lists: list[UserListSummary] = []
    pagination: Pagination = Pagination()


class ItemList(BaseModel):
    id: int
    name: str
    url: str
    owner: str | None = None
    icon: str | None = None
    description: str | None = None
    item_count: int | None = None
    comment_count: int | None = None
    tags: list[str] = []
    items: list[ItemSummary] = []
    pagination: Pagination = Pagination()


class SearchResults(BaseModel):
    query: str
    items: list[ItemSummary] = []
    pagination: Pagination = Pagination()


class EntryItems(BaseModel):
    """One page of the items linked to an entry (origin, character, company…)."""

    entry_id: int
    items: list[ItemSummary] = []
    pagination: Pagination = Pagination()


class ClubThread(BaseModel):
    id: int
    title: str
    url: str
    status: str | None = Field(default=None, description='e.g. "Open", "Closed"')
    started_by: str | None = None
    started: datetime.datetime | None = None
    last_poster: str | None = None
    last_post: datetime.datetime | None = None
    replies: int | None = None


class ClubComment(BaseModel):
    username: str
    avatar: str | None = None
    body: str
    posted: datetime.datetime | None = None
    posted_relative: str | None = None


class ClubMember(BaseModel):
    username: str
    url: str
    avatar: str | None = None
    role: str | None = Field(default=None, description='e.g. "Founder", "Admin"')


class Club(BaseModel):
    id: int
    name: str
    url: str
    subtitle: str | None = None
    icon: str | None = None
    category: str | None = None
    description: str | None = None
    member_count: int | None = None
    comment_count: int | None = None
    updated: datetime.datetime | None = None
    updated_relative: str | None = None
    threads: list[ClubThread] = []
    comments: list[ClubComment] = []
    staff: list[ClubMember] = []
    members: list[ClubMember] = Field(
        default=[],
        description="Only the handful shown on the club page; see get_club_members for all",
    )


class ClubMembers(BaseModel):
    club_id: int
    members: list[ClubMember] = []
    pagination: Pagination = Pagination()


class PartnerAvailability(str, Enum):
    """From the CSS modifier on the listing's availability chip.

    MFC only knows real stock for items whose barcode it has; everything else
    falls back to MAYBE_AVAILABLE, which means "this shop might carry it",
    not "we checked".
    """

    AVAILABLE = "available"
    MAYBE_AVAILABLE = "maybe_available"
    NOT_AVAILABLE = "not_available"
    UNKNOWN = "unknown"


class PartnerListing(BaseModel):
    shop_name: str
    url: str = Field(description="MFC's affiliate redirect, not the shop's own product page")
    partner_id: int | None = None
    shop_icon: str | None = None
    availability: PartnerAvailability = PartnerAvailability.UNKNOWN
    availability_text: str | None = Field(default=None, description="As printed, e.g. 'Available'")
    price: float | None = None
    currency: str | None = None


class PartnerListings(BaseModel):
    item_id: int
    jan: str | None = Field(
        default=None,
        description="The barcode MFC matched on; without one, no shop reports real stock",
    )
    listings: list[PartnerListing] = []

    @property
    def available(self) -> list[PartnerListing]:
        return [l for l in self.listings if l.availability is PartnerAvailability.AVAILABLE]


class ShopSummary(BaseModel):
    id: int
    name: str
    url: str
    icon: str | None = None
    category: str | None = None
    location: str | None = None
    score: float | None = Field(default=None, description="Average user review score, 0-5")
    review_count: int | None = None
    status: str | None = Field(default=None, description='e.g. "Out of business"')


class ShopSearchResults(BaseModel):
    shops: list[ShopSummary] = []
    pagination: Pagination = Pagination()


class Shop(BaseModel):
    id: int
    name: str
    url: str
    logo: str | None = None
    category: str | None = None
    since: int | None = None
    homepage: str | None = None
    username: str | None = Field(default=None, description="The shop's MFC account, if it has one")
    location: str | None = None
    shipping: str | None = None
    is_partner: bool = False
    rating: float | None = None
    rating_count: int | None = None
    review_count: int | None = None
    item_count: int | None = None
    likes: int | None = None


class BarcodeMatch(BaseModel):
    """The result of a JAN/UPC lookup.

    A unique barcode redirects straight to its item, so `item` is populated and
    `matched` is True. Anything else (no match, or several) comes back as a
    possibly-empty `items` list.
    """

    barcode: str
    matched: bool = False
    item: Item | None = None
    items: list[ItemSummary] = []
