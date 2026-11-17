import html as htmllib
import json
import re
from urllib.parse import quote_plus

from . import jsonld
from .base import Hit, Query, Shop

CARD = re.compile(r'data-insights-object-id="\d+"')
LINK = re.compile(r'<a href="(//www\.vandenborre\.be/[^"#]+)"[^>]*data-gtm-label="productblock name"')
TITLE = re.compile(r'<h2 class="productname[^"]*" title="([^"]+)"')
IMAGE = re.compile(r'<img[^>]+src="(//image\.vandenborre\.be/[^"]+)"')
ANALYTICS = re.compile(r'class="js-analytics-item">(\{.*?\})</script>')


def parse_search(page: str) -> list[Hit]:
    hits = []
    for card in CARD.split(page)[1:]:
        link, title = LINK.search(card), TITLE.search(card)
        if not (link and title):
            continue
        image, data = IMAGE.search(card), ANALYTICS.search(card)
        try:
            price = jsonld.to_cents(json.loads(data.group(1)).get("price")) if data else None
        except ValueError:
            price = None
        hits.append(Hit(
            url="https:" + link.group(1),
            title=htmllib.unescape(title.group(1)),
            price=price,
            image="https:" + image.group(1) if image else None,
        ))
    return hits


class Vandenborre(Shop):
    key = "vandenborre.be"

    def search(self, query: Query) -> list[Hit]:
        # Search results are rendered client-side (Algolia), so only a browser sees them.
        # An exact match redirects to the product page, which has JSON-LD.
        # Name only: EANs find nothing, and an MPN gives fuzzy matches on its digits (e.g. "910" toner).
        from . import browser
        url = f"https://www.vandenborre.be/zoekresultaat?query={quote_plus(query.name)}"
        final, page = browser.get(url, wait_until="networkidle")
        if products := jsonld.products(page):
            return [jsonld.to_hit(products[0], final)]
        return parse_search(page)[:3]
