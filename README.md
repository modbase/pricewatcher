# Pricewatcher

One row per Product with its Cheapest Shop; click through for every Shop's price and history.
Design and decisions: `PLAN.md`. Terms: `GLOSSARY.md`.

Shops: amazon.nl, amazon.com.be, bol.com, coolblue.be, mediamarkt.be, vandenborre.be, alternate.be.

## Run locally

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # .venv/bin/pip on Linux
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The database is `data/pricewatcher.db` (override with `PRICEWATCHER_DB`).

Tests: `.venv/Scripts/python -m pytest -q` (no network; Shop pages are saved fixtures).

Prices are rechecked once per check interval (6 hours unless changed on the Settings page). To check right away, use **Check now** on a Product's page
or **Check all now** on the overview; the check runs in the background, so reload the page after a minute.

## Telegram alerts

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (in Docker: a `.env` file next to `docker-compose.yml`).
Without them, alerts are only logged. The Settings page can send a test message.

## Settings

The Settings page (top right) sets the check interval, quiet hours without scheduled checks (Belgian time),
how many failed checks make a Listing stale, and whether and when all-time-low alerts fire. They are stored in the
database, so they survive restarts and come along when you copy the database.

## Deploy (Docker)

```sh
docker compose up -d --build
```

The app listens on port 8000 and stores everything in `./data/pricewatcher.db`. Run exactly one container:
price checks run inside the app process.

### Keep your existing Products

Copy your local database into `./data` on the server **before the first start**. Take the copy with
SQLite's backup API, which is safe while the local app is running:

```sh
.venv/Scripts/python -c "import sqlite3; d = sqlite3.connect('pricewatcher-backup.db'); sqlite3.connect('data/pricewatcher.db').backup(d); d.close()"
scp pricewatcher-backup.db <server>:<app dir>/data/pricewatcher.db
```

The app only creates missing tables on start, so it keeps the Products, Shops and price history in that file.
Stop the local app afterwards, or both will check the same Shops.
