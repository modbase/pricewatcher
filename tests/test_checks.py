from app import checks, db
from app.shops import FetchError, Offer


def test_failures_count_up_and_success_resets(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "t.db"))
    db.init()
    with db.connect() as con:
        pid = con.execute("INSERT INTO product (name) VALUES ('x')").lastrowid
        lid = con.execute("INSERT INTO listing (product_id, shop, url) VALUES (?, 'bol.com', 'u')", (pid,)).lastrowid
        checks.record(con, lid, Offer(1000, 0, True))
        for _ in range(3):
            checks.record(con, lid, FetchError("blocked"))
        l = con.execute("SELECT * FROM listing WHERE id = ?", (lid,)).fetchone()
        assert (l["fail_count"], l["last_price"]) == (3, 1000)  # stale, keeps last good price
        checks.record(con, lid, Offer(900, None, True))
        l = con.execute("SELECT * FROM listing WHERE id = ?", (lid,)).fetchone()
        assert (l["fail_count"], l["last_price"], l["last_shipping"]) == (0, 900, None)
        checks.record(con, lid, Offer(None, None, False))  # out of stock, no price shown
        l = con.execute("SELECT * FROM listing WHERE id = ?", (lid,)).fetchone()
        assert (l["fail_count"], l["last_price"], l["last_in_stock"]) == (0, 900, 0)
        assert con.execute("SELECT count(*) FROM price_check WHERE listing_id = ?", (lid,)).fetchone()[0] == 6
