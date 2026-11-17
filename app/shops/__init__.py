from .amazon import Amazon
from .base import FetchError, Hit, Offer, Query, Shop
from .bol import Bol
from .coolblue import Coolblue
from .mediamarkt import MediaMarkt
from .vandenborre import Vandenborre

SHOPS: dict[str, Shop] = {
    s.key: s
    for s in (Bol(), Coolblue(), MediaMarkt(), Vandenborre(), Amazon("amazon.com.be"), Amazon("amazon.nl"))
}
