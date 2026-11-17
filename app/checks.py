from datetime import UTC, datetime

from .shops import SHOPS, FetchError, Offer


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def record(con, listing_id: int, result) -> None:
    """Store one check result: an Offer resets the fail count, a FetchError adds one."""
    ts = now()
    if isinstance(result, Offer):
        con.execute(
            "INSERT INTO price_check (listing_id, checked_at, price, shipping, in_stock, ok) VALUES (?, ?, ?, ?, ?, 1)",
            (listing_id, ts, result.price, result.shipping, result.in_stock),
        )
        con.execute(
            # Out of stock without a shown price keeps the last known price.
            "UPDATE listing SET fail_count = 0, last_price = COALESCE(?, last_price), last_shipping = ?,"
            " last_in_stock = ?, last_checked = ? WHERE id = ?",
            (result.price, result.shipping, result.in_stock, ts, listing_id),
        )
    else:
        con.execute("INSERT INTO price_check (listing_id, checked_at, ok) VALUES (?, ?, 0)", (listing_id, ts))
        con.execute(
            "UPDATE listing SET fail_count = fail_count + 1, last_checked = ? WHERE id = ?", (ts, listing_id)
        )


def fetch(listing) -> object:
    """Network part of a check; run it outside a write transaction."""
    shop = SHOPS.get(listing["shop"])
    return shop.fetch(listing["url"]) if shop else FetchError(f"no adapter for {listing['shop']}")
