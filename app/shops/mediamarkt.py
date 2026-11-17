from urllib.parse import quote_plus

from . import jsonld
from .base import Hit, Query, Shop


class MediaMarkt(Shop):
    key = "mediamarkt.be"

    def search(self, query: Query) -> list[Hit]:
        # Search results are a JSON-LD ItemList; the product page is a ProductGroup describing that page.
        final, html = self.get(f"https://www.mediamarkt.be/nl/search.html?query={quote_plus(self.term(query))}")
        return [jsonld.to_hit(p, final) for p in jsonld.products(html)[:3]]
