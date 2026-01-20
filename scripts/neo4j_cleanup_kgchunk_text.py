from __future__ import annotations

import argparse
import os
import sys

from neo4j import GraphDatabase


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate Neo4j KGChunk.text (full text) -> KGChunk.text_preview (short), then remove KGChunk.text.",
    )
    parser.add_argument("--uri", default=_env("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=_env("NEO4J_PASSWORD", ""))
    parser.add_argument("--database", default=_env("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--preview-limit", type=int, default=480)
    parser.add_argument("--batch", type=int, default=1000, help="Rows per transaction batch (Neo4j 5+).")
    parser.add_argument("--dry-run", action="store_true", help="Only count how many KGChunk nodes still have `text`.")
    args = parser.parse_args()

    if not args.password:
        print("NEO4J_PASSWORD is required (env or --password).", file=sys.stderr)
        return 2

    preview_limit = max(40, int(args.preview_limit))
    batch = max(100, int(args.batch))

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        with driver.session(database=args.database) as session:
            if args.dry_run:
                n = session.run(
                    "MATCH (c:KGChunk) WHERE c.text IS NOT NULL RETURN count(c) AS n"
                ).single()
                count = int(n["n"] if n and n.get("n") is not None else 0)
                print(f"KGChunk nodes with legacy `text`: {count}")
                return 0

            # Neo4j 5+: batched update in transactions to avoid huge single tx.
            cypher = f"""
            CALL {{
              MATCH (c:KGChunk)
              WHERE c.text IS NOT NULL
              WITH c
              SET c.text_preview = COALESCE(
                    c.text_preview,
                    CASE
                      WHEN c.text IS NULL THEN ''
                      WHEN size(c.text) > $preview_limit THEN substring(c.text, 0, $preview_limit) + '…'
                      ELSE c.text
                    END
                  ),
                  c.kb_doc_id = COALESCE(c.kb_doc_id, ''),
                  c.kb_chunk_id = COALESCE(c.kb_chunk_id, ''),
                  c.source = COALESCE(c.source, '')
              REMOVE c.text
              RETURN count(c) AS batch_n
            }} IN TRANSACTIONS OF {batch} ROWS
            RETURN sum(batch_n) AS updated
            """
            row = session.run(cypher, preview_limit=preview_limit).single()
            updated = int(row["updated"] if row and row.get("updated") is not None else 0)
            print(f"Updated KGChunk nodes: {updated}")
            return 0
    finally:
        try:
            driver.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

