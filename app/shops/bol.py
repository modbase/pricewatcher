import re
from urllib.parse import quote_plus

from .base import Hit, Query, Shop

BASE = "https://www.bol.com"
LINK = re.compile(r'href="(/be/nl/p/[^"]+?/(\d+)/)')


def organic_links(html: str) -> list[str]:
    """Product URLs on a search page in order, without sponsored cards."""
    first = {}
    for m in LINK.finditer(html):
        first.setdefault(m.group(2), (m.start(), m.group(1)))
    cards = sorted(first.values())
    out = []
    for i, (pos, path) in enumerate(cards):
        end = cards[i + 1][0] if i + 1 < len(cards) else len(html)
        # ponytail: the ad label sits inside the card after its first link; re-check if bol changes layout.
        if ">Gesponsord<" not in html[pos:end]:
            out.append(BASE + path)
    return out


class Bol(Shop):
    key = "bol.com"

    def search(self, query: Query) -> list[Hit]:
        final, html = self.get(f"{BASE}/be/nl/s/?searchtext={quote_plus(self.term(query))}")
        # Search results carry no JSON-LD, so each hit costs one product page fetch.
        urls = [final] if "/p/" in final else organic_links(html)[:3]
        return [h for h in (self.hit(u) for u in urls) if h]
