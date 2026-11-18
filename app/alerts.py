"""Telegram alerts on the Cheapest price: below Target Price or a new all-time low, see PLAN.md."""
import json
import logging
import os
from urllib.request import Request, urlopen

from . import pricing, settings

log = logging.getLogger(__name__)


def evaluate(con, product_id: int, check_id: int) -> str | None:
    """Alert text when the Cheapest price triggers an alert (and marks it alerted), else None.

    Call right after checks.record, in the same transaction; check_id is the check just recorded.
    """
    p = con.execute("SELECT * FROM product WHERE id = ?", (product_id,)).fetchone()
    r = pricing.ranked(con.execute("SELECT * FROM listing WHERE product_id = ?", (product_id,)).fetchall())
    if p is None or not r:
        return None
    best, price = r[0], pricing.total(r[0])
    # The lowest earlier in-stock total of any Shop is the lowest Cheapest price recorded before.
    (low,) = con.execute(
        "SELECT MIN(c.price + COALESCE(c.shipping, 0)) FROM price_check c JOIN listing l ON l.id = c.listing_id"
        " WHERE l.product_id = ? AND c.ok AND c.in_stock AND c.price IS NOT NULL AND c.id < ?",
        (product_id, check_id),
    ).fetchone()
    if low is None:  # the Product's first successful check
        return None
    below_target = p["target_price"] is not None and price < p["target_price"]
    s = settings.current
    new_low = s["low_alerts"] and price < low and (low - price) * 100 >= s["low_min_drop_pct"] * low
    if not (below_target or new_low):
        return None
    if p["last_alert_price"] is not None and price >= p["last_alert_price"]:
        return None  # already alerted at this price or lower
    con.execute("UPDATE product SET last_alert_price = ? WHERE id = ?", (price, product_id))
    reason = f"below target {pricing.eur(p['target_price'])}" if below_target else "new all-time low"
    return f"{p['name']}: {pricing.eur(price)} at {best['shop']} ({reason})\n{best['url']}"


def telegram() -> tuple[str, str]:
    """Bot token and chat id; each env var overrides its value from the Settings page."""
    s = settings.current
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or s["telegram_token"],
            os.environ.get("TELEGRAM_CHAT_ID") or s["telegram_chat_id"])


def send(text: str) -> bool:
    """Send to Telegram; False when not configured or the send failed."""
    # ponytail: a failed send is logged, not retried; that alert is lost (last_alert_price is already set).
    token, chat = telegram()
    if not (token and chat):
        log.warning("Telegram not configured, alert not sent: %s", text)
        return False
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    req = Request(f"https://api.telegram.org/bot{token}/sendMessage", body, {"Content-Type": "application/json"})
    try:
        urlopen(req, timeout=15).close()
        return True
    except Exception as e:  # never log the URL: it holds the token
        log.error("Telegram send failed: %s: %s", type(e).__name__, getattr(e, "code", ""))
        return False
