from fastapi.testclient import TestClient

from app import seed
from app.main import app, eur
from app.shops import SHOPS, Hit, Offer, Shop


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
