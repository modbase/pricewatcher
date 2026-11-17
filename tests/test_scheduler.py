import threading

from app import checks, db, scheduler
from app.shops import SHOPS, FetchError, Offer
from app.shops.base import Shop


class FakeShop(Shop):
    key = "fake.test"

    def __init__(self, results):
        self.results, self.calls = list(results), []

    def fetch(self, url):
        self.calls.append(url)
        return self.results.pop(0)


def setup(tmp_path, monkeypatch, *results):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "t.db"))
    shop = FakeShop(results)
    monkeypatch.setitem(SHOPS, shop.key, shop)
    db.init()
    with db.connect() as con:
        pid = con.execute("INSERT INTO product (name) VALUES ('x')").lastrowid
        new = con.execute("INSERT INTO listing (product_id, shop, url) VALUES (?, 'fake.test', 'u1')", (pid,)).lastrowid
        fresh = con.execute(
            "INSERT INTO listing (product_id, shop, url, last_checked) VALUES (?, 'bol.com', 'u2', ?)",
            (pid, checks.now()),
        ).lastrowid
    return shop, new, fresh


def run():
    return scheduler.run_due(threading.Event(), pause=(0, 0))


def listing(lid):
    with db.connect() as con:
        return con.execute("SELECT * FROM listing WHERE id = ?", (lid,)).fetchone()


def test_checks_only_due_listings(tmp_path, monkeypatch):
    shop, new, fresh = setup(tmp_path, monkeypatch, Offer(1000, 0, True))
    assert run() == 1
    assert shop.calls == ["u1"]
    assert listing(new)["last_price"] == 1000
    assert run() == 0  # just checked, not due for 6h


def test_stale_after_three_failures_and_recovers(tmp_path, monkeypatch):
    shop, new, _ = setup(tmp_path, monkeypatch, *[FetchError("blocked")] * 3, Offer(900, None, True))
    for expected in (1, 2, 3):
        with db.connect() as con:
            con.execute("UPDATE listing SET last_checked = '2000-01-01 00:00:00' WHERE id = ?", (new,))
        run()
        assert listing(new)["fail_count"] == expected
    with db.connect() as con:
        con.execute("UPDATE listing SET last_checked = NULL WHERE id = ?", (new,))
    run()
    assert (listing(new)["fail_count"], listing(new)["last_price"]) == (0, 900)


def test_skips_listing_rematched_during_fetch(tmp_path, monkeypatch):
    shop, new, _ = setup(tmp_path, monkeypatch, Offer(1000, 0, True))

    def fetch(url):
        with db.connect() as con:
            con.execute("UPDATE listing SET url = 'other' WHERE id = ?", (new,))
        return Offer(1000, 0, True)

    shop.fetch = fetch
    assert run() == 0
    assert listing(new)["last_checked"] is None


def test_browser_fallback_after_plain_http_fails():
    class Plain(Shop):
        key = "plain.test"
        used = []

        def get(self, url, use_browser=None):
            self.used.append(use_browser)
            if not use_browser:
                raise OSError("503")
            return url, "<html>"

        def parse(self, html):
            return Offer(500, 0, True)

    shop = Plain()
    assert shop.fetch("https://plain.test/p") == Offer(500, 0, True)
    assert shop.used == [False, True]


def test_check_now_ignores_due_and_scopes_to_product(tmp_path, monkeypatch):
    shop, new, fresh = setup(tmp_path, monkeypatch, Offer(1000, 0, True), Offer(950, 0, True))
    with db.connect() as con:
        other = con.execute("INSERT INTO product (name) VALUES ('y')").lastrowid
        con.execute("INSERT INTO listing (product_id, shop, url, last_checked) VALUES (?, 'fake.test', 'u3', ?)",
                    (other, checks.now()))
    pid = listing(new)["product_id"]
    monkeypatch.setitem(SHOPS, "bol.com", shop)  # the fresh Listing's Shop
    assert scheduler.check_now(pid, pause=(0, 0)) == 2  # fresh one too: a manual check ignores the 6h interval
    assert sorted(shop.calls) == ["u1", "u2"]
    assert "u3" not in shop.calls


def test_check_now_all_products(tmp_path, monkeypatch):
    shop, new, fresh = setup(tmp_path, monkeypatch, Offer(1000, 0, True), Offer(950, 0, True))
    monkeypatch.setitem(SHOPS, "bol.com", shop)
    assert scheduler.check_now(pause=(0, 0)) == 2


def test_check_now_skips_when_already_running(tmp_path, monkeypatch):
    shop, new, _ = setup(tmp_path, monkeypatch)
    pid = listing(new)["product_id"]
    assert scheduler.start_check(pid)
    assert not scheduler.start_check(pid)  # second click while the first is running
    assert not scheduler.start_check(None)  # a full check would check this Product too
    scheduler.end_check(pid)
    assert scheduler.start_check(None)
    assert not scheduler.start_check(pid)
    scheduler.end_check(None)
