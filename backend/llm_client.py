"""Unified LLM client supporting multiple providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import config


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str


def parse_model_spec(spec: str) -> ModelSpec:
    """
    Parse a model spec of the form "<provider>:<model>".
    If no provider is given, defaults to "openrouter" (backwards compatible).
    """
    if ":" not in spec:
        return ModelSpec(provider="openrouter", model=spec)
    provider, model = spec.split(":", 1)
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        return ModelSpec(provider="openrouter", model=spec)
    return ModelSpec(provider=provider, model=model)


def _extract_openai_message_content(data: Dict[str, Any]) -> Tuple[Optional[str], Any]:
    try:
        message = data["choices"][0]["message"]
        return message.get("content"), message.get("reasoning_details")
    except Exception:
        return None, None


async def _query_openai_compatible(
    *,
    url: str,
    api_key: Optional[str],
    model: str,
    messages: List[Dict[str, str]],
    timeout: float,
    headers_extra: Optional[Dict[str, str]] = None,
    silent: bool = False,
) -> Optional[Dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if headers_extra:
        headers.update(headers_extra)

    payload = {
        "model": model,
        "messages": messages,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content, reasoning_details = _extract_openai_message_content(data)
            return {
                "content": content,
                "reasoning_details": reasoning_details,
            }
    except Exception as e:
        if not silent:
            print(f"Error querying OpenAI-compatible endpoint {url} model {model}: {e}")
        return None


async def _query_openai_compatible_embeddings(
    *,
    url: str,
    api_key: Optional[str],
    model: str,
    inputs: List[str],
    timeout: float,
    headers_extra: Optional[Dict[str, str]] = None,
    silent: bool = False,
) -> Optional[List[List[float]]]:
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if headers_extra:
        headers.update(headers_extra)

    payload = {
        "model": model,
        "input": inputs,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            items = data.get("data") or []
            # OpenAI returns embeddings in the original input order with "index".
            items_sorted = sorted(items, key=lambda x: x.get("index", 0))
            vectors = [it.get("embedding") for it in items_sorted]
            if not all(isinstance(v, list) for v in vectors):
                return None
            return vectors  # type: ignore[return-value]
    except Exception as e:
        if not silent:
            print(f"Error querying embeddings endpoint {url} model {model}: {e}")
        return None


async def _query_ollama(
    *,
    base_url: str,
    model: str,
    messages: List[Dict[str, str]],
    timeout: float,
) -> Optional[Dict[str, Any]]:
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            message = data.get("message") or {}
            return {
                "content": message.get("content"),
                "reasoning_details": None,
            }
    except Exception as e:
        print(f"Error querying Ollama {url} model {model}: {e}")
        return None


async def _query_ollama_embeddings(
    *,
    base_url: str,
    model: str,
    inputs: List[str],
    timeout: float,
) -> Optional[List[List[float]]]:
    url = base_url.rstrip("/") + "/api/embeddings"
    try:
        vectors: List[List[float]] = []
        async with httpx.AsyncClient(timeout=timeout) as client:
            for text in inputs:
                response = await client.post(url, json={"model": model, "prompt": text})
                response.raise_for_status()
                data = response.json()
                emb = data.get("embedding")
                if not isinstance(emb, list):
                    return None
                vectors.append(emb)
        return vectors
    except Exception as e:
        print(f"Error querying Ollama embeddings {url} model {model}: {e}")
        return None


def provider_key_configured(provider: str) -> Optional[bool]:
    provider = provider.lower()
    if provider == "openrouter":
        return bool(config.OPENROUTER_API_KEY)
    if provider == "dashscope":
        return bool(config.DASHSCOPE_API_KEY)
    if provider == "apiyi":
        return bool(config.APIYI_API_KEY)
    if provider == "ollama":
        return True
    return None


async def query_model(
    spec: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    *,
    silent: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Query a model from one of the supported providers.

    Spec format: "<provider>:<model>" (provider defaults to "openrouter").
    Supported providers: openrouter, dashscope, apiyi, ollama
    """
    parsed = parse_model_spec(spec)

    if parsed.provider == "openrouter":
        return await _query_openai_compatible(
            url=config.OPENROUTER_API_URL,
            api_key=config.OPENROUTER_API_KEY,
            model=parsed.model,
            messages=messages,
            timeout=timeout,
            silent=silent,
        )

    if parsed.provider == "dashscope":
        url = config.DASHSCOPE_BASE_URL.rstrip("/") + "/chat/completions"
        return await _query_openai_compatible(
            url=url,
            api_key=config.DASHSCOPE_API_KEY,
            model=parsed.model,
            messages=messages,
            timeout=timeout,
            silent=silent,
        )

    if parsed.provider == "apiyi":
        url = config.APIYI_BASE_URL.rstrip("/") + "/chat/completions"
        return await _query_openai_compatible(
            url=url,
            api_key=config.APIYI_API_KEY,
            model=parsed.model,
            messages=messages,
            timeout=timeout,
            silent=silent,
        )

    if parsed.provider == "ollama":
        return await _query_ollama(
            base_url=config.OLLAMA_BASE_URL,
            model=parsed.model,
            messages=messages,
            timeout=timeout,
        )

    raise ValueError(
        f"Unsupported provider '{parsed.provider}'. Use one of: openrouter, dashscope, apiyi, ollama."
    )


async def query_models_parallel(
    specs: List[str],
    messages: List[Dict[str, str]],
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Query multiple model specs in parallel."""
    import asyncio

    tasks = [query_model(spec, messages) for spec in specs]
    responses = await asyncio.gather(*tasks, return_exceptions=False)
    return {spec: response for spec, response in zip(specs, responses)}


async def embed_texts(
    spec: str,
    texts: List[str],
    timeout: float = 120.0,
    *,
    silent: bool = False,
) -> Optional[List[List[float]]]:
    """
    Get embeddings for a list of texts.

    Spec format: "<provider>:<model>" (provider defaults to "openrouter").
    Supported providers: openrouter, dashscope, apiyi, ollama
    """
    parsed = parse_model_spec(spec)
    texts = [t or "" for t in (texts or [])]
    if not texts:
        return []

    if parsed.provider == "openrouter":
        url = "https://openrouter.ai/api/v1/embeddings"
        return await _query_openai_compatible_embeddings(
            url=url,
            api_key=config.OPENROUTER_API_KEY,
            model=parsed.model,
            inputs=texts,
            timeout=timeout,
            silent=silent,
        )

    if parsed.provider == "dashscope":
        url = config.DASHSCOPE_BASE_URL.rstrip("/") + "/embeddings"
        return await _query_openai_compatible_embeddings(
            url=url,
            api_key=config.DASHSCOPE_API_KEY,
            model=parsed.model,
            inputs=texts,
            timeout=timeout,
            silent=silent,
        )

    if parsed.provider == "apiyi":
        url = config.APIYI_BASE_URL.rstrip("/") + "/embeddings"
        return await _query_openai_compatible_embeddings(
            url=url,
            api_key=config.APIYI_API_KEY,
            model=parsed.model,
            inputs=texts,
            timeout=timeout,
            silent=silent,
        )

    if parsed.provider == "ollama":
        return await _query_ollama_embeddings(
            base_url=config.OLLAMA_BASE_URL,
            model=parsed.model,
            inputs=texts,
            timeout=timeout,
        )

    raise ValueError(
        f"Unsupported provider '{parsed.provider}'. Use one of: openrouter, dashscope, apiyi, ollama."
    )
