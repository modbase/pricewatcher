from urllib.parse import quote_plus

from . import jsonld
from .base import Hit, Query, Shop


class CustomShop(Shop):
    """A Shop added on the Settings page; works when its pages carry schema.org JSON-LD."""

    def __init__(self, key: str, search_url: str = ""):
        self.key = key
        self.search_url = search_url  # contains {query}; empty means paste product URLs only

    def search(self, query: Query) -> list[Hit]:
        if not self.search_url:
            return []
        final, html = self.get(self.search_url.replace("{query}", quote_plus(self.term(query))))
        return [jsonld.to_hit(p, final) for p in jsonld.products(html)[:3]]
