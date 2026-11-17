STALE_AFTER = 3  # consecutive failed checks


def eur(cents) -> str:
    if cents is None:
        return "-"
    euros, rest = divmod(cents, 100)
    return f"€ {euros:,}".replace(",", ".") + f",{rest:02d}"


def is_stale(listing) -> bool:
    return listing["fail_count"] >= STALE_AFTER


def total(listing) -> int:
    # Unknown shipping counts as 0; the UI shows it as unknown.
    return listing["last_price"] + (listing["last_shipping"] or 0)


def ranked(listings) -> list:
    """Listings that count toward Cheapest Shop, cheapest first."""
    ok = [
        l for l in listings
        if l["last_price"] is not None and l["last_in_stock"] and not is_stale(l)
    ]
    return sorted(ok, key=total)
