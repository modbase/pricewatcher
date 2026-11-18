"""User settings, stored in the setting table and kept in memory (one process, see scheduler.py)."""
import json
import os
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from . import shops

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Brussels"))  # quiet hours are in this timezone
SORTS = ("manual", "name", "price", "shop")  # overview order
INTERVALS = (1, 2, 3, 6, 12, 24)  # hours; nothing more frequent, or Shops start blocking
DOMAIN = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")

DEFAULTS = {
    "interval_hours": 6,
    "stale_after": 3,  # consecutive failed checks
    "low_alerts": True,  # all-time-low alerts; Target Price alerts are always on
    "low_min_drop_pct": 0,  # how far below the earlier low a new low must be to alert
    "quiet_from": None,  # hour 0-23; no scheduled checks from this hour until quiet_until
    "quiet_until": None,
    "sort": "manual",
    "group_order": [],  # Group names top to bottom; Groups not in it follow by name
    "telegram_token": "",  # the TELEGRAM_BOT_TOKEN env var wins when set
    "telegram_chat_id": "",  # the TELEGRAM_CHAT_ID env var wins when set
    "custom_shops": [],  # [{"domain": "example.be", "search_url": "https://...{query}..." or ""}]
}
current = dict(DEFAULTS)


def validate(values: dict) -> dict:
    """The settings with the right types; ValueError when one is out of range."""
    v = {k: values[k] for k in DEFAULTS}
    if v["interval_hours"] not in INTERVALS:
        raise ValueError(f"Check interval must be one of {INTERVALS} hours")
    if not 1 <= v["stale_after"] <= 10:
        raise ValueError("Stale after must be 1 to 10 failed checks")
    if not 0 <= v["low_min_drop_pct"] <= 50:
        raise ValueError("Minimum drop must be 0 to 50%")
    if v["sort"] not in SORTS:
        raise ValueError(f"Sort must be one of {SORTS}")
    if not (isinstance(v["group_order"], list) and all(isinstance(g, str) for g in v["group_order"])):
        raise ValueError("Group order must be a list of names")
    if not all(isinstance(v[k], str) for k in ("telegram_token", "telegram_chat_id")):
        raise ValueError("Telegram token and chat id must be text")
    v["telegram_token"], v["telegram_chat_id"] = v["telegram_token"].strip(), v["telegram_chat_id"].strip()
    v["custom_shops"] = [custom_shop(c) for c in v["custom_shops"]]
    domains = [c["domain"] for c in v["custom_shops"]]
    if len(set(domains)) != len(domains):
        raise ValueError("Each Shop can be added once")
    quiet = (v["quiet_from"], v["quiet_until"])
    if quiet != (None, None):
        if None in quiet or not all(0 <= h <= 23 for h in quiet):
            raise ValueError("Quiet hours need a start and an end hour (0-23)")
        if quiet[0] == quiet[1]:
            raise ValueError("Quiet hours must start and end at a different hour")
    v["low_alerts"] = bool(v["low_alerts"])
    return v


def custom_shop(c: dict) -> dict:
    """A custom Shop entry with its domain normalised; accepts a URL as the domain."""
    raw = str(c.get("domain", "")).strip().lower()
    domain = (urlparse(raw if "//" in raw else "//" + raw).hostname or "").removeprefix("www.")
    if not DOMAIN.fullmatch(domain):
        raise ValueError(f"Not a shop domain: {raw!r}")
    if domain in shops.BUILTIN:
        raise ValueError(f"{domain} is already a built-in Shop")
    search_url = str(c.get("search_url", "")).strip()
    if search_url and not (search_url.startswith(("https://", "http://")) and "{query}" in search_url):
        raise ValueError("The search URL must start with https:// and contain {query}")
    return {"domain": domain, "search_url": search_url}


def load(con) -> None:
    current.clear()
    current.update(DEFAULTS)
    for key, value in con.execute("SELECT key, value FROM setting"):
        if key in DEFAULTS:
            current[key] = json.loads(value)
    shops.sync(current["custom_shops"])


def save(con, values: dict) -> None:
    v = validate(values)
    con.executemany(
        "INSERT INTO setting (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        [(k, json.dumps(x)) for k, x in v.items()],
    )
    current.update(v)
    shops.sync(v["custom_shops"])
