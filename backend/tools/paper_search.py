from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from ..jobs_store import Job
from ..tool_context import ToolContext


@dataclass(frozen=True)
class PaperResult:
    source: str
    title: str
    authors: List[str]
    abstract: str
    url: str
    published: str = ""


_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


def _strip_ws(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())

def _playwright_enabled() -> bool:
    return (os.getenv("PAPER_PLAYWRIGHT_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


async def _maybe_import_playwright():
    try:
        from playwright.async_api import async_playwright  # type: ignore

        return async_playwright
    except Exception as e:
        raise RuntimeError(
            "Playwright 抓取未可用：请先安装依赖并下载浏览器。\n"
            "- uv: `uv add playwright`（或 `pip install playwright`）\n"
            "- 安装浏览器: `python -m playwright install chromium`\n"
            f"原始错误: {e}"
        )


def _detect_blocked(html: str) -> Optional[str]:
    t = (html or "").lower()
    if "captcha" in t or "recaptcha" in t:
        return "检测到 CAPTCHA（本工具不会绕过验证码）。"
    if "unusual traffic" in t or "sorry" in t and "google" in t:
        return "检测到 Google 反爬拦截（unusual traffic）。"
    if "登录" in html and ("cnki" in t or "知网" in html):
        return "页面提示需要登录/授权（本工具只抓取公开页面）。"
    return None


async def _scholar_playwright_search(
    query: str, *, max_results: int, timeout: float, ctx: ToolContext, job_id: str
) -> List[PaperResult]:
    if not _playwright_enabled():
        raise RuntimeError("Google Scholar 抓取需要启用 Playwright：设置环境变量 PAPER_PLAYWRIGHT_ENABLED=1。")

    async_playwright = await _maybe_import_playwright()
    url = f"https://scholar.google.com/scholar?q={quote_plus(query)}"
    ctx.check_job_cancelled(job_id)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx_pw = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = await ctx_pw.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            html = await page.content()
            blocked = _detect_blocked(html)
            if blocked:
                raise RuntimeError(blocked)

            # Very lightweight parse via DOM queries (no stealth/anti-bot tricks).
            rows = await page.query_selector_all("div.gs_r")
            out: List[PaperResult] = []
            for row in rows[:max_results]:
                title_el = await row.query_selector("h3.gs_rt")
                title = _strip_ws(await title_el.inner_text()) if title_el else ""
                link_el = await title_el.query_selector("a") if title_el else None
                link = _strip_ws(await link_el.get_attribute("href")) if link_el else ""

                meta_el = await row.query_selector("div.gs_a")
                meta = _strip_ws(await meta_el.inner_text()) if meta_el else ""
                # Heuristic: authors are before the first '-' (often "A, B - venue - year")
                authors = []
                if meta:
                    head = meta.split(" - ")[0]
                    authors = [_strip_ws(x) for x in head.split(",") if _strip_ws(x)]

                snippet_el = await row.query_selector("div.gs_rs")
                snippet = _strip_ws(await snippet_el.inner_text()) if snippet_el else ""

                if not title:
                    continue
                out.append(PaperResult(source="scholar", title=title, authors=authors, abstract=snippet, url=link or url))
            return out
        finally:
            try:
                await browser.close()
            except Exception:
                pass


async def _cnki_playwright_search(
    query: str, *, max_results: int, timeout: float, ctx: ToolContext, job_id: str
) -> List[PaperResult]:
    if not _playwright_enabled():
        raise RuntimeError("CNKI 抓取需要启用 Playwright：设置环境变量 PAPER_PLAYWRIGHT_ENABLED=1。")

    async_playwright = await _maybe_import_playwright()
    # CNKI: use KNS8S public search entry (no login/captcha bypass).
    url = f"https://kns.cnki.net/kns8s/defaultresult/index?kw={quote_plus(query)}"
    ctx.check_job_cancelled(job_id)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx_pw = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            page = await ctx_pw.new_page()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            if resp and resp.status >= 400:
                raise RuntimeError(f"CNKI 请求失败（HTTP {resp.status}）。")
            html = await page.content()
            blocked = _detect_blocked(html)
            if blocked:
                raise RuntimeError(blocked)

            # KNS results are rendered into #gridTable.
            try:
                await page.wait_for_selector(
                    "#gridTable .result-table-list tbody tr",
                    timeout=min(30000, int(timeout * 1000)),
                )
            except Exception:
                await page.wait_for_selector("#gridTable", timeout=min(30000, int(timeout * 1000)))

            rows = await page.query_selector_all("#gridTable .result-table-list tbody tr")
            out: List[PaperResult] = []
            for row in rows[:max_results]:
                ctx.check_job_cancelled(job_id)

                title_el = await row.query_selector("td.name a.fz14")
                title = _strip_ws(await title_el.inner_text()) if title_el else ""
                link = _strip_ws(await title_el.get_attribute("href")) if title_el else ""

                authors: List[str] = []
                author_els = await row.query_selector_all("td.author a.KnowledgeNetLink")
                for a in author_els:
                    nm = _strip_ws(await a.inner_text())
                    if nm:
                        authors.append(nm)
                if not authors:
                    author_cell = await row.query_selector("td.author")
                    authors_raw = _strip_ws(await author_cell.inner_text()) if author_cell else ""
                    authors = [_strip_ws(x) for x in re.split(r"[;,，、\\s]+", authors_raw) if _strip_ws(x)]

                mark_el = await row.query_selector("td.name .marktip")
                snippet = _strip_ws(await mark_el.inner_text()) if mark_el else ""

                date_el = await row.query_selector("td.date")
                published = _strip_ws(await date_el.inner_text()) if date_el else ""

                if not title:
                    continue
                out.append(
                    PaperResult(
                        source="cnki",
                        title=title,
                        authors=authors,
                        abstract=snippet,
                        url=link or url,
                        published=published,
                    )
                )

            if not out:
                raise RuntimeError("CNKI 未解析到结果（可能被拦截、无结果或页面结构已变化）。")

            return out
        finally:
            try:
                await browser.close()
            except Exception:
                pass


async def _arxiv_search(query: str, *, max_results: int, timeout: float, ctx: ToolContext, job_id: str) -> List[PaperResult]:
    q = quote_plus(query)
    url = f"http://export.arxiv.org/api/query?search_query=all:{q}&start=0&max_results={max_results}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        ctx.check_job_cancelled(job_id)
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        ctx.check_job_cancelled(job_id)
        xml_text = r.text

    root = ET.fromstring(xml_text)
    out: List[PaperResult] = []
    for entry in root.findall("a:entry", _ATOM_NS):
        title = _strip_ws(entry.findtext("a:title", default="", namespaces=_ATOM_NS))
        summary = _strip_ws(entry.findtext("a:summary", default="", namespaces=_ATOM_NS))
        published = _strip_ws(entry.findtext("a:published", default="", namespaces=_ATOM_NS))
        authors = [_strip_ws(a.findtext("a:name", default="", namespaces=_ATOM_NS)) for a in entry.findall("a:author", _ATOM_NS)]
        authors = [a for a in authors if a]

        link = ""
        for l in entry.findall("a:link", _ATOM_NS):
            rel = (l.attrib.get("rel") or "").strip()
            href = (l.attrib.get("href") or "").strip()
            if rel == "alternate" and href:
                link = href
                break
        if not link:
            link = _strip_ws(entry.findtext("a:id", default="", namespaces=_ATOM_NS))

        if not title:
            continue
        out.append(PaperResult(source="arxiv", title=title, authors=authors, abstract=summary, url=link, published=published))
        if len(out) >= max_results:
            break
    return out


async def _scholar_serpapi_search(
    query: str, *, max_results: int, timeout: float, ctx: ToolContext, job_id: str
) -> List[PaperResult]:
    api_key = (os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Google Scholar 需要配置 SERPAPI_KEY（SerpAPI）才能检索，未检测到该环境变量。")
    url = "https://serpapi.com/search.json"
    params = {"engine": "google_scholar", "q": query, "api_key": api_key, "num": max_results}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        ctx.check_job_cancelled(job_id)
        r = await client.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()

    results = data.get("organic_results") or []
    out: List[PaperResult] = []
    for it in results[:max_results]:
        title = _strip_ws(it.get("title") or "")
        link = _strip_ws(it.get("link") or it.get("result_id") or "")
        snippet = _strip_ws(it.get("snippet") or "")
        pub = it.get("publication_info") or {}
        authors_raw = pub.get("authors") or []
        authors = []
        if isinstance(authors_raw, list):
            for a in authors_raw:
                nm = _strip_ws((a or {}).get("name") or "")
                if nm:
                    authors.append(nm)
        summary = snippet
        if not title:
            continue
        out.append(PaperResult(source="scholar", title=title, authors=authors, abstract=summary, url=link, published=""))
    return out


async def run(job: Job, ctx: ToolContext, update_progress) -> Dict[str, Any]:
    ctx.check_job_cancelled(job.id)
    payload = job.payload or {}
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query required"}

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        sources = ["arxiv", "scholar", "cnki"]
    sources = [str(s).strip().lower() for s in sources if str(s).strip()]

    max_results = int(payload.get("max_results") or 5)
    max_results = max(1, min(20, max_results))
    timeout = float(payload.get("timeout_seconds") or 25.0)
    timeout = max(3.0, min(120.0, timeout))

    results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    done = 0
    total = max(1, len(sources))

    async def _add(items: List[PaperResult]):
        for p in items:
            results.append(
                {
                    "source": p.source,
                    "title": p.title,
                    "authors": p.authors,
                    "abstract": p.abstract,
                    "url": p.url,
                    "published": p.published,
                }
            )

    for src in sources:
        ctx.check_job_cancelled(job.id)
        update_progress(min(0.95, 0.05 + 0.9 * (done / total)))
        try:
            if src == "arxiv":
                await _add(await _arxiv_search(query, max_results=max_results, timeout=timeout, ctx=ctx, job_id=job.id))
            elif src in ("google_scholar", "googlescholar", "scholar"):
                # Prefer SerpAPI if configured; otherwise optionally fall back to Playwright (public page only).
                try:
                    await _add(await _scholar_serpapi_search(query, max_results=max_results, timeout=timeout, ctx=ctx, job_id=job.id))
                except Exception:
                    await _add(await _scholar_playwright_search(query, max_results=max_results, timeout=timeout, ctx=ctx, job_id=job.id))
            elif src == "cnki":
                await _add(await _cnki_playwright_search(query, max_results=max_results, timeout=timeout, ctx=ctx, job_id=job.id))
            else:
                raise RuntimeError(f"Unknown source: {src}")
        except Exception as e:
            errors[src] = str(e)
        finally:
            done += 1

    update_progress(1.0)
    ok_sources = sorted({r.get("source") for r in results if r.get("source")})
    summary = f"论文检索完成：{len(results)} 条结果（sources={','.join(ok_sources) or 'none'}）。"
    if errors:
        summary += f" 未成功：{', '.join(sorted(errors.keys()))}。"
    if results:
        top = results[0]
        summary += f" Top1: {top.get('title','')}"

    return {
        "type": "paper_search",
        "summary": summary,
        "query": query,
        "results": results,
        "errors": errors,
    }
