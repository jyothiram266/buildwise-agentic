"""Rerank the fused candidate set down to the top N that enter a prompt.

Default is a heuristic cross-scorer rather than a cross-encoder, for the same
reason the default embedder is local: a prototype that needs a 90 MB model
download before it answers anything is a prototype nobody runs. The interface is
the swappable part — set RERANKER=cross_encoder with the `rerank` extra installed
and the same call site gets a real model.

Falling back is logged as a degradation rather than passing silently, because a
silent quality drop is indistinguishable from a bug.
"""

from __future__ import annotations

import re
from functools import lru_cache

from api.config import get_logger, get_settings
from core.models import Chunk
from retrieval.text_split import estimate_tokens

log = get_logger(__name__)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]*")
_ID_LIKE = re.compile(r"\b(?:[A-Z]{2,}-[A-Z0-9\-]+|[A-Z]{2,}\d{2,}|\d{1,2}BHK)\b")


def _terms(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def heuristic_score(query: str, chunk: Chunk) -> float:
    """Lexical overlap, exact-identifier match, section-title match, freshness.

    Each component is bounded so no single signal can dominate; the identifier
    bonus is the largest because a query naming BW-B-0704 or PS-AUR-2026-07 almost
    always wants that exact document.
    """
    q_terms = _terms(query)
    if not q_terms:
        return 0.0
    c_terms = _terms(chunk.content)
    overlap = len(q_terms & c_terms) / len(q_terms)

    heading = _terms(chunk.section_heading or "") | _terms(chunk.source_name)
    heading_hit = len(q_terms & heading) / len(q_terms)

    ids = set(_ID_LIKE.findall(query))
    id_hit = 0.0
    if ids:
        present = sum(1 for i in ids if i.lower() in chunk.content.lower())
        id_hit = present / len(ids)

    length_penalty = 0.0
    tokens = chunk.token_estimate or estimate_tokens(chunk.content)
    if tokens < 40:
        length_penalty = 0.05  # a fragment rarely answers a real question
    stale_penalty = 0.08 if chunk.is_stale else 0.0

    return (
        0.45 * overlap
        + 0.20 * heading_hit
        + 0.35 * id_hit
        + 0.10 * min(1.0, chunk.score * 40)
        - length_penalty
        - stale_penalty
    )


@lru_cache
def _cross_encoder():
    from sentence_transformers import CrossEncoder

    settings = get_settings()
    return CrossEncoder(settings.rerank_model)


def rerank(query: str, chunks: list[Chunk], top_n: int | None = None) -> list[Chunk]:
    """Return the top `top_n` chunks, most relevant first."""
    settings = get_settings()
    top_n = top_n or settings.rerank_top_n
    if not chunks:
        return []

    if settings.reranker == "cross_encoder":
        try:
            model = _cross_encoder()
            pairs = [(query, c.content) for c in chunks]
            scores = model.predict(pairs)
            for chunk, score in zip(chunks, scores, strict=True):
                chunk.score = float(score)
            return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_n]
        except Exception as exc:  # noqa: BLE001
            log.warning("reranker_unavailable_using_fusion_order", error=str(exc))
            return chunks[:top_n]

    scored = []
    for chunk in chunks:
        chunk.score = heuristic_score(query, chunk)
        scored.append(chunk)
    return sorted(scored, key=lambda c: c.score, reverse=True)[:top_n]
