from urllib.parse import quote_plus

from . import jsonld
from .base import Hit, Query, Shop


class Coolblue(Shop):
    key = "coolblue.be"

    def search(self, query: Query) -> list[Hit]:
        # The search page lists its results as a JSON-LD ItemList; an exact hit may land on the product page.
        final, html = self.get(f"https://www.coolblue.be/nl/zoeken?query={quote_plus(self.term(query))}")
        return [jsonld.to_hit(p, final) for p in jsonld.products(html)[:3]]
