from .amazon import Amazon
from .base import FetchError, Hit, Offer, Query, Shop
from .bol import Bol
from .coolblue import Coolblue

SHOPS: dict[str, Shop] = {
    s.key: s
    for s in (Bol(), Coolblue(), Amazon("amazon.com.be"), Amazon("amazon.nl"), Amazon("amazon.de"))
}
