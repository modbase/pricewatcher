"""Headless Chromium for Shops that block plain HTTP."""
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .http import HEADERS


def get(url: str, timeout_ms: int = 30000, wait_for: str | None = None) -> tuple[str, str]:
    """Like http.get, through a real browser. Must not run on an asyncio event loop thread.
    wait_for: a JS expression that is true once a JavaScript-rendered page is ready (survives redirects)."""
    # ponytail: one browser launch per page (~1-2 s); keep a shared browser if checks get slow.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(locale="nl-BE", user_agent=HEADERS["User-Agent"])
            r = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if r is None or r.status >= 400:
                raise RuntimeError(f"HTTP {r.status if r else 'no response'}")
            for _ in range(3):
                if wait_for:
                    page.wait_for_function(wait_for, timeout=timeout_ms)
                try:
                    return page.url, page.content()
                except PlaywrightError:  # a script redirect started after the wait: let it land, then read again
                    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            return page.url, page.content()
        finally:
            browser.close()
