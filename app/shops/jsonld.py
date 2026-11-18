"""schema.org Product/Offer data from <script type="application/ld+json"> blocks."""
import json
import re

from . import base

SCRIPT = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
CANONICAL = re.compile(r'<link[^>]*rel="canonical"[^>]*href="([^"]+)"')
IN_STOCK = ("InStock", "LimitedAvailability", "OnlineOnly")


def to_cents(value) -> int | None:
    """72.9, "72.90", "1.299,99", "€ 49,-", "49,99 €" -> cents."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(value * 100)
    s = re.sub(r"[,.]-+", "", str(value))  # "49,-" means 49,00
    s = re.sub(r"[^\d,.]", "", s)
    if not re.search(r"\d", s):
        return None
    m = re.search(r"[,.](\d{1,2})$", s)  # last separator with 1-2 digits is the decimal one
    whole, frac = (s[:m.start()], m.group(1).ljust(2, "0")) if m else (s, "00")
    return int(re.sub(r"[,.]", "", whole) or 0) * 100 + int(frac)


def _walk(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        yield from _walk(node.get("@graph", []))
        yield from _walk(node.get("object", []))  # MediaMarkt: BuyAction -> ProductGroup
        for el in node.get("itemListElement", []):
            yield from _walk(el.get("item", el) if isinstance(el, dict) else el)


def _variant(group: dict, canonical: str | None) -> dict:
    """The variant this page is about (bol: a ProductGroup of sizes/colours), else the group itself."""
    for v in group.get("hasVariant") or []:
        if canonical and isinstance(v, dict) and str(v.get("url", "")).rstrip("/") == canonical.rstrip("/"):
            return v
    return group


def products(html: str) -> list[dict]:
    m = CANONICAL.search(html)
    canonical = m.group(1) if m else None
    out = []
    for m in SCRIPT.finditer(html):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in _walk(data):
            t = node.get("@type")
            if t in ("Product", "ProductGroup") or (isinstance(t, list) and "Product" in t):
                out.append(_variant(node, canonical))
    return out


def _first(v):
    return (v[0] if v else None) if isinstance(v, list) else v


def _image(product) -> str | None:
    img = _first(product.get("image"))
    return img.get("url") if isinstance(img, dict) else img


def _ean(product) -> str | None:
    v = product.get("gtin13") or product.get("gtin") or product.get("ean") or product.get("gtin8")  # Alternate puts the EAN in gtin8
    return str(v) if v else None


def to_offer(product: dict) -> "base.Offer | base.FetchError":
    o = _first(product.get("offers"))
    if not isinstance(o, dict):
        return base.FetchError("no offer in JSON-LD")
    if o.get("priceCurrency", "EUR") != "EUR":
        return base.FetchError(f"currency {o.get('priceCurrency')}")
    price = to_cents(o.get("price", o.get("lowPrice")))
    if price is None:
        return base.FetchError("no price in JSON-LD")
    # ponytail: takes the first shipping rate; split per destination if a Shop lists several.
    rate = (_first(o.get("shippingDetails")) or {}).get("shippingRate")
    shipping = to_cents(_first(rate).get("value")) if isinstance(_first(rate), dict) else None
    # Missing availability counts as out of stock, so it never wins Cheapest Shop by accident.
    in_stock = any(s in str(o.get("availability", "")) for s in IN_STOCK)
    return base.Offer(price, shipping, in_stock, _ean(product))


def parse_offer(html: str) -> "base.Offer | base.FetchError":
    found = products(html)
    return to_offer(found[0]) if found else base.FetchError("no Product JSON-LD")


def to_hit(product: dict, url: str) -> "base.Hit":
    offer = to_offer(product)
    return base.Hit(
        url=product.get("url") or url,
        title=product.get("name") or url,
        price=offer.price if isinstance(offer, base.Offer) else None,
        image=_image(product),
        ean=_ean(product),
    )
