from app.pricing import ranked


def l(shop, price, shipping=0, in_stock=1, fails=0):
    return {"shop": shop, "last_price": price, "last_shipping": shipping,
            "last_in_stock": in_stock, "fail_count": fails}


def shops(listings):
    return [x["shop"] for x in ranked(listings)]


def test_shipping_counts_toward_total():
    assert shops([l("a", 1000, shipping=500), l("b", 1200)]) == ["b", "a"]


def test_unknown_shipping_counts_as_zero():
    assert shops([l("a", 1000, shipping=None), l("b", 1001)]) == ["a", "b"]


def test_out_of_stock_excluded():
    assert shops([l("a", 100, in_stock=0), l("b", 200)]) == ["b"]


def test_stale_after_three_failures():
    assert shops([l("a", 100, fails=3), l("b", 200, fails=2)]) == ["b"]


def test_never_priced_excluded():
    assert shops([l("a", None, in_stock=None)]) == []


def test_none_qualifying():
    assert shops([l("a", 100, in_stock=0), l("b", 100, fails=5)]) == []
