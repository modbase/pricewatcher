"""Headless Chromium for Shops that block plain HTTP."""
from playwright.sync_api import sync_playwright

from .http import HEADERS


def get(url: str, timeout_ms: int = 30000, wait_until: str = "domcontentloaded") -> tuple[str, str]:
    """Like http.get, through a real browser. Must not run on an asyncio event loop thread.
    wait_until="networkidle" for pages that render their content with JavaScript."""
    # ponytail: one browser launch per page (~1-2 s); keep a shared browser if checks get slow.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(locale="nl-BE", user_agent=HEADERS["User-Agent"])
            r = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            if r is None or r.status >= 400:
                raise RuntimeError(f"HTTP {r.status if r else 'no response'}")
            return page.url, page.content()
        finally:
            browser.close()
