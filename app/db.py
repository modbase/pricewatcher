import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import settings

# All amounts are integer euro cents.
SCHEMA = """
CREATE TABLE IF NOT EXISTS product (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    ean              TEXT,
    mpn              TEXT,
    asin             TEXT,
    image_url        TEXT,
    target_price     INTEGER,
    last_alert_price INTEGER,
    position         INTEGER,  -- manual order on the overview; NULL sorts last
    grp              TEXT,     -- Group on the overview; NULL means ungrouped
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS listing (
    id            INTEGER PRIMARY KEY,
    product_id    INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    shop          TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    fail_count    INTEGER NOT NULL DEFAULT 0,
    last_price    INTEGER,
    last_in_stock INTEGER,
    last_shipping INTEGER,
    last_checked  TEXT,
    UNIQUE (product_id, shop)
);
CREATE TABLE IF NOT EXISTS price_check (
    id         INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listing(id) ON DELETE CASCADE,
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    price      INTEGER,
    shipping   INTEGER,
    in_stock   INTEGER,
    ok         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS price_check_listing ON price_check (listing_id, checked_at);
CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL  -- JSON
);
"""


def path() -> Path:
    p = Path(os.environ.get("PRICEWATCHER_DB", "data/pricewatcher.db"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def connect():
    con = sqlite3.connect(path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        with con:  # commit on success, roll back on error
            yield con
    finally:
        con.close()


def init():
    with connect() as con:
        con.executescript(SCHEMA)
        cols = {c["name"] for c in con.execute("PRAGMA table_info(product)")}
        for col, type_ in [("position", "INTEGER"), ("grp", "TEXT")]:  # databases made before these columns
            if col not in cols:
                con.execute(f"ALTER TABLE product ADD COLUMN {col} {type_}")
        settings.load(con)
