"""Corpus ingestion CLI.

    python -m retrieval.ingest --all
    python -m retrieval.ingest --collection policies
    python -m retrieval.ingest --dry-run          # chunk and report, touch nothing

Idempotent on document content hash: a re-run re-embeds only what changed. That
matters because embedding a whole corpus on every deploy is both slow and, with a
paid provider, expensive.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from api.config import get_logger, get_settings
from retrieval.chunker import FrontmatterError, chunk_document
from retrieval.embeddings import get_embedder
from retrieval.store import (
    corpus_stats,
    delete_chunks,
    insert_chunks,
    stored_document_hash,
    upsert_document,
)

log = get_logger(__name__)


async def ingest_path(path: Path, force: bool = False, dry_run: bool = False) -> tuple[str, int]:
    """Ingest one document. Returns (status, chunk_count)."""
    meta, chunks = chunk_document(path)
    source_id = str(meta["source_id"])
    doc_hash = meta["_hash"]

    if dry_run:
        return "dry-run", len(chunks)

    existing = await stored_document_hash(source_id)
    if existing == doc_hash and not force:
        return "unchanged", len(chunks)

    await upsert_document(
        source_id=source_id,
        source_name=str(meta["source_name"]),
        collection=str(meta["collection"]),
        effective_date=chunks[0].effective_date if chunks else None,
        freshness_days=int(meta.get("freshness_days", 365)),
        audience_scope=list(meta["audience_scope"]),
        project_id=meta.get("project_id"),
        path=str(path),
        doc_hash=doc_hash,
    )
    await delete_chunks(source_id)
    embedder = get_embedder()
    vectors = await embedder.embed([c.content for c in chunks])
    await insert_chunks(chunks, vectors)
    return ("reingested" if existing else "new"), len(chunks)


async def run(collection: str | None, force: bool, dry_run: bool) -> int:
    settings = get_settings()
    root = settings.corpus_dir
    if collection:
        paths = sorted((root / collection).glob("*.md"))
        if not paths:
            print(f"no documents found in {root / collection}")
            return 1
    else:
        paths = sorted(root.rglob("*.md"))

    totals = {"new": 0, "reingested": 0, "unchanged": 0, "dry-run": 0}
    chunk_total = 0
    flagged = 0
    failures: list[str] = []

    for path in paths:
        try:
            status, count = await ingest_path(path, force=force, dry_run=dry_run)
        except FrontmatterError as exc:
            failures.append(str(exc))
            continue
        totals[status] += 1
        chunk_total += count
        _, chunks = chunk_document(path)
        flagged += sum(1 for c in chunks if c.flagged_injection)
        print(f"  {status:11s} {path.parent.name}/{path.name}  ({count} chunks)")

    print(
        f"\ndocuments: {len(paths)}  chunks: {chunk_total}  "
        f"new={totals['new']} reingested={totals['reingested']} unchanged={totals['unchanged']}"
    )
    if flagged:
        print(f"flagged for review: {flagged} chunk(s) contain instruction-like text")
    if failures:
        print("\nfailed:")
        for f in failures:
            print(f"  {f}")
        return 1
    if not dry_run:
        stats = await corpus_stats()
        print(f"stored chunks: {stats['total_chunks']} (dense mode: {stats['dense_mode']})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest the BuildWise knowledge base")
    parser.add_argument("--collection", help="ingest a single collection directory")
    parser.add_argument("--all", action="store_true", help="ingest every collection")
    parser.add_argument("--force", action="store_true", help="re-embed unchanged documents")
    parser.add_argument("--dry-run", action="store_true", help="chunk and report without writing")
    args = parser.parse_args()
    if not args.all and not args.collection and not args.dry_run:
        parser.error("pass --all, --collection <name>, or --dry-run")
    return asyncio.run(run(args.collection, args.force, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
