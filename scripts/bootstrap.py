"""One command to take an empty database to a working demo.

Order matters and each step explains why it comes where it does. Run it twice and
nothing breaks: every step is idempotent, which is a requirement rather than a nice
property — the most common way a demo dies is a half-seeded database.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.config import configure_logging, get_settings  # noqa: E402
from db import pool  # noqa: E402


async def step(label: str, coro) -> None:
    print(f"\n=== {label} ===")
    await coro


async def already_populated() -> bool:
    """Is the database already usable? Cheap enough to run on every boot.

    Checks the *end* of the pipeline rather than the beginning: chunks exist only
    after migrate, seed, corpus and ingest have all succeeded, so a half-finished
    bootstrap correctly reports as not populated and runs again.
    """
    try:
        chunks = int(await pool.fetchval("SELECT count(*) FROM chunks") or 0)
        actors = int(await pool.fetchval("SELECT count(*) FROM actors") or 0)
    except Exception:  # tables absent: definitely not populated
        return False
    return chunks > 0 and actors > 0


async def main() -> int:
    configure_logging()
    settings = get_settings()
    print("BuildWise bootstrap")
    print(f"  database : {settings.database_url.split('@')[-1]}")
    print(f"  llm      : {settings.llm_provider}")
    print(f"  embeddings: {settings.embedding_provider}")

    try:
        await pool.get_pool()
    except Exception as exc:  # noqa: BLE001
        print(f"\nCannot reach Postgres: {exc}")
        print("Start it with `make up` (or `docker compose up -d postgres`) and try again.")
        return 1

    if "--if-empty" in sys.argv and await already_populated():
        counts = await pool.fetchrow(
            "SELECT (SELECT count(*) FROM chunks) AS chunks, (SELECT count(*) FROM units) AS units"
        )
        print(
            f"\nalready populated ({counts['units']} units, {counts['chunks']} chunks) — "
            "nothing to do. Pass no flag, or use --force-reseed, to run it anyway."
        )
        await pool.close_pool()
        return 0

    # 1. Schema first: everything else writes into it.
    from scripts import migrate

    await step("schema and migrations", migrate.main())

    # 2. Seed data before the corpus, because the corpus is generated *from* the
    #    seed so the knowledge base and the systems of record cannot disagree.
    from db.seed import generate as seed_generate

    print("\n=== generating seed data ===")
    seed_generate.main()

    from db.seed import load_all

    await step("loading seed data", load_all.main())

    # 3. Corpus generated from the loaded data and the policy YAML.
    print("\n=== building the corpus ===")
    from scripts import build_corpus

    build_corpus.main()

    # 4. Chunk, embed and index. Idempotent by content hash.
    print("\n=== ingesting the corpus ===")
    from retrieval import ingest

    await ingest.run(collection=None, force=False, dry_run=False)

    # 5. Report what a reviewer needs to know before opening the UI.
    print("\n=== ready ===")
    mode = await pool.dense_mode()
    counts = await pool.fetch(
        """
        SELECT 'units' AS t, count(*) AS n FROM units
        UNION ALL SELECT 'bookings', count(*) FROM bookings
        UNION ALL SELECT 'tickets', count(*) FROM tickets
        UNION ALL SELECT 'leads', count(*) FROM leads
        UNION ALL SELECT 'documents', count(*) FROM documents
        UNION ALL SELECT 'corpus docs', count(*) FROM documents_corpus
        UNION ALL SELECT 'chunks', count(*) FROM chunks
        UNION ALL SELECT 'actors', count(*) FROM actors
        """
    )
    for row in counts:
        print(f"  {row['t']:<12} {row['n']}")
    print(f"  dense mode   {mode}")
    print("\nOpen http://localhost:3000 (or http://localhost:8000 for the API docs).")
    await pool.close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
