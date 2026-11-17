"""Amazon: no JSON-LD and plain HTTP is blocked, so a browser plus page selectors."""
import html as htmllib
import re
from urllib.parse import quote_plus

from .base import FetchError, Hit, Offer, Query, Shop
from .jsonld import to_cents

CARD = re.compile(r'<div[^>]*data-component-type="s-search-result"[^>]*>')
FREE = ("GRATIS", "KOSTENLOS", "FREE", "GRATUITE")


def _text(s: str) -> str:
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def _find(pattern: str, s: str) -> str | None:
    m = re.search(pattern, s, re.S)
    return m.group(1) if m else None


def parse_product(html: str) -> Offer | FetchError:
    if "validateCaptcha" in html:
        return FetchError("captcha")
    # Only the buy box price: other prices on the page belong to other sellers or other products.
    box = _find(r'priceToPay apex-pricetopay-value"(.{0,800})', html) or ""
    whole, frac = _find(r'a-price-whole">([\d.,\s]+)<', box), _find(r'a-price-fraction">(\d+)<', box)
    price = to_cents(f"{re.sub(r'[^0-9]', '', whole)},{frac or '00'}") if whole else None
    in_stock = 'id="add-to-cart-button"' in html and 'id="outOfStock' not in html
    if price is None:
        return Offer(None, None, False) if not in_stock else FetchError("no buy box price")
    fee = _find(r'data-csa-c-delivery-price="([^"]*)"', html)
    shipping = 0 if fee and fee.strip().upper() in FREE else to_cents(fee) if fee else None
    return Offer(price, shipping, in_stock)


def parse_search(html: str, domain: str) -> list[Hit]:
    starts = list(CARD.finditer(html))
    hits, seen = [], set()
    for i, m in enumerate(starts):
        card = html[m.start(): starts[i + 1].start() if i + 1 < len(starts) else m.start() + 40000]
        asin = _find(r'data-asin="(\w+)"', m.group(0))
        if not asin or asin in seen or "AdHolder" in m.group(0) or re.search(r"Gesponsor|Sponsored", card):
            continue
        seen.add(asin)
        hits.append(Hit(
            url=f"https://www.{domain}/dp/{asin}",
            title=_text(_find(r"<h2[^>]*>(.*?)</h2>", card) or asin),
            price=to_cents(_find(r'class="a-price"[^>]*>\s*<span class="a-offscreen">([^<]+)<', card)),
            image=_find(r'<img[^>]*class="s-image"[^>]*src="([^"]+)"', card)
            or _find(r'<img[^>]*src="([^"]+)"[^>]*class="s-image"', card),
            asin=asin,
        ))
        if len(hits) == 3:
            break
    return hits


class Amazon(Shop):
    needs_browser = True

    def __init__(self, domain: str):
        self.key = domain

    def search(self, query: Query) -> list[Hit]:
        if query.asin:
            hit = self.hit(f"https://www.{self.key}/dp/{query.asin}")
            return [hit] if hit else []
        # Amazon often finds nothing for an EAN, so fall back to the next term.
        for term in dict.fromkeys(t for t in (query.ean, query.mpn, query.name) if t):
            _, html = self.get(f"https://www.{self.key}/s?k={quote_plus(term)}")
            if hits := parse_search(html, self.key):
                return hits
        return []

    def hit(self, url: str) -> Hit | None:
        final, html = self.get(url)
        title = _find(r'id="productTitle"[^>]*>(.*?)</span>', html)
        if not title:
            return None
        offer = parse_product(html)
        return Hit(
            url=final.split("?")[0],
            title=_text(title),
            price=offer.price if isinstance(offer, Offer) else None,
            image=_find(r'data-old-hires="([^"]+)"', html),
            asin=_find(r"/dp/(\w{10})", final),
        )

    def parse(self, html: str) -> Offer | FetchError:
        return parse_product(html)
