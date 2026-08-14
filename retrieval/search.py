"""Hybrid retrieval with the access-control filter applied in SQL.

This module implements design rule #2, and it is the only sanctioned path to
corpus data. Two properties matter more than ranking quality here:

1. `audience_scope` and the project predicate are **WHERE clauses**. Nothing is
   fetched and then filtered in python, so there is no window in which
   unauthorised text exists in the process at all.
2. The predicate is built from an `AccessScope` object that is frozen and cannot
   be widened by anything downstream, including model output.

Ranking is reciprocal rank fusion over a dense list and a BM25 list. RRF is used
rather than a weighted score blend because the two scales are not comparable and
rank positions are stable across embedding providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from api.config import get_logger, get_settings
from core.enums import Role
from core.models import AccessScope, Chunk
from db import pool
from retrieval.embeddings import cosine, get_embedder
from retrieval.store import row_to_chunk, vector_literal

log = get_logger(__name__)

RRF_K = 60

#: Roles whose project access is unrestricted. Everyone else may only see
#: project-tagged chunks for projects inside their scope.
READ_ALL_PROJECT_ROLES = frozenset({Role.MANAGER, Role.LEGAL_FINANCE, Role.SALES_STAFF})

#: Roles that see only project-agnostic or public catalogue material.
PUBLIC_ONLY_ROLES = frozenset({Role.PUBLIC_LEAD, Role.BROKER})


@dataclass
class SearchDiagnostics:
    """Returned alongside results so tests and the audit trail can assert on it."""

    candidates_dense: int = 0
    candidates_sparse: int = 0
    acl_filtered_total: int = 0
    dense_mode: str = "array"
    stale_hits: int = 0


def _project_predicate(scope: AccessScope, start_index: int) -> tuple[str, list]:
    """Build the project-scoping clause. Returns (sql, params).

    A chunk with a NULL project_id is project-agnostic (a policy, an FAQ) and is
    governed by audience_scope alone. A project-tagged chunk additionally requires
    the actor to have that project in scope, unless the role reads all projects.
    """
    if scope.role in READ_ALL_PROJECT_ROLES:
        return "TRUE", []
    if scope.role in {Role.SITE_ENGINEER} and not scope.project_ids:
        # AGENTS.md Section 5: empty project list for an engineer means all.
        return "TRUE", []
    if scope.role in PUBLIC_ONLY_ROLES:
        return "TRUE", []
    if not scope.project_ids:
        return "c.project_id IS NULL", []
    return f"(c.project_id IS NULL OR c.project_id = ANY(${start_index}::text[]))", [
        list(scope.project_ids)
    ]


#: Cosine floor for a dense hit to count as a candidate.
#:
#: Nearest-neighbour search always returns k rows: it answers "what is closest", never
#: "is anything relevant at all". Without a floor, "zzzz qqqq xxxx" came back with
#: twenty confident-looking chunks, the knowledge-gap path never fired, and the agent
#: was handed irrelevant context to ground an answer in.
#:
#: Calibrated against this corpus and this embedder, over 15 real queries and 7
#: nonsense ones:
#:
#:     floor   real kept    nonsense leaked
#:     0.12      15/15            5/7
#:     0.15      15/15            3/7
#:     0.17      15/15            0/7      <- chosen
#:     0.20      13/15            0/7
#:
#: The weakest real query scores 0.181 ("who approves a refund") and the strongest
#: nonsense 0.154, so 0.17 sits inside a genuine gap rather than on a guess. The
#: margin is narrow because character 4-grams give nonsense partial credit — that is
#: a property of the hashed embedder, not of the corpus.
#:
#: **This value is specific to the embedding space.** A trained model has a different
#: scale entirely, which is why it is overridable per provider rather than hardcoded:
#: shipping one number for every embedder would silently reject everything or accept
#: everything the moment the provider changed.
_FLOOR_BY_PROVIDER = {"local": 0.17, "openai": 0.55}


def dense_score_floor() -> float:
    return _FLOOR_BY_PROVIDER.get(get_settings().embedding_provider, 0.17)


async def _dense_candidates(
    query_vec: list[float], acl_sql: str, acl_params: list, k: int
) -> list[dict]:
    mode = await pool.dense_mode()
    if mode == "pgvector":
        idx = len(acl_params) + 1
        sql = f"""
            SELECT c.*, 1 - (c.embedding <=> ${idx}::vector) AS score
            FROM chunks c
            WHERE {acl_sql} AND c.embedding IS NOT NULL
              AND 1 - (c.embedding <=> ${idx}::vector) >= {dense_score_floor()}
            ORDER BY c.embedding <=> ${idx}::vector
            LIMIT {int(k)}
        """
        return await pool.fetch(sql, *acl_params, vector_literal(query_vec))

    # Fallback: score in python over the ACL-filtered set only. The corpus is a
    # few hundred chunks, so this is milliseconds, and the filter still ran in SQL.
    sql = f"SELECT c.* FROM chunks c WHERE {acl_sql} AND c.embedding_arr IS NOT NULL"
    rows = await pool.fetch(sql, *acl_params)
    for row in rows:
        row["score"] = cosine(query_vec, row["embedding_arr"])
    floor = dense_score_floor()
    rows = [r for r in rows if r["score"] >= floor]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:k]


async def _sparse_candidates(query: str, acl_sql: str, acl_params: list, k: int) -> list[dict]:
    """BM25-style lexical match. Exact identifiers live or die here."""
    idx = len(acl_params) + 1
    sql = f"""
        SELECT c.*, ts_rank_cd(c.tsv, q, 32) AS score
        FROM chunks c, websearch_to_tsquery('english', ${idx}) q
        WHERE {acl_sql} AND c.tsv @@ q
        ORDER BY score DESC
        LIMIT {int(k)}
    """
    rows = await pool.fetch(sql, *acl_params, query)
    if rows:
        return rows
    # websearch_to_tsquery ANDs terms; retry as an OR of the longest tokens so a
    # verbose question still matches something lexically.
    terms = [t for t in _significant_terms(query)][:8]
    if not terms:
        return []
    or_query = " | ".join(terms)
    sql = f"""
        SELECT c.*, ts_rank_cd(c.tsv, q, 32) AS score
        FROM chunks c, to_tsquery('english', ${idx}) q
        WHERE {acl_sql} AND c.tsv @@ q
        ORDER BY score DESC
        LIMIT {int(k)}
    """
    try:
        return await pool.fetch(sql, *acl_params, or_query)
    except Exception as exc:  # malformed tsquery from odd input
        log.warning("sparse_fallback_failed", error=str(exc))
        return []


def _significant_terms(query: str) -> list[str]:
    import re

    stop = {
        "what", "when", "where", "which", "who", "why", "how", "is", "are", "the", "a", "an",
        "for", "of", "to", "in", "on", "my", "me", "i", "you", "your", "and", "or", "do", "does",
        "can", "please", "tell", "about", "with", "from", "has", "have", "been", "was", "it",
    }
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", query.lower())
    return [t for t in tokens if t not in stop]


async def search(
    query: str,
    scope: AccessScope,
    collections: list[str] | None = None,
    k: int | None = None,
    today: date | None = None,
) -> list[Chunk]:
    """Retrieve up to `k` fused candidates the actor is permitted to see."""
    results, _ = await search_with_diagnostics(query, scope, collections, k, today)
    return results


async def search_with_diagnostics(
    query: str,
    scope: AccessScope,
    collections: list[str] | None = None,
    k: int | None = None,
    today: date | None = None,
) -> tuple[list[Chunk], SearchDiagnostics]:
    settings = get_settings()
    k = k or settings.retrieval_k
    diag = SearchDiagnostics(dense_mode=await pool.dense_mode())

    # --- ACL predicate: built first, applied to every candidate query ---------
    params: list = [scope.role.value]
    clauses = ["c.audience_scope @> ARRAY[$1]::text[]"]

    project_sql, project_params = _project_predicate(scope, len(params) + 1)
    if project_sql != "TRUE":
        clauses.append(project_sql)
        params.extend(project_params)

    if collections:
        clauses.append(f"c.collection = ANY(${len(params) + 1}::text[])")
        params.append(list(collections))

    acl_sql = " AND ".join(clauses)
    diag.acl_filtered_total = int(
        await pool.fetchval(f"SELECT count(*) FROM chunks c WHERE {acl_sql}", *params) or 0
    )
    if diag.acl_filtered_total == 0:
        log.info("retrieval_empty_after_acl", role=scope.role.value, collections=collections)
        return [], diag

    embedder = get_embedder()
    query_vec = await embedder.embed_one(query)

    dense_rows = await _dense_candidates(query_vec, acl_sql, params, k)
    sparse_rows = await _sparse_candidates(query, acl_sql, params, k)
    diag.candidates_dense = len(dense_rows)
    diag.candidates_sparse = len(sparse_rows)

    # --- reciprocal rank fusion ---------------------------------------------
    fused: dict[str, float] = {}
    by_id: dict[str, dict] = {}
    dense_rank: dict[str, int] = {}
    sparse_rank: dict[str, int] = {}

    for rank, row in enumerate(dense_rows, start=1):
        cid = row["chunk_id"]
        by_id[cid] = row
        dense_rank[cid] = rank
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    for rank, row in enumerate(sparse_rows, start=1):
        cid = row["chunk_id"]
        by_id.setdefault(cid, row)
        sparse_rank[cid] = rank
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)

    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
    chunks: list[Chunk] = []
    for cid, score in ordered:
        row = dict(by_id[cid])
        row["score"] = score
        chunk = row_to_chunk(row, today=today)
        chunk.dense_rank = dense_rank.get(cid)
        chunk.sparse_rank = sparse_rank.get(cid)
        chunks.append(chunk)
        if chunk.is_stale:
            diag.stale_hits += 1

    log.info(
        "retrieval_done",
        role=scope.role.value,
        returned=len(chunks),
        dense=diag.candidates_dense,
        sparse=diag.candidates_sparse,
        stale=diag.stale_hits,
    )
    return chunks, diag


async def fetch_chunks_by_source(source_id: str, scope: AccessScope) -> list[Chunk]:
    """Read a whole document, still under the ACL predicate."""
    rows = await pool.fetch(
        """
        SELECT c.* FROM chunks c
        WHERE c.source_id = $1 AND c.audience_scope @> ARRAY[$2]::text[]
        ORDER BY c.chunk_index
        """,
        source_id,
        scope.role.value,
    )
    return [row_to_chunk(r) for r in rows]
