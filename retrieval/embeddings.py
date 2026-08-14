"""Embedding providers.

The default provider is local and deterministic: hashed word and character
n-grams projected into a fixed-dimension unit vector. That choice is deliberate
for a prototype that has to run on a reviewer's laptop with no API key and no
model download, and it keeps eval numbers reproducible across machines. It is a
lexical-semantic approximation, not a sentence transformer, which is exactly why
retrieval is hybrid: BM25 carries exact-match strength for unit IDs and project
names, and the dense side contributes soft overlap.

Swap `EMBEDDING_PROVIDER=openai` for real embeddings without touching callers.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

import numpy as np

from api.config import get_logger, get_settings

log = get_logger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the to was were will with
    you your i we our they this these those my me""".split()
)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


def _bucket(feature: str, dim: int) -> tuple[int, float]:
    """Hash a feature to an index and a sign, the standard hashing-trick pair."""
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1.0 if (value >> 63) & 1 else -1.0


def local_embed(text: str, dim: int) -> list[float]:
    """Deterministic hashed embedding with sublinear term weighting."""
    vec = np.zeros(dim, dtype=np.float64)
    tokens = _tokens(text)
    if not tokens:
        return vec.tolist()

    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    for token, count in counts.items():
        weight = 1.0 + math.log(count)
        idx, sign = _bucket(f"w:{token}", dim)
        vec[idx] += sign * weight
        # Character 4-grams give partial credit for morphological variants
        # ("possession" / "possessions") and for identifiers ("BW-B-0704").
        padded = f"#{token}#"
        for i in range(max(1, len(padded) - 3)):
            gram = padded[i : i + 4]
            gidx, gsign = _bucket(f"c:{gram}", dim)
            vec[gidx] += gsign * weight * 0.35
    for i in range(len(tokens) - 1):
        bidx, bsign = _bucket(f"b:{tokens[i]}_{tokens[i + 1]}", dim)
        vec[bidx] += bsign * 0.8

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec.tolist()


class Embedder:
    """Provider-agnostic embedding facade."""

    def __init__(self) -> None:
        settings = get_settings()
        self.provider = settings.embedding_provider
        self.dim = settings.embedding_dim
        self.model = settings.embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.provider == "openai":
            try:
                return await self._openai(texts)
            except Exception as exc:  # noqa: BLE001 - degrade rather than fail ingest
                log.warning("embedding_provider_failed", provider="openai", error=str(exc))
        return [local_embed(t, self.dim) for t in texts]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    async def _openai(self, texts: list[str]) -> list[list[float]]:
        import httpx

        settings = get_settings()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": "text-embedding-3-small", "input": texts, "dimensions": self.dim},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        return [row["embedding"] for row in sorted(data, key=lambda r: r["index"])]


@lru_cache
def get_embedder() -> Embedder:
    return Embedder()


def cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(va @ vb / (na * nb))
