# MFC API Investigation — 2026-07-30

## TL;DR

There is no working MyFigureCollection API, official or third-party. But the data is
fully gettable: MFC's legacy scrape-able pages still exist and `curl_cffi` (Chrome TLS
impersonation) passes their Cloudflare wall. Verified live today. The path forward is a
new local-first MCP server + Python lib using tenji's parser design with a swapped
transport layer.

## What's broken and why

**1. MFC's official API is dead.**
Club 349 (https://myfigurecollection.net/club/349) *is* MFC's API club. Its own comments
are the obituary: "API v4 coming soon" posted 8 years ago, never shipped. Comments from
1–4 months ago confirm nothing works and nothing is documented.

**2. tenji-api (github.com/Tenji-hin/tenji-api) is abandoned.**
- Last commit: Sept 12, 2023.
- Thin FastAPI wrapper around the `tenji` scraper lib (PyPI, v0.2, same author, MIT).
- Shipped typos crash two endpoints as-written: `sshop` in shops.py, `sbuys` (NameError).
- No club endpoint at all — only item, list(s), shops, profile, collection, listings.
- Requires Redis for caching; `requirements.txt` is UTF-16-mangled.

**3. The actual killer: Cloudflare.**
Tested live from this machine (2026-07-30):

| Client | Result |
|---|---|
| plain `curl`, any user-agent | **403 "Just a moment..."** challenge page |
| aiohttp (what tenji uses) | blocked the same way |
| real browser | 200, full HTML |
| `curl_cffi` with `impersonate="chrome"` | **200, full HTML** ✅ |

So tenji's parsers never even get HTML to parse. The block is TLS-fingerprint-based,
not user-agent-based — tenji already spoofs a Chrome UA and it doesn't help.

**4. But the parsers still work.**
Verified against live pages today:
- `users.v4.php?mode=view&username=X&tab=collection&page=N&status=S&output=0` still
  serves the legacy markup tenji expects: `div.results-toggles` present,
  `div.results > div.result` matched 50 items/page, stamp/category/pagination intact.
- Item pages (`/item/{id}`) return full HTML with title/data.

## Recommended build: `myfigurecollection-api` (this repo)

**Shape: local-first MCP server + importable Python lib, REST optional.**

Why local-first: Cloudflare challenges are IP-reputation-weighted. Residential IPs +
Chrome TLS impersonation pass; a hosted scraper on datacenter IPs will likely get
challenged and burn the shared IP for everyone. A tool anyone runs locally (uvx /
pipx / MCP config one-liner) is both more reliable and more "AI friendly" — agents
speak MCP natively.

**Stack:**
- Python, `curl_cffi` for transport (`impersonate="chrome"`), `selectolax` or
  BeautifulSoup for parsing
- Parser structure ported from `tenji` v0.2 (MIT, credit Nate Shoffner)
- MCP server via the `mcp` Python SDK (stdio) — tools: `get_item`, `get_collection`,
  `get_profile`, `get_user_lists`, `get_list`, `search_items`, `get_club` (new — tenji
  never had it)
- Optional: FastAPI REST facade for non-MCP consumers, same core lib
- Polite scraping: rate limit (~1 req/s), on-disk cache with TTL, honest README about
  being an unofficial scraper

**Non-goals for v1:** auth/login flows, write operations, hosted deployment.

## Claude Code prompt

```
Build a Python project in ~/Code/myfigurecollection-api: an unofficial
MyFigureCollection.net API exposed as a local MCP server (stdio, `mcp` SDK) plus an
importable lib. Read INVESTIGATION.md first — it has the verified findings.

Core: transport module using curl_cffi with impersonate="chrome" (plain HTTP clients
get Cloudflare 403 — this is verified and non-negotiable), rate-limited to 1 req/s
with an on-disk TTL cache. Port the parser design from the MIT-licensed `tenji` 0.2
package (pip3 install tenji, read its parser/ and request/ dirs; credit Nate Shoffner
in README). URLs and CSS selectors in tenji still match MFC's live markup — verified
2026-07-30 (users.v4.php collection pages: div.results-toggles,
div.results > div.result).

MCP tools: get_item, get_collection(username, status, page), get_profile,
get_user_lists, get_list, get_club (new — parse /club/{id}: description, member
count, threads, comments). Pydantic models, good logging, pytest with saved HTML
fixtures so tests don't hit MFC. python3/pip3, no venv.

Package it for distribution: pyproject.toml with a console-script entry point
(mfc-api) that starts the MCP server, so end users need zero clones — their config
is just `uvx myfigurecollection-api`. README with that copy-paste MCP config
snippet for Claude Desktop/Code, credit to Nate Shoffner's tenji, and a disclaimer
that this is an unofficial scraper (rate-limited, cached, be polite). Don't publish
to PyPI yet — get it working locally first.
```

## Corrections found during the build (2026-07-30)

The transport finding held exactly. The parser finding did not — "tenji's parsers
still work" was too optimistic. The *containers* tenji looks for still exist, but the
markup inside them has moved on, so every selector had to be re-derived from live
pages. Specifically:

| Claim in this doc | Reality |
|---|---|
| `users.v4.php` collection markup matches tenji | URL is fine (200, 50 results/page), but items are now `div.dgst.item-dgst` with `div.dgst-anchor`, not `div.stamp` + `div.stamp-category` |
| `div.results-toggles` holds owned/ordered/wished counts | It holds the Figures/Goods/Media root filter. The counts are on the status tab links (`div.tab > a[href*="status="]`) |
| tenji's list endpoint works | `itemlists.v4.php` **404s**. Lists live at `/list/{id}` and render an icon grid, not digest rows |
| tenji's profile parser works | Profile fields moved from `div.form-label` inside `div.data_2` to `div.data-field` / `div.data-label` / `div.data-value` |
| pagination via `a.nav-next` / `a.nav-last` | Those classes are gone; page links are plain `a.nav-page`, current is `a.nav-current`, last page = highest number |

Also new, not in the original plan:

- **Search needs `title=`, not `keywords=`.** `keywords` renders a "Quick search" icon
  grid with no result count and no pagination. `title=X&output=0` gives 50 parseable
  results per page plus a total.
- **MFC's 404 is a styled 200-shaped page**, so the parser sniffs for `h1.title` == "404"
  in addition to checking the status code.
- Clubs give member/comment counts in `div.object-stats`, threads as `div.dgst-thread`,
  and comments as `div.comment` — none of which tenji ever touched.

What this means: the port is a port of tenji's *architecture* (parser class per page,
HTML in, model out), not of its selectors. Credit still stands.

## Phase 2 findings — store integration (2026-07-31)

Partner listings, shops and barcode lookup are all **live**. MFC has not dropped the
partner program. Three things worth writing down:

**1. The Buy window is a form POST that answers with JSON.**
tenji's envelope (`request/item/buy.py`) survived intact — this is the one piece of
tenji that still works as written:

```
POST https://myfigurecollection.net/item/{id}
     commit=loadWindow&window=buyItem
  -> {"htmlValues": {"WINDOW": "<html…>"}, …}
```

A GET with the same query string just returns the ordinary item page, so the method
matters. Inside the envelope the markup did move: listings are `div.result` with
`div.item-availability` carrying one of `item-is-available` / `item-maybe-available` /
`item-is-not-available`, and the price sits in a `<strong>` inside that chip.

Passing `jan=` explicitly changes nothing — MFC derives the barcode from the item id in
the URL path. Verified both ways against item 287.

Two sibling modes exist on the same endpoint, found in the window's own toggle links:
`soldBy=users` (user marketplace listings; empty for item 287) and `soldBy=stats`.
Neither is built here — stats is price-history-shaped, which belongs to the
animeprices-stack decision, not this repo.

**2. Availability is only real when MFC has a barcode.** This is the finding that
matters for price aggregation. Item 287 (JAN 4543341130624) returns AmiAmi
"Available 11,980 JPY" and Solaris "Not available". Item 2748700 (Funko Bankotsu, no
barcode registered) returns all 32 partners as "Maybe available" with no price and
`itemId=0` in the affiliate link. **"Maybe available" means "not checked", not "in
stock"** — treating it as a stock signal would be wrong. The models and the MCP tool
description both say so explicitly.

**3. Barcode search redirects to the item.** The advanced search form has a `barcode`
field, and it is a *lookup*, not a search:

| Input | Result |
|---|---|
| `?_tb=item&mode=browse&tab=search&barcode=4543341130624&output=0` | **302 to `/item/287`** |
| unknown barcode | stays on the search page, zero results |

So there is no result count to read — you have to look at what came back. The parser
checks the breadcrumb (`a.current` reads "Item #287" on an item page, "Search" on a
result page) rather than the final URL, so it works through the cache too.

Note `barcode=` only matches items whose JAN MFC actually recorded. Plenty of Western
releases have none — the Funko above is a real example — and cannot be found this way.

**4. Shops are live at both URLs.** `/shop/` and `shops.v4.php` return the same page
(220 shops, 10 per page, 22 pages). Fresh selectors, as ever:

| tenji | 2026 |
|---|---|
| `div.list-anchor a`, `img.list-icon`, `div.list-actions` | `div.dgst.shop-dgst` with `div.dgst-anchor` / `a.dgst-icon` / `div.dgst-meta` |
| shop pages via `div.form-label` in `div.shop-object` | same `div.data-field` / `data-label` / `data-value` layout as items and profiles |
| `location=` query parameter | does not exist — the live form sends `keywords`, which matches name *and* location |

Working filters, read off the form: `keywords`, `categoryId`, `averageScore`,
`isPartner=1` (32 shops — the same set the Buy window lists), `sort`, `order`, `page`.

Also: shop pages abbreviate large counts ("11.6k items"), so a naive integer parse
reads 11. There is an `abbreviated_number` helper for that.

## Correction to the install instructions (2026-07-31)

"python3/pip3, no venv" is ambiguous on this Mac and it bit us. In a **minimal-PATH
shell — which is exactly what an MCP client uses to launch a server** — `python3` is
Xcode's 3.9.6, which this code (3.10+ syntax) will not run, and `mfc-api` is not on
`PATH` at all:

```
$ env -i /bin/zsh -c 'which python3; python3 -V; which mfc-api'
/usr/bin/python3
Python 3.9.6
mfc-api not found
```

Install with `/usr/local/bin/pip3.12` (→ Framework Python 3.12.4), and give MCP
configs the **absolute** path to the console script. An interactive login shell is
fine — it already has the Framework bin directory ahead of `/usr/bin`.

`mfc-api` is now one entry point for both jobs: bare `mfc-api` starts the MCP server on
stdio, `mfc-api item 287` runs the CLI. That matches what anyone would type.

## Listing every item under an origin (2026-09-19)

Title search matches names, not links, so it cannot enumerate a franchise
("Chiikawa" by title: 984; by origin link: 7,247). Checked live through the lib:

- `/entry/{id}` is **not** a listing: it renders a partial `span.item-icon` grid
  (65 icons for entry 508519) with no count and no pagination.
- Its own "browse" links go to the item browser: `/?_tb=item&orEntries[]={id}&rootId=N`.
  Adding `output=0` gives the same `div.dgst.item-dgst` rows + `div.results-count`
  as search, so the existing `item_summaries()` / `pagination()` parse it unchanged.
- Origin 237138 (Chiikawa): 7,247 items / 145 pages; `rootId=0` (figures) 739.
  `sort=insert&order=asc` is honoured, which keeps page numbers stable for a
  resumable crawl.
- The Chiikawa movie is a **separate origin** (508519, "Eiga Chiikawa Ningyo no
  Shima no Himitsu"); its items do not carry 237138.
- Pictures: `upload/items/0/` is the thumbnail, `/1/` is `Item.picture`. See
  figure-id/README for the size check.

Shipped as `urls.entry_items` + `MFCClient.get_entry_items(entry_id, page)` +
`mfc-api entry-items`. Fixture: `tests/fixtures/entry_items_237138_page2.html`.

## Verification log

- 2026-07-30: plain curl → 403 challenge (5.6KB "Just a moment..." page)
- 2026-07-30: curl_cffi chrome impersonation → item/287: 200, 67,920 bytes, real title;
  collection page: 200, 74,763 bytes, `results-toggles` present, 50 `div.result`
- 2026-07-30: browser fetch of same collection URL → selectors verified via DOM query
- tenji-api cloned and read end-to-end; tenji 0.2 installed and source-reviewed
- 2026-07-31: Buy window POST → 200, 28.7KB JSON, 32 partner listings; item 287 gives
  AmiAmi "Available 11,980 JPY", item 2748700 gives 32× "Maybe available", no prices
- 2026-07-31: `barcode=4543341130624` → final URL `/item/287`; `barcode=0000000000000`
  → search page, 0 results
- 2026-07-31: `/shop/` → 200, "Shops (Page 1 of 22)", 220 shops; `/shop/12` → AmiAmi,
  rating 4.2 of 277, 11.6k items, partner flag present
- 2026-07-31: `isPartner=1` → 32 shops, matching the 32 listings in the Buy window
