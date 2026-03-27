"""Chatty — Web search and fetch tools.

Provides web_search (DuckDuckGo) and web_fetch (httpx + BeautifulSoup) handlers
for use by all AI agents.
"""

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

_BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.google.internal.",
    "169.254.169.254",
}

def _validate_url(url: str) -> str | None:
    """Return an error string if the URL targets a blocked host, else None."""
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if hostname in _BLOCKED_HOSTS or hostname.startswith("169.254."):
            return f"Requests to '{hostname}' are blocked"
        if parsed.scheme not in ("http", "https"):
            return f"Unsupported scheme '{parsed.scheme}'"
    except Exception:
        return "Invalid URL"
    return None

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_MAX_CONTENT_CHARS = 15_000
_MAX_RESPONSE_BYTES = 5_000_000  # 5 MB
_STRIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"}


def web_search(query: str, num_results: int = 5) -> dict:
    """Search the web using DuckDuckGo. Returns top results with title, URL, and snippet."""
    num_results = max(1, min(num_results, 10))
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=num_results))
        results = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in raw
        ]
        return {"results": results, "total": len(results), "query": query}
    except Exception as e:
        return {"error": f"Web search failed: {e}", "query": query}


def web_fetch(url: str, extract_links: bool = False) -> dict:
    """Fetch a URL and extract readable text content using BeautifulSoup."""
    ssrf_err = _validate_url(url)
    if ssrf_err:
        return {"error": ssrf_err, "url": url}
    try:
        resp = httpx.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}", "url": url}
    except Exception as e:
        return {"error": f"Fetch failed: {e}", "url": url}

    content_length = int(resp.headers.get("content-length", 0))
    if content_length > _MAX_RESPONSE_BYTES:
        return {"error": f"Response too large ({content_length} bytes, max {_MAX_RESPONSE_BYTES})", "url": url}

    content_type = resp.headers.get("content-type", "")

    # Non-HTML: return raw text truncated
    if "html" not in content_type:
        text = resp.text[:_MAX_CONTENT_CHARS]
        return {
            "url": url,
            "title": None,
            "content": text,
            "content_length": len(resp.text),
            "truncated": len(resp.text) > _MAX_CONTENT_CHARS,
        }

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract title
    title = soup.title.get_text(strip=True) if soup.title else None

    # Strip non-content tags
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    # Extract text
    text = soup.get_text(separator="\n", strip=True)

    # Collapse excessive blank lines
    lines = text.splitlines()
    collapsed = []
    blank_count = 0
    for line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 1:
                collapsed.append("")
        else:
            blank_count = 0
            collapsed.append(line)
    text = "\n".join(collapsed)

    truncated = len(text) > _MAX_CONTENT_CHARS
    text = text[:_MAX_CONTENT_CHARS]

    result = {
        "url": url,
        "title": title,
        "content": text,
        "content_length": len(text),
        "truncated": truncated,
    }

    if extract_links:
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith(("http://", "https://")):
                link_text = a.get_text(strip=True)
                if link_text:
                    links.append({"text": link_text[:100], "href": href})
        result["links"] = links[:50]

    return result
