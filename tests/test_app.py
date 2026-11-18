from pathlib import Path

from fastapi.testclient import TestClient

from app import checks, db, seed
from app.main import app, eur
from app.shops import SHOPS, Hit, Offer, Shop


def test_templates_have_no_mojibake():
    for f in Path("app/templates").glob("*.html"):
        assert "â‚¬" not in f.read_text(encoding="utf-8"), f  # a UTF-8 euro sign decoded as cp1252


def test_eur():
    assert eur(129999) == "€ 1.299,99"
    assert eur(5) == "€ 0,05"
    assert eur(None) == "-"


def test_pages_on_seed_data(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "test.db"))
    seed.seed()
    with TestClient(app) as c:
        page = c.get("/").text
        assert "€ 294,49" in page  # amazon.nl 289,50 + 4,99 shipping beats coolblue 299,99
        assert "No in-stock offer" in page  # Switch 2: all out of stock
        assert "1 stale" in page
        assert "€ 384,48" in page and "1 without an in-stock offer not counted" in page  # total: 89,99 + 294,49
        assert c.get("/products/1").status_code == 200
        assert c.get("/products/999").status_code == 404


class FakeShop(Shop):
    key = "fake.be"

    def search(self, query):
        return [Hit("https://www.fake.be/p/1", "Other", 900), Hit("https://www.fake.be/p/2", "Right", 1000, ean="123")]

    def hit(self, url):
        return Hit(url, "Pasted", None)

    def fetch(self, url):
        return Offer(1000, 0, True)


def test_name_search_hides_unrelated_hits(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "test.db"))
    monkeypatch.setitem(SHOPS, "fake.be", FakeShop())
    with TestClient(app) as c:
        c.post("/products", data={"name": "right", "shop": ["fake.be"]})
        hits = c.get("/products/1/match/fake.be").text
        assert "Right" in hits and "Other" not in hits


def test_add_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "test.db"))
    monkeypatch.setitem(SHOPS, "fake.be", FakeShop())
    with TestClient(app) as c:
        r = c.post("/products", data={"name": "Thing", "ean": "123", "shop": ["fake.be"]}, follow_redirects=False)
        assert r.headers["location"] == "/products/1/match?shop=fake.be"
        hits = c.get("/products/1/match/fake.be").text
        assert hits.index("Right") < hits.index("Other")  # EAN match first
        assert "EAN match" in hits
        assert "Not a fake.be URL" in c.post("/products/1/listings", data={"shop": "fake.be", "url": "https://bol.com/x"}).text
        assert "Pasted" in c.post("/products/1/listings", data={"shop": "fake.be", "url": "https://www.fake.be/p/9"}).text
        assert "€ 10,00" in c.get("/").text
        c.post("/products/1/delete")
        assert "No products yet" in c.get("/").text


def test_check_now(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "test.db"))
    monkeypatch.setitem(SHOPS, "fake.be", FakeShop())
    with TestClient(app) as c:
        c.post("/products", data={"name": "Thing"})
        c.post("/products/1/listings", data={"shop": "fake.be", "url": "https://www.fake.be/p/9"})
        r = c.post("/products/1/check", follow_redirects=False)
        assert r.headers["location"] == "/products/1?checking=1"
        assert "Checking prices" in c.get(r.headers["location"]).text
        assert c.post("/check", follow_redirects=False).headers["location"] == "/?checking=1"
        assert c.post("/products/999/check").status_code == 404


def test_sort_and_manual_order(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "test.db"))
    seed.seed()
    names = ["Sony", "Nintendo", "Logitech"]

    def order(page):
        return sorted(names, key=page.index)

    with TestClient(app) as c:
        assert order(c.get("/").text) == ["Logitech", "Nintendo", "Sony"]  # no manual order yet: by name
        c.post("/sort", data={"sort": "price"})
        assert order(c.get("/").text) == ["Logitech", "Sony", "Nintendo"]  # no in-stock offer last
        c.post("/sort", data={"sort": "shop"})
        assert order(c.get("/").text) == ["Sony", "Logitech", "Nintendo"]  # amazon.nl, bol.com, none
        assert c.post("/sort", data={"sort": "nope"}).status_code == 422
        assert c.post("/order", data={"ids": [2, 1, 3]}).status_code == 204
        assert order(c.get("/").text) == ["Nintendo", "Sony", "Logitech"]
    with TestClient(app) as c:  # a restart keeps the sort and the order
        assert order(c.get("/").text) == ["Nintendo", "Sony", "Logitech"]


def test_groups(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "test.db"))
    seed.seed()
    with TestClient(app) as c:
        c.post("/products/1/edit", data={"name": "Sony", "grp": " Mom "})
        c.post("/products/2/edit", data={"name": "Nintendo", "grp": "Mom"})
        page = c.get("/").text
        assert page.count('data-group="Mom"') == 1 and "2 products" in page
        assert page.index("Logitech") < page.index('data-group="Mom"')  # ungrouped first
        assert '>Mom</option>' in c.get("/products/3").text
        c.post("/products/1/edit", data={"name": "Sony", "grp": ""})  # empty clears the Group
        assert "1 product<" in c.get("/").text
        c.post("/order", data={"ids": [3, 1, 2], "moved": 3, "grp": "Mom"})  # dragged into a Group
        assert "2 products" in c.get("/").text
        c.post("/order", data={"ids": [1, 3, 2], "moved": 3, "grp": ""})  # dragged out again
        assert "1 product<" in c.get("/").text
        c.post("/products/1/edit", data={"name": "Sony", "grp": "Dad"})
        page = c.get("/").text
        assert page.index('data-group="Dad"') < page.index('data-group="Mom"')  # no Group order yet: by name
        assert c.post("/group-order", data={"names": ["Mom", "Dad"]}).status_code == 204
        page = c.get("/").text
        assert page.index("Logitech") < page.index('data-group="Mom"') < page.index('data-group="Dad"')
        assert 'value="Mom"' in c.get("/settings").text
        c.post("/settings/groups", data={"old": "Mom", "new": " Mum "})  # rename keeps its place in the order
        page = c.get("/").text
        assert 'data-group="Mom"' not in page and page.index('data-group="Mum"') < page.index('data-group="Dad"')
        c.post("/settings/groups", data={"old": "Dad", "new": "Mum"})  # rename onto an existing Group merges
        assert c.get("/").text.count("data-group=") == 1 and "2 products" in c.get("/").text
        c.post("/settings/groups", data={"old": "Mum", "new": ""})  # empty ungroups
        assert 'data-group="Mum"' not in c.get("/").text


def test_adds_position_to_old_database(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "test.db"))
    import sqlite3
    sqlite3.connect(tmp_path / "test.db").execute("CREATE TABLE product (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    with TestClient(app) as c:
        assert c.get("/").status_code == 200


def test_price_change_bell(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "t.db"))
    with TestClient(app) as c:
        with db.connect() as con:
            pid = con.execute("INSERT INTO product (name) VALUES ('Lamp')").lastrowid
            lid = con.execute("INSERT INTO listing (product_id, shop, url) VALUES (?, 'bol.com', 'u')", (pid,)).lastrowid
            for price in (1000, 1000, None, 900, 950):  # first price, same, no price shown, two changes
                checks.record(con, lid, Offer(price, None, price is not None))
        page = c.get("/").text
        assert "Price changes (2)" in page and "€ 10,00 &rarr; € 9,00" in page and "€ 9,00 &rarr; € 9,50" in page
        with db.connect() as con:
            cid = con.execute("SELECT min(id) FROM price_change").fetchone()[0]
        c.post("/changes/delete", data={"id": cid})
        assert "Price changes (1)" in c.get("/").text
        c.post("/changes/delete")
        assert "No price changes." in c.get("/").text


def test_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "test.db"))
    seed.seed()
    with TestClient(app) as c:
        assert 'id="archived"' not in c.get("/").text
        r = c.post("/products/1/archive", follow_redirects=False)
        assert r.headers["location"] == "/products/1"
        assert "Archived on" in c.get("/products/1").text
        page = c.get("/").text
        assert 'data-id="1"' not in page and 'id="archived"' in page and "Sony" in page  # only in the Archived list
        assert "€ 89,99</span>" in page  # the total leaves out the Archived Product
        with db.connect() as con:
            from app import scheduler
            assert all(l["product_id"] != 1 for l in scheduler.due(con))
        r = c.post("/products/1/unarchive", data={"next": "/"}, follow_redirects=False)
        assert r.headers["location"] == "/"
        page = c.get("/").text
        assert 'data-id="1"' in page and 'id="archived"' not in page
        assert c.post("/products/999/archive").status_code == 404


def test_delete_asks_in_a_dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "test.db"))
    seed.seed()
    with TestClient(app) as c:
        page = c.get("/products/1").text
        assert 'id="delete-dialog"' in page and "cannot be undone" in page and "Archive instead" in page
        assert 'id="remove-dialog"' in page and 'data-action="/products/1/listings/' in page
        c.post("/products/1/delete")
        assert c.get("/products/1").status_code == 404
