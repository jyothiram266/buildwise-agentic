"""Turn a corpus markdown file into Chunk objects carrying full provenance.

Every chunk inherits the document's frontmatter, so the ACL predicate and the
freshness calculation both have what they need without a join back to the source.
That duplication is intentional: retrieval must not depend on a second lookup
that could be skipped.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from core.enums import Collection, Role
from core.models import Chunk
from retrieval.text_split import (
    TARGET_MAX_TOKENS,
    TARGET_MIN_TOKENS,
    estimate_tokens,
    find_injection_patterns,
    pack,
    split_sections,
    strip_frontmatter,
)

REQUIRED_KEYS = ("source_id", "source_name", "collection", "audience_scope")


class FrontmatterError(ValueError):
    """Raised at ingest time so a malformed document fails loudly, not silently."""


def parse_frontmatter(raw: str, path: Path) -> tuple[dict[str, Any], str]:
    fm_text, body = strip_frontmatter(raw)
    if not fm_text:
        raise FrontmatterError(f"{path}: missing YAML frontmatter")
    data = yaml.safe_load(fm_text) or {}
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise FrontmatterError(f"{path}: frontmatter missing {', '.join(missing)}")

    try:
        Collection(str(data["collection"]))
    except ValueError as exc:
        raise FrontmatterError(f"{path}: unknown collection {data['collection']!r}") from exc

    roles = data["audience_scope"]
    if isinstance(roles, str):
        roles = [r.strip() for r in roles.strip("[]").split(",") if r.strip()]
    unknown = [r for r in roles if r not in {x.value for x in Role}]
    if unknown:
        raise FrontmatterError(f"{path}: unknown roles in audience_scope: {unknown}")
    data["audience_scope"] = roles
    return data, body


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def chunk_document(path: Path) -> tuple[dict[str, Any], list[Chunk]]:
    """Chunk one markdown file. Returns (frontmatter, chunks)."""
    raw = path.read_text()
    meta, body = parse_frontmatter(raw, path)
    pieces = pack(split_sections(body), TARGET_MIN_TOKENS, TARGET_MAX_TOKENS)

    source_id = str(meta["source_id"])
    chunks: list[Chunk] = []
    for index, (heading, text) in enumerate(pieces):
        flagged = bool(find_injection_patterns(text))
        chunks.append(
            Chunk(
                chunk_id=f"{source_id}::{index:03d}",
                source_id=source_id,
                source_name=str(meta["source_name"]),
                collection=Collection(str(meta["collection"])),
                section_heading=heading,
                chunk_index=index,
                content=text,
                effective_date=_to_date(meta.get("effective_date")),
                freshness_days=int(meta.get("freshness_days", 365)),
                audience_scope=[Role(r) for r in meta["audience_scope"]],
                project_id=meta.get("project_id"),
                token_estimate=estimate_tokens(text),
                flagged_injection=flagged,
            )
        )
    meta["_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return meta, chunks
