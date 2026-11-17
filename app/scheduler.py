"""Background checker: rechecks every Listing about every 6h, one at a time.

Runs in one thread inside the web process, so uvicorn must run with exactly 1 worker.
A thread (not an asyncio task) because Playwright's sync API cannot run on the event loop thread.
"""
import logging
import random
import threading
from datetime import UTC, datetime, timedelta

from . import checks, db

INTERVAL = timedelta(hours=6)
log = logging.getLogger(__name__)


def due(con) -> list:
    cutoff = (datetime.now(UTC) - INTERVAL).strftime("%Y-%m-%d %H:%M:%S")
    return con.execute(
        "SELECT * FROM listing WHERE last_checked IS NULL OR last_checked <= ? ORDER BY last_checked", (cutoff,)
    ).fetchall()


def run_due(stop: threading.Event, pause: tuple[float, float] = (10, 40)) -> int:
    """Check every due Listing; returns how many were checked."""
    with db.connect() as con:
        listings = due(con)
    done = 0
    for l in listings:
        if stop.is_set():
            break
        result = checks.fetch(l)  # network, outside any transaction
        with db.connect() as con:
            # Skip if the Listing was deleted or re-Matched while we were fetching.
            if con.execute("SELECT 1 FROM listing WHERE id = ? AND url = ?", (l["id"], l["url"])).fetchone():
                checks.record(con, l["id"], result)
                done += 1
        stop.wait(random.uniform(*pause))  # jitter, and no hammering of one Shop
    return done


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
