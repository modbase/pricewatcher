import threading
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import alerts, checks, db, pricing, scheduler, settings
from app.main import app
from app.shops import SHOPS, Offer

from test_alerts import check
from test_alerts import setup as alert_setup
from test_scheduler import setup as scheduler_setup


def save(**values):
    with db.connect() as con:
        settings.save(con, settings.current | values)


def test_saved_settings_survive_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "t.db"))
    db.init()
    save(interval_hours=12, quiet_from=1, quiet_until=7)
    settings.current.update(settings.DEFAULTS)  # as after a restart
    db.init()
    assert (settings.current["interval_hours"], settings.current["quiet_from"]) == (12, 1)


@pytest.mark.parametrize("values", [
    {"interval_hours": 5}, {"stale_after": 0}, {"stale_after": 11}, {"low_min_drop_pct": 51},
    {"quiet_from": 24}, {"quiet_from": 3, "quiet_until": None}, {"quiet_from": 3, "quiet_until": 3},
])
def test_invalid_settings_rejected(tmp_path, monkeypatch, values):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "t.db"))
    db.init()
    with pytest.raises(ValueError), db.connect() as con:
        settings.save(con, settings.current | values)
    assert settings.current == settings.DEFAULTS


def test_interval_setting_decides_what_is_due(tmp_path, monkeypatch):
    shop, new, fresh = scheduler_setup(tmp_path, monkeypatch)
    with db.connect() as con:
        con.execute("UPDATE listing SET last_checked = datetime('now', '-2 hours')")
        assert scheduler.due(con) == []
    save(interval_hours=1)
    with db.connect() as con:
        assert len(scheduler.due(con)) == 2


@pytest.mark.parametrize("quiet, hour, expected", [
    ((1, 7), 0, False), ((1, 7), 1, True), ((1, 7), 6, True), ((1, 7), 7, False),
    ((23, 6), 23, True), ((23, 6), 3, True), ((23, 6), 12, False), ((None, None), 3, False),
])
def test_quiet_hours(quiet, hour, expected):
    settings.current["quiet_from"], settings.current["quiet_until"] = quiet
    assert scheduler.is_quiet(datetime(2026, 1, 1, hour, 30, tzinfo=settings.TZ)) is expected


def test_no_scheduled_round_in_quiet_hours(tmp_path, monkeypatch):
    shop, new, _ = scheduler_setup(tmp_path, monkeypatch, Offer(1000, 0, True), Offer(950, 0, True))
    monkeypatch.setitem(SHOPS, "bol.com", shop)  # the second Listing's Shop
    monkeypatch.setattr(scheduler, "is_quiet", lambda now=None: True)
    assert scheduler.run_due(threading.Event(), pause=(0, 0)) == 0
    assert shop.calls == []
    assert scheduler.check_now(pause=(0, 0)) == 2  # manual checks ignore quiet hours


def test_stale_threshold_setting():
    l = {"shop": "a", "last_price": 100, "last_shipping": 0, "last_in_stock": 1, "fail_count": 2}
    assert pricing.ranked([l]) == [l]
    settings.current["stale_after"] = 2
    assert pricing.ranked([l]) == []


def test_all_time_low_alerts_off(tmp_path, monkeypatch):
    pid, a, _ = alert_setup(tmp_path, monkeypatch, target=950)
    save(low_alerts=False)
    assert check(pid, a, 1000) is None
    assert check(pid, a, 960) is None  # new low, but those alerts are off
    assert "below target" in check(pid, a, 940)  # Target Price alerts still fire


def test_all_time_low_minimum_drop(tmp_path, monkeypatch):
    pid, a, _ = alert_setup(tmp_path, monkeypatch)
    save(low_min_drop_pct=5)
    assert check(pid, a, 1000) is None
    assert check(pid, a, 990) is None  # 1% below the earlier low
    assert check(pid, a, 940) is not None  # 5.05% below 990


def test_send_reports_success(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert alerts.send("hi") is False


def test_settings_page(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCHER_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with TestClient(app) as c:
        page = c.get("/settings").text
        assert "Check interval" in page and "not configured" in page
        form = {"interval_hours": "12", "stale_after": "4", "low_alerts": "on", "low_min_drop_pct": "2",
                "quiet_from": "1", "quiet_until": "7"}
        r = c.post("/settings", data=form, follow_redirects=False)
        assert r.headers["location"] == "/settings?saved=1"
        assert settings.current == {"interval_hours": 12, "stale_after": 4, "low_alerts": True,
                                    "low_min_drop_pct": 2, "quiet_from": 1, "quiet_until": 7, "sort": "manual",
                                    "group_order": []}
        assert "Settings saved" in c.get(r.headers["location"]).text
        form.pop("low_alerts")  # unchecked box: not sent
        form.update(quiet_from="", quiet_until="")
        c.post("/settings", data=form)
        assert (settings.current["low_alerts"], settings.current["quiet_from"]) == (False, None)
        assert c.post("/settings", data=form | {"interval_hours": "5"}).status_code == 422
        r = c.post("/settings/telegram-test", follow_redirects=False)
        assert r.headers["location"] == "/settings?telegram=failed"
