"""Demo data for the UI: python -m app.seed (no-op when products exist)."""
from datetime import UTC, datetime, timedelta

from . import db

# (name, target_price, [(shop, price, shipping, in_stock, fail_count, hours_ago)])
PRODUCTS = [
    ("Sony WH-1000XM5", 29000, [
        ("bol.com", 31999, 0, 1, 0, 2),
        ("coolblue.be", 29999, 0, 1, 0, 3),
        ("amazon.nl", 28950, 499, 1, 0, 2),
        ("amazon.de", 27999, None, 1, 3, 20),
    ]),
    ("Nintendo Switch 2", None, [
        ("mediamarkt.be", 46999, 0, 0, 0, 4),
        ("fnac.be", 46999, 499, 0, 0, 4),
    ]),
    ("Logitech MX Master 3S", 8000, [
        ("coolblue.be", 9999, 0, 1, 0, 1),
        ("bol.com", 8999, None, 1, 0, 1),
        ("krefel.be", 10499, 0, 1, 1, 1),
    ]),
]


def ts(hours_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")


def seed():
    db.init()
    with db.connect() as con:
        if con.execute("SELECT 1 FROM product").fetchone():
            return
        for name, target, listings in PRODUCTS:
            pid = con.execute(
                "INSERT INTO product (name, target_price) VALUES (?, ?)", (name, target)
            ).lastrowid
            for shop, price, shipping, in_stock, fails, hours in listings:
                con.execute(
                    "INSERT INTO listing (product_id, shop, url, title, fail_count, last_price,"
                    " last_shipping, last_in_stock, last_checked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (pid, shop, f"https://www.{shop}/", name, fails, price, shipping, in_stock, ts(hours)),
                )


if __name__ == "__main__":
    seed()
