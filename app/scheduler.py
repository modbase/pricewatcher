"""Background checker: rechecks every Listing once per check interval (Settings), one at a time.
The user can also check one Product, or all of them, right away (check_now).

Runs in one thread inside the web process, so uvicorn must run with exactly 1 worker.
A thread (not an asyncio task) because Playwright's sync API cannot run on the event loop thread.
"""
import logging
import random
import threading
from datetime import UTC, datetime, timedelta

from . import alerts, checks, db, settings

log = logging.getLogger(__name__)


def due(con) -> list:
    cutoff = (datetime.now(UTC) - timedelta(hours=settings.current["interval_hours"])).strftime("%Y-%m-%d %H:%M:%S")
    return con.execute(
        "SELECT * FROM listing WHERE last_checked IS NULL OR last_checked <= ? ORDER BY last_checked", (cutoff,)
    ).fetchall()


def check(l) -> bool:
    """Check one Listing and send its alert; False when it was deleted or re-Matched while fetching."""
    result = checks.fetch(l)  # network, outside any transaction
    alert = None
    with db.connect() as con:
        if (check_id := checks.record_if_current(con, l["id"], l["url"], result)) is None:
            return False
        alert = alerts.evaluate(con, l["product_id"], check_id)
    if alert:
        alerts.send(alert)  # after commit: no network inside the transaction
    return True


def run(listings, stop: threading.Event, pause: tuple[float, float]) -> int:
    """Check the given Listings one by one; returns how many were checked."""
    done = 0
    for i, l in enumerate(listings):
        if stop.is_set():
            break
        if i:
            stop.wait(random.uniform(*pause))  # jitter, and no hammering of one Shop
        done += check(l)
    return done


def is_quiet(now: datetime | None = None) -> bool:
    """True during the quiet hours from Settings, when scheduled checks wait."""
    start, end = settings.current["quiet_from"], settings.current["quiet_until"]
    if start is None:
        return False
    hour = (now or datetime.now(settings.TZ)).astimezone(settings.TZ).hour
    return start <= hour < end if start < end else hour >= start or hour < end  # the window may cross midnight


def run_due(stop: threading.Event, pause: tuple[float, float] = (10, 40)) -> int:
    """Check every due Listing, unless it is quiet hours; returns how many were checked."""
    if is_quiet():
        return 0
    with db.connect() as con:
        listings = due(con)
    return run(listings, stop, pause)


# Manual checks in progress: Product ids, or None for all Products. Guards against double clicks.
_running: set[int | None] = set()
_running_lock = threading.Lock()


def start_check(product_id: int | None) -> bool:
    """Claim a manual check; False when one covering the same Listings is already running."""
    with _running_lock:
        if None in _running or product_id in _running or (product_id is None and _running):
            return False
        _running.add(product_id)
        return True


def end_check(product_id: int | None) -> None:
    with _running_lock:
        _running.discard(product_id)


def check_now(product_id: int | None = None, pause: tuple[float, float] = (2, 6)) -> int:
    """Check one Product's Listings (or every Listing) now, due or not; returns how many were checked.

    A Product's Listings are on different Shops, so the pause mostly matters when checking all Products.
    May overlap with a scheduler round; each Listing check is its own transaction, so that is safe.
    """
    with db.connect() as con:
        listings = con.execute(
            "SELECT * FROM listing WHERE ? IS NULL OR product_id = ? ORDER BY product_id, shop", (product_id, product_id)
        ).fetchall()
    return run(listings, threading.Event(), pause)


def loop(stop: threading.Event) -> None:
    stop.wait(60)  # let the app settle first; also keeps --reload restarts and tests off the network
    while not stop.is_set():
        try:
            log.info("checked %d listings", run_due(stop))
        except Exception:
            log.exception("check round failed")
        stop.wait(random.uniform(300, 900))


def start() -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    thread = threading.Thread(target=loop, args=(stop,), name="scheduler", daemon=True)
    thread.start()
    return thread, stop
