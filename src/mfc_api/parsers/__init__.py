"""Page parsers. Each takes raw HTML and returns a model from :mod:`mfc_api.models`."""

from .base import Parser
from .club import ClubMembersParser, ClubParser
from .collection import CollectionParser
from .item import ItemParser
from .item_list import ItemListParser
from .partner_listings import PartnerListingsParser
from .profile import ProfileParser
from .search import SearchParser
from .shop import ShopParser, ShopsParser
from .user_lists import UserListsParser

__all__ = [
    "Parser",
    "ClubParser",
    "ClubMembersParser",
    "CollectionParser",
    "ItemParser",
    "ItemListParser",
    "PartnerListingsParser",
    "ProfileParser",
    "SearchParser",
    "ShopParser",
    "ShopsParser",
    "UserListsParser",
]
