from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates

from . import db, pricing


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


@app.get("/products/{product_id}")
def product(request: Request, product_id: int):
    with db.connect() as con:
        p = con.execute("SELECT * FROM product WHERE id = ?", (product_id,)).fetchone()
        if p is None:
            raise HTTPException(404, "Product not found")
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
