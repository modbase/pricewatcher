"""User settings, stored in the setting table and kept in memory (one process, see scheduler.py)."""
import json
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Brussels")  # quiet hours are Belgian time
INTERVALS = (1, 2, 3, 6, 12, 24)  # hours; nothing more frequent, or Shops start blocking

DEFAULTS = {
    "interval_hours": 6,
    "stale_after": 3,  # consecutive failed checks
    "low_alerts": True,  # all-time-low alerts; Target Price alerts are always on
    "low_min_drop_pct": 0,  # how far below the earlier low a new low must be to alert
    "quiet_from": None,  # hour 0-23; no scheduled checks from this hour until quiet_until
    "quiet_until": None,
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
    quiet = (v["quiet_from"], v["quiet_until"])
    if quiet != (None, None):
        if None in quiet or not all(0 <= h <= 23 for h in quiet):
            raise ValueError("Quiet hours need a start and an end hour (0-23)")
        if quiet[0] == quiet[1]:
            raise ValueError("Quiet hours must start and end at a different hour")
    v["low_alerts"] = bool(v["low_alerts"])
    return v


def load(con) -> None:
    current.clear()
    current.update(DEFAULTS)
    for key, value in con.execute("SELECT key, value FROM setting"):
        if key in DEFAULTS:
            current[key] = json.loads(value)


def save(con, values: dict) -> None:
    v = validate(values)
    con.executemany(
        "INSERT INTO setting (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        [(k, json.dumps(x)) for k, x in v.items()],
    )
    current.update(v)
