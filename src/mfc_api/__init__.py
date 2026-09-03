"""An unofficial MyFigureCollection.net API — scraper, Python lib, and MCP server.

MFC has no working public API. This package reads its public HTML pages through
a Chrome-impersonating TLS transport (the only kind Cloudflare lets through),
parses them into Pydantic models, and exposes the result both as a library and
as a local MCP server.
"""

from .archive import Archiver, ArchiveLedger, is_public_item_url, snapshot
from .cache import DiskCache
from .client import MFCClient
from .exceptions import (
    MFCBlockedError,
    MFCError,
    MFCNotFoundError,
    MFCParseError,
    MFCTransportError,
)
from .models import (
    ArchiveResult,
    BarcodeMatch,
    Club,
    ClubComment,
    ClubMember,
    ClubMembers,
    ClubThread,
    Collection,
    CollectionStats,
    CollectionStatus,
    CollectionSummary,
    Entry,
    Item,
    ItemCategory,
    ItemList,
    ItemSummary,
    Pagination,
    PartnerAvailability,
    PartnerListing,
    PartnerListings,
    Profile,
    Release,
    SearchResults,
    Shop,
    ShopSearchResults,
    ShopSummary,
    UserLists,
    UserListSummary,
)
from .transport import Transport

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "MFCClient",
    "Archiver",
    "ArchiveLedger",
    "ArchiveResult",
    "is_public_item_url",
    "snapshot",
    "Transport",
    "DiskCache",
    "MFCError",
    "MFCBlockedError",
    "MFCNotFoundError",
    "MFCParseError",
    "MFCTransportError",
    "BarcodeMatch",
    "Club",
    "ClubComment",
    "ClubMember",
    "ClubMembers",
    "ClubThread",
    "Collection",
    "CollectionStats",
    "CollectionStatus",
    "CollectionSummary",
    "Entry",
    "Item",
    "ItemCategory",
    "ItemList",
    "ItemSummary",
    "Pagination",
    "PartnerAvailability",
    "PartnerListing",
    "PartnerListings",
    "Profile",
    "Release",
    "SearchResults",
    "Shop",
    "ShopSearchResults",
    "ShopSummary",
    "UserLists",
    "UserListSummary",
]
