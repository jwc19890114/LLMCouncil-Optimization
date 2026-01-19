"""LLM-based reranker for retrieval results."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from . import config
from .llm_client import parse_model_spec, query_model


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


async def rerank(
    *,
    model_spec: str,
    query: str,
    candidates: List[Dict[str, Any]],
    top_k: int,
    timeout: float = 120.0,
) -> List[Dict[str, Any]]:
    """
    Rerank candidates by relevance to query.
    Returns a list of {index:int, score:float} sorted desc score.
    """
    query = (query or "").strip()
    if not query or not candidates:
        return []

    top_k = max(1, min(top_k, len(candidates)))
    shown = candidates[: min(len(candidates), max(top_k * 3, 12))]

    items = []
    for i, c in enumerate(shown):
        text = (c.get("text") or "").strip()
        if len(text) > 800:
            text = text[:800] + "…"
        meta = []
        if c.get("title"):
            meta.append(f"title={c['title']}")
        if c.get("source"):
            meta.append(f"source={c['source']}")
        meta_s = ("; " + "; ".join(meta)) if meta else ""
        items.append(f"[{i}]{meta_s}\n{text}")

    system = (
        "你是一个检索结果重排器（reranker）。\n"
        "任务：根据用户问题，从候选片段中挑选最相关的 TopK，并给出相关性分数。\n"
        "要求：\n"
        "- 输出必须是严格 JSON（不要 Markdown，不要解释文字）。\n"
        '- JSON 结构：{"ranking":[{"index":0,"score":0.0},...]}。\n'
        "- score 范围 0~1，越大越相关。\n"
        f"- ranking 数量必须等于 {top_k}。\n"
    )

    parsed = parse_model_spec(model_spec)

    # Some providers expose rerank-only models that are not chat-completions compatible.
    # For DashScope, try a rerank endpoint when the model name suggests a reranker.
    if parsed.provider == "dashscope" and "rerank" in parsed.model.lower():
        return await _dashscope_rerank(
            model=parsed.model,
            query=query,
            candidates=shown,
            top_k=top_k,
            timeout=timeout,
        )

    user = "用户问题：\n" + query + "\n\n候选片段：\n" + "\n\n".join(items)
    resp = await query_model(
        model_spec,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        timeout=timeout,
        silent=True,
    )
    content = (resp or {}).get("content") or ""
    data = _extract_json_object(content)
    if not data:
        return []

    ranking = data.get("ranking")
    if not isinstance(ranking, list):
        return []
    out: List[Dict[str, Any]] = []
    for r in ranking:
        if not isinstance(r, dict):
            continue
        try:
            idx = int(r.get("index"))
            score = float(r.get("score"))
        except Exception:
            continue
        if 0 <= idx < len(shown):
            out.append({"index": idx, "score": max(0.0, min(1.0, score))})

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_k]


async def _dashscope_rerank(
    *,
    model: str,
    query: str,
    candidates: List[Dict[str, Any]],
    top_k: int,
    timeout: float,
) -> List[Dict[str, Any]]:
    """
    Best-effort DashScope rerank call.

    DashScope's OpenAI-compatible endpoint may not support rerank-only models via /chat/completions.
    We try a /rerank endpoint under DASHSCOPE_BASE_URL. If it fails or returns an unexpected shape,
    rerank gracefully falls back to "no rerank" (empty list).
    """
    api_key = (config.DASHSCOPE_API_KEY or "").strip()
    if not api_key:
        return []

    url = config.DASHSCOPE_BASE_URL.rstrip("/") + "/rerank"
    docs = [(c.get("text") or "")[:1200] for c in (candidates or [])]
    payload = {
        "model": model,
        "query": query,
        "documents": docs,
        "top_n": top_k,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results = None
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            results = data.get("results")
        elif isinstance((data.get("output") or {}).get("results"), list):
            results = (data.get("output") or {}).get("results")

    if not isinstance(results, list):
        return []

    out: List[Dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        idx = r.get("index")
        if idx is None:
            idx = r.get("document_index")
        score = r.get("relevance_score")
        if score is None:
            score = r.get("score")
        try:
            idx_i = int(idx)
            score_f = float(score)
        except Exception:
            continue
        if 0 <= idx_i < len(candidates):
            out.append({"index": idx_i, "score": max(0.0, min(1.0, score_f))})

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[: max(1, min(top_k, len(out)))]
