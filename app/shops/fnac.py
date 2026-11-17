from .base import Hit, Query, Shop


class Fnac(Shop):
    key = "fnac.be"  # nl.fnac.be and fr.fnac.be both count

    def search(self, query: Query) -> list[Hit]:
        # Product pages load over plain HTTP, but search answers 403 with a captcha, even in a browser.
        raise RuntimeError("Fnac blocks automated search; paste the product URL from nl.fnac.be")
