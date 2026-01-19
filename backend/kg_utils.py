"""Small helpers shared across KG endpoints and jobs."""

from __future__ import annotations


def stable_uuid_fallback(graph_id: str, entity_type: str, name: str) -> str:
    # Keep consistent with Neo4j store stable id.
    import hashlib

    normalized = (name or "").strip().lower()
    base = f"{graph_id}:{entity_type}:{normalized}".encode("utf-8")
    digest = hashlib.sha1(base).hexdigest()[:16]
    return f"ent_{digest}"

