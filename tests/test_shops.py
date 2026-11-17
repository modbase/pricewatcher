import gzip
from pathlib import Path

import pytest

from app.shops import Amazon, FetchError, Offer, amazon, jsonld
from app.shops.bol import Bol, organic_links
from app.shops.coolblue import Coolblue

FIXTURES = Path(__file__).parent / "fixtures"


def page(name: str) -> str:
    return gzip.decompress((FIXTURES / f"{name}.html.gz").read_bytes()).decode("utf-8")


@pytest.mark.parametrize("raw, cents", [
    (69, 6900), (72.9, 7290), ("72.90", 7290), ("1.299,99", 129999), ("1,299.99", 129999),
    ("€ 49,-", 4900), ("49,99 €", 4999), ("1299", 129900), ("1.299", 129900), ("€ 1.299,9", 129990),
    (None, None), ("", None), ("gratis", None),
])
def test_to_cents(raw, cents):
    assert jsonld.to_cents(raw) == cents


def test_bol_product_page():
    assert jsonld.parse_offer(page("bol_product")) == Offer(7290, 0, True, "5099206129382")


def test_coolblue_product_page():
    assert jsonld.parse_offer(page("coolblue_product")) == Offer(6900, None, True, None)


def test_page_without_jsonld_is_an_error():
    assert isinstance(jsonld.parse_offer("<html></html>"), FetchError)


def test_non_eur_is_an_error():
    html = '<script type="application/ld+json">{"@type":"Product","offers":{"price":"10","priceCurrency":"USD"}}</script>'
    assert isinstance(jsonld.parse_offer(html), FetchError)


def test_bol_search_skips_sponsored():
    links = organic_links(page("bol_search"))
    assert not any("macbook" in u for u in links[:3])
    assert links[:2] == [
        "https://www.bol.com/be/nl/p/logitech-mx-master-3se-draadloze-muis-graphite-windows-linux-chrome/9300000239090168/",
        "https://www.bol.com/be/nl/p/logitech-mx-master-3s-muis-zwart/9300000096887779/",
    ]


def test_coolblue_search_hits():
    hits = [jsonld.to_hit(p, "x") for p in jsonld.products(page("coolblue_search"))]
    assert hits[0].url == "https://www.coolblue.be/nl/product/970149/logitech-mx-master-3s-bluetooth-edition.html"
    assert (hits[0].title, hits[0].price) == ("Logitech MX Master 3S Bluetooth Edition", 6900)


def test_amazon_product_reads_buy_box_only():
    assert amazon.parse_product(page("amazon_product")) == Offer(7218, 0, True)


def test_amazon_out_of_stock_is_not_a_failure():
    # This page shows other products' prices further down; none of them may leak in.
    assert amazon.parse_product(page("amazon_product_oos")) == Offer(None, None, False)


def test_amazon_captcha_is_an_error():
    assert isinstance(amazon.parse_product('<form action="/errors/validateCaptcha">'), FetchError)


def test_amazon_search_skips_ads():
    hits = amazon.parse_search(page("amazon_search"), "amazon.nl")
    assert [h.asin for h in hits] == ["B0FHHV6YR5", "B07W6HCFYS", "B0FHHSHJ5L"]
    assert hits[0].url == "https://www.amazon.nl/dp/B0FHHV6YR5"
    assert hits[0].price == 7218 and hits[0].title.startswith("Logitech MX Master 3S")


@pytest.mark.parametrize("shop, url, ok", [
    (Amazon("amazon.com.be"), "https://www.amazon.com.be/dp/B0FHHV6YR5", True),
    (Amazon("amazon.com.be"), "https://www.amazon.de/dp/B0FHHV6YR5", False),
    (Bol(), "https://www.bol.com/be/nl/p/x/1/", True),
    (Bol(), "https://bol.com/x", True),
    (Bol(), "https://evilbol.com/x", False),
    (Coolblue(), "https://www.coolblue.be/nl/product/1/x.html", True),
    (Coolblue(), "javascript:alert(1)//coolblue.be", False),
])
def test_owns(shop, url, ok):
    assert shop.owns(url) is ok
