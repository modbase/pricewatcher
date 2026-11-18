from .alternate import Alternate
from .amazon import Amazon
from .base import FetchError, Hit, Offer, Query, Shop
from .bol import Bol
from .coolblue import Coolblue
from .custom import CustomShop
from .mediamarkt import MediaMarkt
from .vandenborre import Vandenborre

BUILTIN: dict[str, Shop] = {
    s.key: s
    for s in (Bol(), Coolblue(), MediaMarkt(), Vandenborre(), Alternate(),Amazon("amazon.com.be"), Amazon("amazon.nl"))
}
SHOPS: dict[str, Shop] = dict(BUILTIN)


def sync(custom: list[dict]) -> None:
    """Make the custom Shops in SHOPS match the settings; validation keeps them off built-in keys."""
    new = {c["domain"]: CustomShop(c["domain"], c["search_url"]) for c in custom}
    # Changed in place: other modules hold this dict, and kept keys never disappear mid-check.
    SHOPS.update(new)
    for key in [k for k, s in SHOPS.items() if isinstance(s, CustomShop) and k not in new]:
        del SHOPS[key]
