"""Shop adapter interface. One adapter per Shop, see PLAN.md. Amounts are euro cents."""
from dataclasses import dataclass


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
    price: int
    shipping: int | None  # None = unknown
    in_stock: bool
    ean: str | None = None


@dataclass(frozen=True)
class FetchError:
    reason: str  # counts as a failed check; never replaced by a guessed price


class Shop:
    key: str
    needs_browser: bool = False  # plain HTTP is known to fail

    def search(self, query: Query) -> list[Hit]:
        raise NotImplementedError

    def fetch(self, url: str) -> Offer | FetchError:
        raise NotImplementedError
