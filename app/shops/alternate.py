import html as htmllib
import re
from urllib.parse import quote_plus

from . import jsonld
from .base import Hit, Query, Shop

CARD = re.compile(r'<a href="(/[^"]+/html/product/\d+)" class="card[^"]*productBox')
NAME = re.compile(r'<div class="product-name[^"]*">(.*?)</div>', re.S)
IMAGE = re.compile(r'<img src="(/p/[^"]+)"[^>]*class="productPicture')
PRICE = re.compile(r'<span class="price[^"]*">([^<]+)</span>')


def parse_search(page: str) -> list[Hit]:
    parts = CARD.split(page)  # [before, url1, card1, url2, card2, ...]
    hits = []
    for path, card in zip(parts[1::2], parts[2::2]):
        name, image, price = NAME.search(card), IMAGE.search(card), PRICE.search(card)
        hits.append(Hit(
            url="https://www.alternate.be" + path,
            title=htmllib.unescape(re.sub(r"<[^>]+>", "", name.group(1))).strip() if name else path,
            price=jsonld.to_cents(htmllib.unescape(price.group(1)).replace("\xa0", " ")) if price else None,
            image="https://www.alternate.be" + image.group(1) if image else None,
        ))
    return hits


class Alternate(Shop):
    key = "alternate.be"

    def search(self, query: Query) -> list[Hit]:
        # Server-rendered result cards; an EAN search finds the exact product.
        _, page = self.get(f"https://www.alternate.be/listing.xhtml?q={quote_plus(self.term(query))}")
        return parse_search(page)[:3]
