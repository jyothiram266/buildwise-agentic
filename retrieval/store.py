"""Chunk persistence.

Handles both dense back-ends: a real `vector(384)` column when pgvector loaded,
and a `double precision[]` fallback when it did not. Access control is unaffected
by that choice, because the ACL filter is a SQL predicate on `audience_scope`
either way — only the ranking arithmetic moves.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from api.config import get_logger
from core.enums import Collection, Role
from core.models import Chunk
from db import pool

log = get_logger(__name__)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def is_stale(effective: date | None, freshness_days: int, today: date | None = None) -> bool:
    """A source past its freshness window is usable but must be labelled."""
    if effective is None:
        return False
    today = today or date.today()
    return (today - effective).days > freshness_days


async def upsert_document(
    *,
    source_id: str,
    source_name: str,
    collection: str,
    effective_date: date | None,
    freshness_days: int,
    audience_scope: list[str],
    project_id: str | None,
    path: str,
    doc_hash: str,
) -> None:
    await pool.execute(
        """
        INSERT INTO documents_corpus (source_id, source_name, collection, effective_date,
                                      freshness_days, audience_scope, project_id, path, content_hash)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (source_id) DO UPDATE SET
            source_name = EXCLUDED.source_name,
            collection = EXCLUDED.collection,
            effective_date = EXCLUDED.effective_date,
            freshness_days = EXCLUDED.freshness_days,
            audience_scope = EXCLUDED.audience_scope,
            project_id = EXCLUDED.project_id,
            path = EXCLUDED.path,
            content_hash = EXCLUDED.content_hash,
            ingested_at = now()
        """,
        source_id,
        source_name,
        collection,
        effective_date,
        freshness_days,
        audience_scope,
        project_id,
        path,
        doc_hash,
    )


async def stored_document_hash(source_id: str) -> str | None:
    return await pool.fetchval(
        "SELECT content_hash FROM documents_corpus WHERE source_id = $1", source_id
    )


async def delete_chunks(source_id: str) -> None:
    await pool.execute("DELETE FROM chunks WHERE source_id = $1", source_id)


async def insert_chunks(chunks: list[Chunk], embeddings: list[list[float]]) -> int:
    """Insert chunk rows with both text-search and dense representations."""
    if not chunks:
        return 0
    mode = await pool.dense_mode()
    rows = []
    for chunk, vector in zip(chunks, embeddings, strict=True):
        rows.append(
            (
                chunk.chunk_id,
                chunk.source_id,
                chunk.source_name,
                chunk.collection.value,
                chunk.section_heading,
                chunk.chunk_index,
                chunk.content,
                chunk.effective_date,
                chunk.freshness_days,
                [r.value for r in chunk.audience_scope],
                chunk.project_id,
                chunk.token_estimate,
                chunk.flagged_injection,
                content_hash(chunk.content),
                vector,
            )
        )

    if mode == "pgvector":
        sql = """
            INSERT INTO chunks (chunk_id, source_id, source_name, collection, section_heading,
                                chunk_index, content, effective_date, freshness_days,
                                audience_scope, project_id, token_estimate, flagged_injection,
                                content_hash, embedding_arr, embedding, tsv)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$15::double precision[]::vector,
                    to_tsvector('english', $3 || ' ' || coalesce($5,'') || ' ' || $7))
            ON CONFLICT (chunk_id) DO UPDATE SET
                content = EXCLUDED.content, embedding_arr = EXCLUDED.embedding_arr,
                embedding = EXCLUDED.embedding, tsv = EXCLUDED.tsv,
                content_hash = EXCLUDED.content_hash, flagged_injection = EXCLUDED.flagged_injection
        """
    else:
        sql = """
            INSERT INTO chunks (chunk_id, source_id, source_name, collection, section_heading,
                                chunk_index, content, effective_date, freshness_days,
                                audience_scope, project_id, token_estimate, flagged_injection,
                                content_hash, embedding_arr, tsv)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                    to_tsvector('english', $3 || ' ' || coalesce($5,'') || ' ' || $7))
            ON CONFLICT (chunk_id) DO UPDATE SET
                content = EXCLUDED.content, embedding_arr = EXCLUDED.embedding_arr,
                tsv = EXCLUDED.tsv, content_hash = EXCLUDED.content_hash,
                flagged_injection = EXCLUDED.flagged_injection
        """
    await pool.executemany(sql, rows)
    return len(rows)


def row_to_chunk(row: dict[str, Any], today: date | None = None) -> Chunk:
    """Map a DB row onto the canonical Chunk, computing staleness on the way out."""
    audience = []
    for value in row.get("audience_scope") or []:
        try:
            audience.append(Role(value))
        except ValueError:
            continue
    effective = row.get("effective_date")
    freshness = int(row.get("freshness_days") or 365)
    return Chunk(
        chunk_id=row["chunk_id"],
        source_id=row["source_id"],
        source_name=row["source_name"],
        collection=Collection(row["collection"]),
        section_heading=row.get("section_heading"),
        chunk_index=int(row.get("chunk_index") or 0),
        content=row["content"],
        effective_date=effective,
        freshness_days=freshness,
        audience_scope=audience,
        project_id=row.get("project_id"),
        token_estimate=int(row.get("token_estimate") or 0),
        is_stale=is_stale(effective, freshness, today),
        score=float(row.get("score") or 0.0),
        flagged_injection=bool(row.get("flagged_injection")),
    )


async def corpus_stats() -> dict[str, Any]:
    rows = await pool.fetch(
        """
        SELECT collection, count(*) AS chunks, count(DISTINCT source_id) AS sources
        FROM chunks GROUP BY collection ORDER BY collection
        """
    )
    total = sum(r["chunks"] for r in rows)
    return {"total_chunks": total, "by_collection": rows, "dense_mode": await pool.dense_mode()}


async def log_kb_gap(case_id: str | None, query: str, collections: list[str], role: str) -> None:
    """Every empty retrieval is a knowledge-base backlog item, not just a refusal."""
    await pool.execute(
        "INSERT INTO kb_gaps (case_id, query, collections, role) VALUES ($1,$2,$3,$4)",
        case_id,
        query[:500],
        collections,
        role,
    )


def vector_literal(vec: list[float]) -> str:
    """pgvector accepts a bracketed JSON-ish literal for parameterised queries."""
    return json.dumps([round(v, 6) for v in vec])
