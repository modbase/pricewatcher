from fastapi.testclient import TestClient

from app import alerts, checks, db
from app.main import app
from app.shops import FetchError, Offer


def setup(tmp_path, monkeypatch, target=None):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "t.db"))
    db.init()
    with db.connect() as con:
        pid = con.execute("INSERT INTO product (name, target_price) VALUES ('Kettle', ?)", (target,)).lastrowid
        a, b = (
            con.execute("INSERT INTO listing (product_id, shop, url) VALUES (?, ?, ?)", (pid, s, f"https://{s}/p")).lastrowid
            for s in ("bol.com", "coolblue.be")
        )
    return pid, a, b


def check(pid, lid, price, in_stock=True):
    result = Offer(price, 0, in_stock) if price else FetchError("blocked")
    with db.connect() as con:
        return alerts.evaluate(con, pid, checks.record(con, lid, result))


def test_no_alert_on_first_successful_check(tmp_path, monkeypatch):
    pid, a, _ = setup(tmp_path, monkeypatch, target=5000)
    assert check(pid, a, None) is None  # a failed check doesn't count
    assert check(pid, a, 1000) is None  # below target, but the first successful check


def test_all_time_low_with_dedup(tmp_path, monkeypatch):
    pid, a, b = setup(tmp_path, monkeypatch)
    assert check(pid, a, 1000) is None
    assert check(pid, a, 1000) is None  # same price
    msg = check(pid, b, 900)
    assert msg.startswith("Kettle: € 9,00 at coolblue.be (new all-time low)")
    assert "https://coolblue.be/p" in msg
    assert check(pid, b, 950) is None  # rise
    assert check(pid, b, 900) is None  # back to the alerted price: no repeat
    assert check(pid, b, 850) is not None


def test_below_target_and_bounce(tmp_path, monkeypatch):
    pid, a, _ = setup(tmp_path, monkeypatch, target=950)
    assert check(pid, a, 1000) is None
    assert "below target € 9,50" in check(pid, a, 940)
    assert check(pid, a, 1000) is None
    assert check(pid, a, 940) is None  # bounced back, already alerted


def test_out_of_stock_is_not_cheapest(tmp_path, monkeypatch):
    pid, a, b = setup(tmp_path, monkeypatch)
    assert check(pid, a, 1000) is None
    assert check(pid, b, 500, in_stock=False) is None
    assert check(pid, a, 990) is not None  # out-of-stock 500 is not an earlier low


def test_send_without_config_does_nothing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    alerts.send("hi")  # logs, no network


def test_set_target(tmp_path, monkeypatch):
    pid, *_ = setup(tmp_path, monkeypatch)
    with TestClient(app) as c:
        assert "199,99" in c.post(f"/products/{pid}/target", data={"target": "199,99"}).text
        with db.connect() as con:
            assert con.execute("SELECT target_price FROM product").fetchone()[0] == 19999
        c.post(f"/products/{pid}/target", data={"target": ""})
        with db.connect() as con:
            assert con.execute("SELECT target_price FROM product").fetchone()[0] is None
        assert c.post(f"/products/{pid}/target", data={"target": "abc"}).status_code == 422
