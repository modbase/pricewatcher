from fastapi.testclient import TestClient

from app import seed
from app.main import app, eur


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
        assert c.get("/products/1").status_code == 200
        assert c.get("/products/999").status_code == 404
