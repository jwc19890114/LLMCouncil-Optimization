"""LLM-based reranker for retrieval results."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .llm_client import query_model


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

    user = "用户问题：\n" + query + "\n\n候选片段：\n" + "\n\n".join(items)
    try:
        resp = await query_model(
            model_spec,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            timeout=timeout,
        )
    except Exception:
        # Best-effort: rerank is optional. If the model_spec does not support chat/completions
        # (e.g. some provider-specific rerank-only models), fall back to heuristic ranking.
        return []
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
