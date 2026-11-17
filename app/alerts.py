"""Telegram alerts on the Cheapest price: below Target Price or a new all-time low, see PLAN.md."""
import json
import logging
import os
from urllib.request import Request, urlopen

from . import pricing

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
    if not (below_target or price < low):
        return None
    if p["last_alert_price"] is not None and price >= p["last_alert_price"]:
        return None  # already alerted at this price or lower
    con.execute("UPDATE product SET last_alert_price = ? WHERE id = ?", (price, product_id))
    reason = f"below target {pricing.eur(p['target_price'])}" if below_target else "new all-time low"
    return f"{p['name']}: {pricing.eur(price)} at {best['shop']} ({reason})\n{best['url']}"


def send(text: str) -> None:
    # ponytail: a failed send is logged, not retried; that alert is lost (last_alert_price is already set).
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        log.warning("Telegram not configured, alert not sent: %s", text)
        return
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    req = Request(f"https://api.telegram.org/bot{token}/sendMessage", body, {"Content-Type": "application/json"})
    try:
        urlopen(req, timeout=15).close()
    except Exception as e:  # never log the URL: it holds the token
        log.error("Telegram send failed: %s: %s", type(e).__name__, getattr(e, "code", ""))
