"""Async Postgres access.

Raw asyncpg rather than an ORM, deliberately: every ACL predicate in this system
is a WHERE clause that a reviewer needs to be able to read at a glance. Hiding
those behind relationship loading would make design rule #2 hard to audit.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Iterable

from api.config import get_logger, get_settings
from core.errors import ConnectorError

log = get_logger(__name__)

#: One pool per event loop, keyed by the loop object.
#:
#: An asyncpg pool holds sockets bound to the loop that created them, so a single
#: module-level pool is only correct in a process with exactly one loop. The test
#: runner creates a fresh loop per test, which meant the pool from the first test
#: was reused by the second against a closed loop — 37 tests failed with "Event
#: loop is closed" and the real bug was here, not in the tests. Keying by loop is
#: correct for both cases: the API has one loop and gets one pool.
_pools: dict[Any, Any] = {}
_dense_mode: str | None = None


async def get_pool() -> Any:
    """Return the connection pool for the running event loop, creating it if needed."""
    loop = asyncio.get_running_loop()
    existing = _pools.get(loop)
    if existing is not None and not existing._closed:  # noqa: SLF001 - no public accessor
        return existing

    try:
        import asyncpg
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ConnectorError("asyncpg is not installed; run `make install`") from exc

    settings = get_settings()
    pool = await asyncpg.create_pool(
        dsn=settings.asyncpg_dsn,
        min_size=1,
        max_size=10,
        command_timeout=30,
        init=_init_connection,
    )
    _pools[loop] = pool
    log.info("db_pool_created", dsn_host=settings.asyncpg_dsn.rsplit("@", 1)[-1])
    return pool


async def _init_connection(conn: Any) -> None:
    """Register JSON codecs so JSONB columns round-trip as python objects.

    Because this codec is registered, callers must pass **python objects** to JSONB
    parameters, never a pre-encoded JSON string: `json.dumps` at the call site would
    be applied a second time here, storing a quoted string where an object belongs.
    Several call sites did exactly that, and nothing failed loudly — the data was
    simply wrong when read back. `to_jsonb` below is the intended helper.
    """
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def close_pool() -> None:
    """Close the pool belonging to the running loop, if there is one."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop: nothing of ours can be open
        return
    pool = _pools.pop(loop, None)
    if pool is not None and not pool._closed:  # noqa: SLF001
        await pool.close()


def to_jsonb(value: Any) -> Any:
    """Prepare a value for a JSONB parameter.

    Round-trips through the JSON encoder so non-serialisable members (dates,
    Decimals, enums) become primitives, then hands back an object for the codec to
    encode exactly once.
    """
    return json.loads(json.dumps(value, default=str))


async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)
    return dict(row) if row else None


async def fetchval(sql: str, *args: Any) -> Any:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


async def execute(sql: str, *args: Any) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(sql, *args)


async def executemany(sql: str, rows: Iterable[Iterable[Any]]) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(sql, list(rows))


async def dense_mode() -> str:
    """'pgvector' when the extension is present, otherwise 'array'.

    Cached because it cannot change without a migration, and the retrieval hot
    path checks it on every search.
    """
    global _dense_mode
    if _dense_mode is not None:
        return _dense_mode
    try:
        value = await fetchval("SELECT value FROM system_meta WHERE key = 'dense_mode'")
    except Exception:  # system_meta does not exist yet
        value = None
    if value:
        # Only cache a value that was actually read. Caching the fallback was a real
        # bug: the API starts before migrations run, so it cached "array" and kept
        # using it for the process lifetime even after the schema declared pgvector —
        # silently downgrading retrieval with nothing in the logs to say why.
        _dense_mode = value
        return _dense_mode
    return "array"


def reset_dense_mode() -> None:
    """Drop the cached mode. Called by the migration path after it sets the value."""
    global _dense_mode
    _dense_mode = None


async def healthcheck() -> dict[str, Any]:
    """Used by GET /health; reports rather than raises."""
    try:
        one = await fetchval("SELECT 1")
        chunks = await fetchval("SELECT count(*) FROM chunks")
        cases = await fetchval("SELECT count(*) FROM cases")
        return {
            "ok": one == 1,
            "dense_mode": await dense_mode(),
            "chunks": int(chunks or 0),
            "cases": int(cases or 0),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
