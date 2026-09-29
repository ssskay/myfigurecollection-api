"""URL builders for the MyFigureCollection pages we read.

Every URL here was verified against the live site on 2026-07-30. Two of the
legacy endpoints the `tenji` package used are gone:

- ``itemlists.v4.php`` now returns 404 — use :func:`item_list` instead.
- ``users.v4.php?tab=collection`` still works and is what :func:`collection`
  uses, because it renders a compact 50-per-page result set.
"""

from urllib.parse import urlencode

BASE_URL = "https://myfigurecollection.net"


def _query(path: str, **params: object) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    return f"{BASE_URL}{path}?{urlencode(clean)}" if clean else f"{BASE_URL}{path}"


def item(item_id: int) -> str:
    return f"{BASE_URL}/item/{item_id}"


def profile(username: str) -> str:
    return f"{BASE_URL}/profile/{username}"


def collection(username: str, status: int, page: int = 1) -> str:
    return _query(
        "/users.v4.php",
        mode="view",
        username=username,
        tab="collection",
        page=page,
        status=status,
        output=0,
    )


def user_lists(username: str, page: int = 1) -> str:
    return _query(
        "/users.v4.php",
        mode="view",
        username=username,
        tab="lists",
        page=page,
    )


def item_list(list_id: int, page: int = 1) -> str:
    return _query(f"/list/{list_id}/", page=page)


def club(club_id: int) -> str:
    return f"{BASE_URL}/club/{club_id}"


def club_members(club_id: int, page: int = 1) -> str:
    return _query(f"/club/{club_id}/members/", page=page)


def search_items(
    query: str,
    page: int = 1,
    category_id: int | None = None,
    root_id: int | None = None,
    sort: str = "insert",
    order: str = "desc",
) -> str:
    """Advanced item search.

    Note the parameter is ``title``, not ``keywords``. ``keywords`` triggers the
    "Quick search" grid, which has no result count and no pagination;
    ``title`` + ``output=0`` gives 50 parseable results per page.
    """
    return _query(
        "/",
        _tb="item",
        mode="browse",
        tab="search",
        title=query,
        categoryId=category_id,
        rootId=root_id,
        output=0,
        sort=sort,
        order=order,
        page=page,
    )


def entry_items(
    entry_id: int,
    page: int = 1,
    root_id: int | None = None,
    sort: str = "insert",
    order: str = "asc",
) -> str:
    """Every item linked to one entry (an origin, character, company…).

    Title search cannot do this: it matches names, not links. The entry page
    itself (``/entry/{id}``) only shows a partial icon grid, but its "browse"
    links point at the item browser with ``orEntries[]={id}``, and adding
    ``output=0`` gives the same 50-per-page digest rows as search, with a
    total. Verified live 2026-09-19 against origin 237138 (Chiikawa): 7,247
    items, 145 pages; ``rootId=0`` narrows to figures (739).

    ``root_id``: 0 figures, 1 goods, 2 media, None for everything. The default
    sort is oldest-insert-first so page numbers stay stable while a crawl is
    in progress — new items land on the last page instead of shifting page 1.
    """
    return _query(
        "/",
        _tb="item",
        **{"orEntries[]": entry_id},
        rootId=root_id,
        output=0,
        sort=sort,
        order=order,
        page=page,
    )


def lists_containing_item(item_id: int, page: int = 1) -> str:
    return _query("/", _tb="list", itemId=item_id, page=page)


def search_by_barcode(barcode: str) -> str:
    """Look an item up by JAN/UPC.

    A unique match 302s straight to ``/item/{id}``; anything else stays on the
    (possibly empty) search page. The caller has to look at what came back.
    """
    return _query(
        "/",
        _tb="item",
        mode="browse",
        tab="search",
        barcode=barcode,
        output=0,
        page=1,
    )


def partner_listings(item_id: int) -> tuple[str, dict[str, str]]:
    """The Buy window: a form POST that answers with JSON, not a page.

    Returns ``(url, form_fields)``. MFC derives the barcode from the item id in
    the path, so passing ``jan`` explicitly changes nothing — verified against
    item 287 both ways.
    """
    return item(item_id), {"commit": "loadWindow", "window": "buyItem"}


def shop(shop_id: int) -> str:
    return f"{BASE_URL}/shop/{shop_id}"


def search_shops(
    keywords: str | None = None,
    page: int = 1,
    category_id: int | None = None,
    average_score: int | None = None,
    partners_only: bool = False,
    sort: str = "name",
    order: str = "asc",
) -> str:
    """The shop directory. 10 shops per page.

    `keywords` matches the location as well as the name — the live form has no
    separate location field, whatever tenji's ``location=`` parameter suggests.
    """
    return _query(
        "/",
        _tb="shop",
        mode="browse",
        keywords=keywords,
        categoryId=category_id,
        averageScore=average_score,
        isPartner=1 if partners_only else None,
        sort=sort,
        order=order,
        page=page,
    )
