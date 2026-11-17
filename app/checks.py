from datetime import UTC, datetime

from .shops import SHOPS, FetchError, Offer


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def record(con, listing_id: int, result) -> int:
    """Store one check result: an Offer resets the fail count, a FetchError adds one. Returns the check id."""
    ts = now()
    if isinstance(result, Offer):
        check_id = con.execute(
            "INSERT INTO price_check (listing_id, checked_at, price, shipping, in_stock, ok) VALUES (?, ?, ?, ?, ?, 1)",
            (listing_id, ts, result.price, result.shipping, result.in_stock),
        ).lastrowid
        con.execute(
            # Out of stock without a shown price keeps the last known price.
            "UPDATE listing SET fail_count = 0, last_price = COALESCE(?, last_price), last_shipping = ?,"
            " last_in_stock = ?, last_checked = ? WHERE id = ?",
            (result.price, result.shipping, result.in_stock, ts, listing_id),
        )
    else:
        check_id = con.execute(
            "INSERT INTO price_check (listing_id, checked_at, ok) VALUES (?, ?, 0)", (listing_id, ts)
        ).lastrowid
        con.execute(
            "UPDATE listing SET fail_count = fail_count + 1, last_checked = ? WHERE id = ?", (ts, listing_id)
        )
    return check_id


def record_if_current(con, listing_id: int, url: str, result) -> int | None:
    """Record unless the Listing was deleted or re-Matched while fetching; returns the check id."""
    if con.execute("SELECT 1 FROM listing WHERE id = ? AND url = ?", (listing_id, url)).fetchone():
        return record(con, listing_id, result)
    return None


def fetch(listing) -> object:
    """Network part of a check; run it outside a write transaction."""
    shop = SHOPS.get(listing["shop"])
    return shop.fetch(listing["url"]) if shop else FetchError(f"no adapter for {listing['shop']}")
