"""Web search & HTTP page fetch tools for aZoth-local.

Provides robust multi-provider search (DuckDuckGo + Yahoo fallback) and clean
HTML page text extraction.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

import requests
from bs4 import BeautifulSoup


def _search_ddg(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for result in soup.find_all("div", class_="result")[:max_results]:
        title_tag = result.find("a", class_="result__a")
        snippet_tag = result.find("a", class_="result__snippet")
        if title_tag:
            title = title_tag.get_text(strip=True)
            raw_link = title_tag.get("href", "")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            actual_link = raw_link
            if "uddg=" in raw_link:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_link).query)
                if "uddg" in parsed:
                    actual_link = parsed["uddg"][0]
            results.append({
                "title": title,
                "url": actual_link,
                "snippet": snippet,
                "source": "duckduckgo",
            })
    return results


def _search_yahoo(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote_plus(query)
    url = f"https://search.yahoo.com/search?p={encoded}"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0"
    }
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for item in soup.select("div.algo")[:max_results]:
        a = item.select_one("h3 a") or item.select_one("a")
        p = item.select_one(".compText") or item.select_one("p")
        if a:
            raw_href = a.get("href", "")
            m = re.search(r"/RU=([^/]+)/", raw_href)
            actual_url = urllib.parse.unquote(m.group(1)) if m else raw_href
            title = a.get_text(strip=True)
            snippet = p.get_text(strip=True) if p else ""
            results.append({
                "title": title,
                "url": actual_url,
                "snippet": snippet,
                "source": "yahoo",
            })
    return results


def search_web(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the live web using resilient multi-engine routing."""
    clean_query = query.strip()
    results: list[dict[str, Any]] = []

    # 1. Try DuckDuckGo
    try:
        results = _search_ddg(clean_query, max_results=max_results)
    except Exception:
        results = []

    # 2. Resilient fallback to Yahoo if DDG failed or was challenged
    if not results:
        try:
            results = _search_yahoo(clean_query, max_results=max_results)
        except Exception:
            results = []

    return {
        "ok": True,
        "query": clean_query,
        "results": results,
        "summary": f"Found {len(results)} search results for '{clean_query}'",
    }


def fetch_page(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """Fetch a public webpage over HTTP and extract clean text."""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        if "text/html" in content_type:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "svg", "noscript", "meta", "link"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            text_clean = " ".join(text.split())
        else:
            text_clean = resp.text

        if len(text_clean) > max_chars:
            text_clean = text_clean[:max_chars] + "... [truncated]"

        return {
            "ok": True,
            "url": url,
            "content": text_clean,
            "status_code": resp.status_code,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}
