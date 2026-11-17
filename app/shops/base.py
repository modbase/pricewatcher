"""Shop adapter interface. One adapter per Shop, see PLAN.md. Amounts are euro cents."""
from dataclasses import dataclass
from urllib.parse import urlparse

from . import http, jsonld


@dataclass(frozen=True)
class Query:
    name: str
    ean: str | None = None
    mpn: str | None = None
    asin: str | None = None


@dataclass(frozen=True)
class Hit:
    url: str
    title: str
    price: int | None
    image: str | None = None
    ean: str | None = None
    asin: str | None = None


@dataclass(frozen=True)
class Offer:
    price: int | None  # None only when out of stock without a shown price
    shipping: int | None  # None = unknown
    in_stock: bool
    ean: str | None = None


@dataclass(frozen=True)
class FetchError:
    reason: str  # counts as a failed check; never replaced by a guessed price


class Shop:
    key: str  # also the domain, e.g. "bol.com"
    needs_browser: bool = False  # plain HTTP is known to fail

    def term(self, query: Query) -> str:
        return query.ean or query.mpn or query.name

    def owns(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return urlparse(url).scheme in ("http", "https") and (host == self.key or host.endswith("." + self.key))

    def get(self, url: str, use_browser: bool | None = None) -> tuple[str, str]:
        if self.needs_browser if use_browser is None else use_browser:
            from . import browser  # Playwright is only imported when a browser is needed
            return browser.get(url)
        return http.get(url)

    def search(self, query: Query) -> list[Hit]:
        raise NotImplementedError

    def hit(self, url: str) -> Hit | None:
        """The Hit for one product page, from its JSON-LD."""
        final, html = self.get(url)
        products = jsonld.products(html)
        return jsonld.to_hit(products[0], final) if products else None

    def parse(self, html: str) -> Offer | FetchError:
        return jsonld.parse_offer(html)

    def fetch(self, url: str) -> Offer | FetchError:
        result = self._fetch(url, self.needs_browser)
        if isinstance(result, FetchError) and not self.needs_browser:
            result = self._fetch(url, True)  # blocked or empty over plain HTTP: retry once in a real browser
        return result

    def _fetch(self, url: str, use_browser: bool) -> Offer | FetchError:
        try:
            _, html = self.get(url, use_browser)
            return self.parse(html)
        except Exception as e:  # network, HTTP status, decoding, missing Playwright: all count as a failed check
            return FetchError(f"{type(e).__name__}: {e}")
