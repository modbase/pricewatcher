from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import checks, db, pricing
from .shops import SHOPS, Offer
from .shops import Query as SearchQuery


def eur(cents) -> str:
    if cents is None:
        return "-"
    euros, rest = divmod(cents, 100)
    return f"€ {euros:,}".replace(",", ".") + f",{rest:02d}"


def when(ts) -> str:
    return f"{ts[:16]} UTC" if ts else "never"


@asynccontextmanager
async def lifespan(app):
    db.init()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters.update(eur=eur, when=when)
templates.env.globals.update(is_stale=pricing.is_stale, total=pricing.total)


@app.get("/")
def overview(request: Request):
    with db.connect() as con:
        products = con.execute("SELECT * FROM product ORDER BY name").fetchall()
        by_product = defaultdict(list)
        for l in con.execute("SELECT * FROM listing"):
            by_product[l["product_id"]].append(l)

    rows = []
    for p in products:
        listings = by_product[p["id"]]
        r = pricing.ranked(listings)
        rows.append({
            "product": p,
            "best": r[0] if r else None,
            "best_total": pricing.total(r[0]) if r else None,
            "spread": pricing.total(r[1]) - pricing.total(r[0]) if len(r) > 1 else None,
            "stale": sum(pricing.is_stale(l) for l in listings),
            "count": len(listings),
            "last_checked": max((l["last_checked"] for l in listings if l["last_checked"]), default=None),
        })
    return templates.TemplateResponse(request, "overview.html", {"rows": rows})


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
    hits.sort(key=lambda h: not code_match(p, h))  # EAN/ASIN match first
    return templates.TemplateResponse(
        request, "_match_shop.html", {"product": p, "shop": shop, "hits": hits, "error": error}
    )


@app.post("/products/{product_id}/listings")
def save_listing(
    request: Request,
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

    result = adapter.fetch(url)
    with db.connect() as con:
        get_product(con, product_id)
        # Re-Match replaces the Listing; its old checks go with it (they belong to another page).
        con.execute("DELETE FROM listing WHERE product_id = ? AND shop = ?", (product_id, shop))
        lid = con.execute(
            "INSERT INTO listing (product_id, shop, url, title) VALUES (?, ?, ?, ?)", (product_id, shop, url, title)
        ).lastrowid
        checks.record(con, lid, result)
        if image:
            con.execute("UPDATE product SET image_url = ? WHERE id = ? AND image_url IS NULL", (image, product_id))
    return templates.TemplateResponse(
        request, "_matched.html", ctx | {"url": url, "title": title, "offer": result if isinstance(result, Offer) else None,
                                         "error": None if isinstance(result, Offer) else result.reason},
    )


@app.post("/products/{product_id}/delete")
def delete_product(product_id: int):
    with db.connect() as con:
        con.execute("DELETE FROM product WHERE id = ?", (product_id,))
    return RedirectResponse("/", status_code=303)


@app.get("/products/{product_id}")
def product(request: Request, product_id: int):
    with db.connect() as con:
        p = get_product(con, product_id)
        listings = con.execute(
            "SELECT * FROM listing WHERE product_id = ? ORDER BY shop", (product_id,)
        ).fetchall()

    r = pricing.ranked(listings)
    ids = {l["id"] for l in r}
    return templates.TemplateResponse(request, "product.html", {
        "product": p,
        "listings": r + [l for l in listings if l["id"] not in ids],
        "best_id": r[0]["id"] if r else None,
    })
