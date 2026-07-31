# Phase 2 — store integration + install fix

Read INVESTIGATION.md first, especially the Corrections section: tenji's selectors
were stale once already. The rule for everything below is **verify live HTML before
writing any parser** — fetch the real page with the existing transport, save it as a
fixture, then code against what you saw.

## 0. Make the console script work (do this first)

The Xcode `python3` on this Mac is 3.9 and the code needs 3.10+. Working interpreter:
`/usr/local/bin/python3.12`. Run `/usr/local/bin/pip3.12 install -e .` (or
`python3.12 -m pip install -e .`), then verify `mfc-api item 287` works from a fresh
shell. If pip3.12 doesn't exist, use the module form and note the working invocation
in README.

## 1. Partner listings (the store links on item pages)

MFC item pages have a Buy/partner section linking to shops (AmiAmi, HobbyLink Japan,
Solaris Japan, etc.). tenji 0.2 had `request/item/buy.py` (`get_partner_listings`)
— use it as an architecture reference only, selectors are 3 years stale.

- Fetch a live item page for something in-print (e.g. item/2748700, the Bankotsu
  Funko) and inspect what the partner/buy block actually looks like in 2026.
  It may be a separate endpoint (tenji hit a `?mode=` URL — verify) or inline.
- Model: shop name, listing url, price + currency if shown, availability/status.
- New MCP tool + CLI subcommand: `get_partner_listings(item_id)` / `listings <id>`.
- If MFC has removed the partner program or the block is JS-injected and absent
  from server HTML, don't fake it — document exactly what you found in a new
  Corrections entry in INVESTIGATION.md and stop there.

## 2. Shops directory

tenji had `get_shops` (directory w/ keyword/location/score filters) and `get_shop(id)`
at `shops.v4.php` or `/shops`. Verify those pages still exist; if yes, port with
fresh selectors: `get_shop(id)`, `search_shops(...)`. Same live-first rule.

## 3. Barcode lookup

Items carry JAN barcodes (already parsed). Check whether MFC's item search supports
a barcode/JAN parameter (try the advanced search form live — look at what query
params the form submits, e.g. `barcode=`). If it works, add `search_by_barcode(jan)`
as an MCP tool + CLI subcommand — this is the join key for price aggregation across
stores, so it's the highest-value tool in this phase. Document the working param
in INVESTIGATION.md.

## 4. Tests + docs

- Saved-HTML fixtures for every new parser (offline), plus live canaries marked
  `-m live` matching the existing pattern.
- Update the README tool table and MCP config snippet.
- Reuse the existing rate limiter and cache for all new endpoints — no new
  transport paths.

Out of scope: PyPI publish, REST facade, price *history* (that's the
animeprices-stack decision, not this repo's).
