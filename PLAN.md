# Pricewatcher plan

One row per Product, cheapest Shop shown, click through for all Shop prices. Terms: see `GLOSSARY.md`.

## Decisions (settled)

- Standalone app, single user, LAN only, no login.
- Python, FastAPI + Jinja/HTMX + Tailwind (CDN), SQLite, Playwright (fallback only), one Docker image on the homelab.
- EUR only.
- Check every Listing once per check interval (Settings: 1-24h, default 6h) with jitter, except during the optional quiet hours (Belgian time). N failed checks in a row = stale (Settings, default 3); stale Listings keep their last good price and are excluded from Cheapest Shop. One successful check resets the fail count and the Listing is ok again.
- Cheapest Shop = lowest in-stock, non-stale price, incl. shipping when the page exposes it. If no Listing qualifies, the overview shows "no in-stock offer"; the spread is hidden when fewer than two Listings qualify.
- Telegram alerts via env vars (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), one chat. Triggers:
  - Cheapest price drops below the Product's Target Price (only when one is set).
  - New all-time low: the Cheapest price is lower than any Cheapest price recorded for that Product before. Fires with or without a Target Price, but never on the Product's first successful check. Settings can turn it off, or require a minimum drop in % below the earlier low.
  - De-dup: an alert fires only when the Cheapest price is below `product.last_alert_price` (or none is stored yet); sending sets it. A price rise does not reset it, so bouncing prices don't re-alert.
  - Only background checks alert; the check made while Matching a Shop does not (you are looking at that price already).
- Shops: amazon.nl, amazon.com.be, bol.com, coolblue.be, mediamarkt.be, vandenborre.be, krefel.be, alternate.be. One code adapter per Shop; Shops with JSON-LD can also be added on the Settings page. fnac.be was dropped (2026-11-17): its search is behind a captcha.

## Data model (SQLite)

All amounts are stored as integer euro cents.

- `product(id, name, ean, mpn, asin, image_url, target_price, last_alert_price, created_at)`
- `listing(id, product_id, shop, url, title, fail_count, last_price, last_in_stock, last_shipping, last_checked)`; unique (product_id, shop). Stale is derived (`fail_count >=` the Settings threshold), not stored.
- `price_check(id, listing_id, checked_at, price, shipping, in_stock, ok)`; history for charts and the all-time-low check
- `setting(key, value)`; Settings as JSON values, loaded into memory at start (one process).
- Deleting a Product cascades to its Listings and checks. Re-Matching a Listing to a new URL clears that Listing's checks (old history belongs to another page).

## Shop adapter interface

```python
class Shop:
    key: str                      # "bol.com"
    def search(self, query: Query) -> list[Hit]      # Hit: url, title, price, image, ean/asin if present
    def fetch(self, url: str) -> Offer               # Offer: price, shipping|None, in_stock, ean|None
```

- Fetch order: plain HTTP, parse JSON-LD `Offer` first, then shop-specific selectors; on block/empty, retry once via Playwright. Adapter declares `needs_browser = True` when plain HTTP is known to fail.
- Search query priority: EAN, then ASIN (Amazon only), then MPN, then name.
- Fetch returns an error value, never a made-up price; scheduler counts it as a failure.

## Screens

1. **Overview**: row = image, name, Cheapest Shop + price, spread vs next Shop, last checked, stale flag. "Add product" button. A total at the bottom: the sum of every Product's Cheapest price (Products without an in-stock offer are left out and counted).
2. **Add product**: name + optional EAN/MPN/ASIN, tick Shops. Per Shop show top 3 hits (title, price, image); pick one, paste a URL, or skip. Hit whose EAN/ASIN equals the input is pre-selected. Pick saves the Listing at once; its first check runs in the background (a browser fetch takes seconds).
3. **Product detail**: table of all Listings (Shop, price, shipping, stock, status, last checked), price history chart per Listing, Target Price field, edit name and EAN/MPN/ASIN, add/re-Match/remove Shop, delete.

## UI

Modern look, no JS build step. Server-rendered Jinja templates plus:

- **Tailwind CSS** via CDN (pinned version). Dark mode follows the OS (`dark:` variants).
- **HTMX** for the add flow (per-Shop search results load in as they arrive), inline Target Price edit and re-Match, no full page reloads.
- **Chart.js** from a CDN for the price history, one line per Listing.
- Overview as a card/table list with product image; Cheapest Shop as a green badge, stale as a red chip, spread vs next Shop in muted text.
- Responsive: usable on a phone (single-column cards below the `md` breakpoint).
- Pin CDN versions; if the homelab should work offline, vendor the files into the image instead.

## Milestones

1. **Skeleton** (done): project layout, DB schema, Shop interface, Cheapest Shop calculation (with unit tests), FastAPI app, Dockerfile, overview and detail pages on seed data.
2. **First adapters** (done): bol.com, coolblue.be, amazon (.nl/.com.be). Add-product flow with Match. Fixture-based parser tests (saved HTML per Shop).
3. **Scheduler** (done): in-process loop, 6h + jitter, failure counting, stale logic and recovery, price history. Playwright fallback. Uvicorn runs with exactly 1 worker (set in the Dockerfile), or every check runs twice.
4. **Alerts** (done): Telegram sender, Target Price and all-time-low triggers, de-dup so one drop alerts once. Also: Target Price form, remove a Shop from a Product, first check after Pick in the background.
5. **Remaining adapters**, one at a time: mediamarkt.be (done), vandenborre.be (done), krefel.be (site down for maintenance on 2026-11-17, retry later), alternate.be (done). Each ships with a fixture test.
6. **Settings** (done): Check now buttons; a Settings page for the check interval, quiet hours, stale threshold, all-time-low alerts and a Telegram test message.
6. **Polish**: history chart (done, total incl. known shipping per Shop, stepped line), re-Match, docs in README (done), homelab deploy (compose file written; image built and tested locally 2026-11-17, not yet on Proxmox) (docker compose, volume for the SQLite file; carry over the local `data/pricewatcher.db` so existing Products and history are kept).

## Tests

- Pure logic with unit tests: Cheapest Shop selection (stock, stale, shipping, none qualifying), stale transition and recovery, alert triggers (no alert on first check) and de-dup.
- Price parsing: EU formats (`1.299,99`, `€ 49,-`, `49,99 €`).
- Adapters: parse saved HTML fixtures for both search results and product pages, no live network in tests.
- One manual live smoke run per adapter before it counts as done.

## Risks and unknowns

- Tested 2026-11-17: bol.com and coolblue.be work over plain HTTP with JSON-LD (bol.com includes shipping, Coolblue does not). amazon.nl, amazon.com.be and amazon.de all block plain HTTP (503 or captcha) but work through headless Chromium (Playwright), about 3 s per page. Amazon has no JSON-LD, so its adapter reads the buy box with selectors. amazon.de was dropped afterwards (not wanted as a Shop).
- Tested 2026-11-17: mediamarkt.be works over plain HTTP. Search is a JSON-LD ItemList; the product page wraps a ProductGroup (the page's own product, incl. shipping and EAN) in a BuyAction, with other variants under `hasVariant`.
- Tested 2026-11-17: vandenborre.be product pages work over plain HTTP with JSON-LD (incl. shipping and EAN). Search results are rendered client-side (Algolia), so search runs in the browser (2-4 s) and reads the result cards; an exact match redirects to the product page. The page keeps polling, so the browser waits for cards, the redirect or the no-results message instead of network idle. Its search finds nothing for an EAN and gives fuzzy matches for an MPN, so it searches by name only.
- Tested 2026-11-17: fnac.be product pages (nl. and fr.fnac.be) work over plain HTTP with JSON-LD (price, stock, EAN; no shipping). Search answers 403 with a captcha, also in headless Chromium, Not working around the captcha; a paste-only adapter was built, then dropped.
- Tested 2026-11-17: alternate.be works over plain HTTP. Search returns server-rendered cards (an EAN finds the exact product); product pages have JSON-LD with price, stock, shipping (€ 6,99) and the EAN (in `gtin8`). Pages claim UTF-8 but send cp1252 bytes, so decoding falls back to cp1252.
- 2026-11-17: krefel.be answered every request (plain HTTP and browser) with a 500 maintenance page; adapter postponed.
- Amazon sets the delivery country from the visitor's IP. From a Belgian IP (laptop, homelab) both show delivery to Belgium and the matching shipping fee, so no location cookie is needed. A VPN exit abroad would change prices.
- Amazon finds nothing for some EANs; its search falls back to MPN, then name. An ASIN skips search and opens the product page.
- Anti-bot: Amazon, bol.com, MediaMarkt, Vandenborre, Krefel may block plain HTTP or even headless Playwright. Untested; milestone 2 settles it for the first three. Fallback: skip a Shop rather than ship flaky scraping.
- Shipping cost is not always on the product page; "unknown" shipping is treated as 0 and shown as such.
- Shop markup changes will break adapters; the stale flag makes this visible instead of silent.
- A minimum drop for all-time-low alerts compares with the earlier low, so a slow slide in small steps never alerts; the Target Price covers that case.
- A failed Telegram send is logged, not retried, so that alert is lost (de-dup already counts it as sent).
- Scraping may breach some Shops' ToS; personal low-volume use only, no parallel hammering.
- Out of scope v1: non-EUR Shops, multi-user, UI-configurable Telegram, price comparison sites as sources.
