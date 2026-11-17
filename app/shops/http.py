import gzip
from urllib.request import Request, urlopen

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip",
}


def get(url: str, timeout: float = 20) -> tuple[str, str]:
    """GET a page; returns (final URL after redirects, text). Raises on HTTP errors."""
    with urlopen(Request(url, headers=HEADERS), timeout=timeout) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return r.geturl(), body.decode(r.headers.get_content_charset() or "utf-8", "replace")
