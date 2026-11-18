import os
import re
from collections import defaultdict
from itertools import groupby
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import alerts, checks, db, pricing, scheduler, settings
from .pricing import eur
from .shops import BUILTIN, SHOPS
from .shops import Query as SearchQuery
from .shops.jsonld import to_cents


def when(ts) -> str:
    return f"{ts[:16]} UTC" if ts else "never"


@asynccontextmanager
async def lifespan(app):
    db.init()
    thread, stop = scheduler.start()
    yield
    stop.set()
    thread.join(timeout=35)  # a running browser check may need its page timeout to finish


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters.update(eur=eur, when=when)
templates.env.globals.update(is_stale=pricing.is_stale, total=pricing.total)


def price_changes():
    with db.connect() as con:
        return con.execute(
            "SELECT c.*, l.shop, l.product_id, p.name FROM price_change c JOIN listing l ON l.id = c.listing_id"
            " JOIN product p ON p.id = l.product_id ORDER BY c.id DESC LIMIT 50"
        ).fetchall()


templates.env.globals["price_changes"] = price_changes  # the bell in base.html on every page


@app.post("/changes/delete")
def delete_changes(request: Request, id: Annotated[int | None, Form()] = None):
    with db.connect() as con:  # no id clears them all
        con.execute("DELETE FROM price_change WHERE ? IS NULL OR id = ?", (id, id))
    return RedirectResponse(request.headers.get("referer", "/"), status_code=303)


@app.get("/")
def overview(request: Request, checking: bool = False):
    with db.connect() as con:
        products = con.execute("SELECT * FROM product ORDER BY position IS NULL, position, name").fetchall()
        by_product = defaultdict(list)
        for l in con.execute("SELECT * FROM listing"):
            by_product[l["product_id"]].append(l)

    rows, archived = [], []
    for p in products:
        listings = by_product[p["id"]]
        r = pricing.ranked(listings)
        (archived if p["archived_at"] else rows).append({
            "product": p,
            "best": r[0] if r else None,
            "best_total": pricing.total(r[0]) if r else None,
            "spread": pricing.total(r[1]) - pricing.total(r[0]) if len(r) > 1 else None,
            "stale": sum(pricing.is_stale(l) for l in listings),
            "count": len(listings),
            "last_checked": max((l["last_checked"] for l in listings if l["last_checked"]), default=None),
        })
    sort = settings.current["sort"]
    if sort == "name":
        rows.sort(key=lambda r: r["product"]["name"].casefold())
    elif sort == "price":  # no in-stock offer last
        rows.sort(key=lambda r: (r["best"] is None, r["best_total"] or 0))
    elif sort == "shop":  # grouped by Cheapest Shop, cheapest first within a shop
        rows.sort(key=lambda r: (r["best"] is None, r["best"]["shop"] if r["best"] else "", r["best_total"] or 0))
    group_pos = {g: i for i, g in enumerate(settings.current["group_order"])}

    def group_key(r):  # ungrouped first, then the dragged Group order, then Groups not in it by name
        g = r["product"]["grp"]
        return (0,) if g is None else (1, group_pos.get(g, len(group_pos)), g.casefold())

    archived.sort(key=lambda r: r["product"]["archived_at"], reverse=True)  # most recently Archived first
    rows.sort(key=group_key)  # stable: keeps the sort within a Group
    groups = [(g, list(rs)) for g, rs in groupby(rows, key=lambda r: r["product"]["grp"])]
    return templates.TemplateResponse(request, "overview.html", {
        "rows": rows, "groups": groups, "archived": archived, "checking": checking, "sort": sort, "sorts": settings.SORTS,
    })


@app.post("/sort")
def save_sort(sort: Annotated[str, Form()]):
    try:
        with db.connect() as con:
            settings.save(con, {**settings.current, "sort": sort})
    except ValueError as e:
        raise HTTPException(422, str(e))
    return RedirectResponse("/", status_code=303)


@app.post("/order")
def save_order(
    ids: Annotated[list[int], Form()],
    moved: Annotated[int | None, Form()] = None,
    grp: Annotated[str, Form()] = "",
):
    """Manual order from drag and drop: the product ids top to bottom, and the Group a dragged product landed in."""
    with db.connect() as con:
        con.executemany("UPDATE product SET position = ? WHERE id = ?", list(enumerate(ids)))
        if moved is not None:
            con.execute("UPDATE product SET grp = ? WHERE id = ?", (grp.strip() or None, moved))
        settings.save(con, {**settings.current, "sort": "manual"})
    return Response(status_code=204)


@app.post("/group-order")
def save_group_order(names: Annotated[list[str], Form()]):
    """Group order from drag and drop: the Group names top to bottom."""
    with db.connect() as con:
        settings.save(con, {**settings.current, "group_order": names})
    return Response(status_code=204)


def get_product(con, product_id: int):
    p = con.execute("SELECT * FROM product WHERE id = ?", (product_id,)).fetchone()
    if p is None:
        raise HTTPException(404, "Product not found")
    return p


@app.get("/products/new")
def new_product(request: Request):
    return templates.TemplateResponse(request, "new.html", {"shops": list(SHOPS)})


@app.post("/products")
def create_product(
    name: Annotated[str, Form()],
    ean: Annotated[str, Form()] = "",
    mpn: Annotated[str, Form()] = "",
    asin: Annotated[str, Form()] = "",
    shop: Annotated[list[str], Form()] = [],
):
    if not name.strip():
        raise HTTPException(422, "Name is required")
    with db.connect() as con:
        pid = con.execute(
            "INSERT INTO product (name, ean, mpn, asin) VALUES (?, ?, ?, ?)",
            (name.strip(), ean.strip() or None, mpn.strip() or None, asin.strip() or None),
        ).lastrowid
    qs = "&".join(f"shop={s}" for s in shop if s in SHOPS)
    return RedirectResponse(f"/products/{pid}/match?{qs}", status_code=303)


@app.get("/products/{product_id}/match")
def match_page(request: Request, product_id: int, shop: Annotated[list[str], Query()] = []):
    with db.connect() as con:
        p = get_product(con, product_id)
        listed = {r["shop"] for r in con.execute("SELECT shop FROM listing WHERE product_id = ?", (product_id,))}
    shops = [s for s in shop if s in SHOPS] or [s for s in SHOPS if s not in listed]
    return templates.TemplateResponse(request, "match.html", {"product": p, "shops": shops})


def code_match(product, hit) -> bool:
    return bool((product["ean"] and hit.ean == product["ean"]) or (product["asin"] and hit.asin == product["asin"]))


def name_match(name: str, title: str) -> bool:
    """Every word of the name appears in the title, ignoring case and spacing ("UGT 3000" ~ "UGT3000")."""
    flat = re.sub(r"\W", "", title.lower())
    return all(w in flat for w in re.findall(r"\w+", name.lower()))


templates.env.globals["code_match"] = code_match


@app.get("/products/{product_id}/match/{shop}")
def match_shop(request: Request, product_id: int, shop: str):
    if shop not in SHOPS:
        raise HTTPException(404, "Unknown shop")
    with db.connect() as con:
        p = get_product(con, product_id)
    hits, error = [], None
    try:
        hits = SHOPS[shop].search(SearchQuery(p["name"], p["ean"], p["mpn"], p["asin"]))
    except Exception as e:  # shown to the user, who can still paste a URL
        error = f"{type(e).__name__}: {e}"
    if not (p["ean"] or p["mpn"]):  # a name search: shops return their nearest products even when they don't carry it
        hits = [h for h in hits if code_match(p, h) or name_match(p["name"], h.title)]
    hits.sort(key=lambda h: not code_match(p, h))  # EAN/ASIN match first
    no_search = getattr(SHOPS[shop], "search_url", None) == ""  # a custom Shop added without a search URL
    return templates.TemplateResponse(
        request, "_match_shop.html", {"product": p, "shop": shop, "hits": hits, "error": error, "no_search": no_search}
    )


@app.post("/products/{product_id}/listings")
def save_listing(
    request: Request,
    tasks: BackgroundTasks,
    product_id: int,
    shop: Annotated[str, Form()],
    url: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    image: Annotated[str, Form()] = "",
):
    adapter = SHOPS.get(shop)
    url = url.strip()
    ctx = {"product_id": product_id, "shop": shop, "url": url}
    if adapter is None or not adapter.owns(url):
        return templates.TemplateResponse(request, "_matched.html", ctx | {"error": f"Not a {shop} URL"})
    if not title:  # pasted URL: read title and image from the page
        try:
            hit = adapter.hit(url)
        except Exception as e:
            hit, ctx["error"] = None, f"{type(e).__name__}: {e}"
        if hit is None:
            ctx.setdefault("error", "No product found on that page")
            return templates.TemplateResponse(request, "_matched.html", ctx)
        url, title, image = hit.url, hit.title, hit.image or ""

    with db.connect() as con:
        get_product(con, product_id)
        # Re-Match replaces the Listing; its old checks go with it (they belong to another page).
        con.execute("DELETE FROM listing WHERE product_id = ? AND shop = ?", (product_id, shop))
        lid = con.execute(
            "INSERT INTO listing (product_id, shop, url, title) VALUES (?, ?, ?, ?)", (product_id, shop, url, title)
        ).lastrowid
        if image:
            con.execute("UPDATE product SET image_url = ? WHERE id = ? AND image_url IS NULL", (image, product_id))
    tasks.add_task(first_check, lid, url)  # a browser fetch takes seconds: don't make Pick wait for it
    return templates.TemplateResponse(request, "_matched.html", ctx | {"url": url, "title": title})


def first_check(listing_id: int, url: str) -> None:
    with db.connect() as con:
        listing = con.execute("SELECT * FROM listing WHERE id = ?", (listing_id,)).fetchone()
    if listing:
        result = checks.fetch(listing)
        with db.connect() as con:
            checks.record_if_current(con, listing_id, url, result)


def check_now(product_id: int | None) -> None:
    """Background task for the Check now buttons; a click while the same check runs is ignored."""
    if not scheduler.start_check(product_id):
        return
    try:
        scheduler.check_now(product_id)
    finally:
        scheduler.end_check(product_id)


@app.post("/check")
def check_all(tasks: BackgroundTasks):
    tasks.add_task(check_now, None)
    return RedirectResponse("/?checking=1", status_code=303)


@app.post("/products/{product_id}/check")
def check_product(tasks: BackgroundTasks, product_id: int):
    with db.connect() as con:
        get_product(con, product_id)
    tasks.add_task(check_now, product_id)
    return RedirectResponse(f"/products/{product_id}?checking=1", status_code=303)


@app.get("/settings")
def settings_page(request: Request, saved: bool = False, telegram: str = "", shop_error: str = ""):
    with db.connect() as con:
        group_names = [g for (g,) in con.execute("SELECT DISTINCT grp FROM product WHERE grp IS NOT NULL ORDER BY grp")]
    return templates.TemplateResponse(request, "settings.html", {
        "s": settings.current,
        "group_names": group_names,
        "shop_error": shop_error,
        "builtin_shops": list(BUILTIN),
        "tz": settings.TZ.key,
        "intervals": settings.INTERVALS,
        "saved": saved,
        "telegram": telegram,
        "telegram_configured": all(alerts.telegram()),
        "env_token": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "env_chat": bool(os.environ.get("TELEGRAM_CHAT_ID")),
    })


def hour(value: str) -> int | None:
    return int(value) if value.strip() else None


@app.post("/settings")
def save_settings(
    interval_hours: Annotated[int, Form()],
    stale_after: Annotated[int, Form()],
    low_min_drop_pct: Annotated[int, Form()],
    low_alerts: Annotated[bool, Form()] = False,  # an unchecked box is not sent
    quiet_from: Annotated[str, Form()] = "",
    quiet_until: Annotated[str, Form()] = "",
):
    values = {
        **settings.current,
        "interval_hours": interval_hours, "stale_after": stale_after, "low_alerts": low_alerts,
        "low_min_drop_pct": low_min_drop_pct, "quiet_from": hour(quiet_from), "quiet_until": hour(quiet_until),
    }
    try:
        with db.connect() as con:
            settings.save(con, values)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/telegram")
def save_telegram(
    chat_id: Annotated[str, Form()] = "",
    token: Annotated[str, Form()] = "",  # empty keeps the saved token: the page never shows it
    clear: Annotated[bool, Form()] = False,
):
    values = {**settings.current, "telegram_chat_id": chat_id}
    if token.strip() or clear:
        values["telegram_token"] = token
    if clear:
        values.update(telegram_token="", telegram_chat_id="")
    with db.connect() as con:
        settings.save(con, values)
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/shops")
def save_shop(domain: Annotated[str, Form()], search_url: Annotated[str, Form()] = ""):
    """Adds a custom Shop, or changes its search URL when the domain is already there."""
    try:
        shop = settings.custom_shop({"domain": domain, "search_url": search_url})
        custom = [c for c in settings.current["custom_shops"] if c["domain"] != shop["domain"]] + [shop]
        with db.connect() as con:
            settings.save(con, {**settings.current, "custom_shops": custom})
    except ValueError as e:
        return RedirectResponse(f"/settings?{urlencode({'shop_error': str(e)})}#shops", status_code=303)
    return RedirectResponse("/settings?saved=1#shops", status_code=303)


@app.post("/settings/shops/delete")
def delete_shop(domain: Annotated[str, Form()]):
    custom = [c for c in settings.current["custom_shops"] if c["domain"] != domain]
    with db.connect() as con:
        settings.save(con, {**settings.current, "custom_shops": custom})
    return RedirectResponse("/settings?saved=1#shops", status_code=303)


@app.post("/settings/groups")
def rename_group(old: Annotated[str, Form()], new: Annotated[str, Form()] = ""):
    """Renames a Group; an existing name merges the two, an empty name ungroups its products."""
    new = new.strip() or None
    order = [new if g == old else g for g in settings.current["group_order"] if new or g != old]
    with db.connect() as con:
        con.execute("UPDATE product SET grp = ? WHERE grp = ?", (new, old))
        settings.save(con, {**settings.current, "group_order": list(dict.fromkeys(order))})  # a merge keeps one entry
    return RedirectResponse("/settings?saved=1#groups", status_code=303)


@app.post("/settings/telegram-test")
def telegram_test():
    sent = alerts.send("Pricewatcher test message: alerts reach this chat.")
    return RedirectResponse(f"/settings?telegram={'sent' if sent else 'failed'}", status_code=303)


@app.post("/products/{product_id}/edit")
def edit_product(
    product_id: int,
    name: Annotated[str, Form()],
    ean: Annotated[str, Form()] = "",
    mpn: Annotated[str, Form()] = "",
    asin: Annotated[str, Form()] = "",
    grp: Annotated[str, Form()] = "",
):
    if not name.strip():
        raise HTTPException(422, "Name is required")
    with db.connect() as con:
        get_product(con, product_id)
        con.execute(
            "UPDATE product SET name = ?, ean = ?, mpn = ?, asin = ?, grp = ? WHERE id = ?",
            (name.strip(), ean.strip() or None, mpn.strip() or None, asin.strip() or None, grp.strip() or None,
             product_id),
        )
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/target")
def set_target(product_id: int, target: Annotated[str, Form()] = ""):
    cents = to_cents(target) if target.strip() else None  # empty clears the Target Price
    if target.strip() and not cents:
        raise HTTPException(422, "Not a price")
    with db.connect() as con:
        get_product(con, product_id)
        con.execute("UPDATE product SET target_price = ? WHERE id = ?", (cents, product_id))
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/listings/{listing_id}/delete")
def delete_listing(product_id: int, listing_id: int):
    with db.connect() as con:
        con.execute("DELETE FROM listing WHERE id = ? AND product_id = ?", (listing_id, product_id))
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/archive")
def archive_product(product_id: int):
    """Archived Products leave the overview and are no longer checked; their Listings and history stay."""
    with db.connect() as con:
        get_product(con, product_id)
        con.execute(
            "UPDATE product SET archived_at = coalesce(archived_at, datetime('now')) WHERE id = ?", (product_id,)
        )
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/unarchive")
def unarchive_product(product_id: int, next: Annotated[str, Form()] = ""):
    with db.connect() as con:
        get_product(con, product_id)
        con.execute("UPDATE product SET archived_at = NULL WHERE id = ?", (product_id,))
    return RedirectResponse("/" if next == "/" else f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/delete")
def delete_product(product_id: int):
    with db.connect() as con:
        con.execute("DELETE FROM product WHERE id = ?", (product_id,))
    return RedirectResponse("/", status_code=303)


@app.get("/products/{product_id}")
def product(request: Request, product_id: int, checking: bool = False):
    with db.connect() as con:
        p = get_product(con, product_id)
        listings = con.execute(
            "SELECT * FROM listing WHERE product_id = ? ORDER BY shop", (product_id,)
        ).fetchall()
        points = con.execute(
            "SELECT l.shop, c.checked_at, c.price + coalesce(c.shipping, 0) AS total FROM price_check c"
            " JOIN listing l ON l.id = c.listing_id"
            " WHERE l.product_id = ? AND c.ok AND c.price IS NOT NULL ORDER BY c.checked_at",
            (product_id,),
        ).fetchall()
        group_names = [g for (g,) in con.execute("SELECT DISTINCT grp FROM product WHERE grp IS NOT NULL ORDER BY grp")]

    history = defaultdict(list)  # shop -> [{x: epoch ms (UTC), y: euros}], same total as the table
    for c in points:
        ms = datetime.strptime(c["checked_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp() * 1000
        history[c["shop"]].append({"x": ms, "y": c["total"] / 100})

    r = pricing.ranked(listings)
    ids = {l["id"] for l in r}
    return templates.TemplateResponse(request, "product.html", {
        "product": p,
        "listings": r + [l for l in listings if l["id"] not in ids],
        "best_id": r[0]["id"] if r else None,
        "history": history,
        "checking": checking,
        "group_names": group_names,
    })
