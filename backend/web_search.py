"""Basic web search (no API key) via DuckDuckGo HTML."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import List
from urllib.parse import quote_plus

import httpx


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str = ""


async def ddg_search(query: str, max_results: int = 5, timeout: float = 10.0) -> List[WebResult]:
    q = quote_plus(query)
    url = f"https://duckduckgo.com/html/?q={q}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        text = r.text

    results: List[WebResult] = []

    # DuckDuckGo HTML results:
    # <a rel="nofollow" class="result__a" href="...">Title</a>
    # <a class="result__snippet" ...>Snippet</a>
    link_re = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    snippet_re = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.S)

    links = link_re.findall(text)
    snippets = snippet_re.findall(text)

    for i, (href, title_html) in enumerate(links):
        if len(results) >= max_results:
            break
        title = html.unescape(re.sub(r"<.*?>", "", title_html)).strip()
        snippet = ""
        if i < len(snippets):
            snippet = html.unescape(re.sub(r"<.*?>", "", snippets[i])).strip()
        if not title or not href:
            continue
        results.append(WebResult(title=title, url=href, snippet=snippet))

    return results

