from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class CacheStats:
    size: int
    hits: int
    misses: int


class TTLCache(Generic[K, V]):
    """
    Small, dependency-free TTL + LRU cache.

    - TTL: entries expire after `ttl_seconds`
    - LRU: evict least-recently-used when exceeding `capacity`
    """

    def __init__(self, *, capacity: int = 256, ttl_seconds: float = 3600.0):
        self.capacity = max(1, int(capacity))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._data: "OrderedDict[K, tuple[float, V]]" = OrderedDict()
        self._hits = 0
        self._misses = 0

    def stats(self) -> CacheStats:
        return CacheStats(size=len(self._data), hits=self._hits, misses=self._misses)

    def _is_expired(self, expires_at: float) -> bool:
        return self.ttl_seconds > 0 and time.time() >= expires_at

    def get(self, key: K) -> Optional[V]:
        item = self._data.get(key)
        if item is None:
            self._misses += 1
            return None
        expires_at, value = item
        if self._is_expired(expires_at):
            try:
                del self._data[key]
            except Exception:
                pass
            self._misses += 1
            return None
        # LRU bump
        self._data.move_to_end(key, last=True)
        self._hits += 1
        return value

    def set(self, key: K, value: V) -> None:
        expires_at = time.time() + self.ttl_seconds if self.ttl_seconds > 0 else float("inf")
        self._data[key] = (expires_at, value)
        self._data.move_to_end(key, last=True)

        while len(self._data) > self.capacity:
            try:
                self._data.popitem(last=False)
            except Exception:
                break

    def cleanup(self) -> int:
        removed = 0
        now = time.time()
        if self.ttl_seconds <= 0:
            return 0
        for k, (expires_at, _v) in list(self._data.items()):
            if now >= expires_at:
                try:
                    del self._data[k]
                    removed += 1
                except Exception:
                    pass
        return removed

