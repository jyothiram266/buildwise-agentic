"""Apply db/schema.sql then every numbered migration, in order.

Idempotent by construction: schema.sql uses IF NOT EXISTS and the migrations use
CREATE OR REPLACE, so running this against a live database is safe.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import get_settings  # noqa: E402


async def main() -> int:
    import asyncpg

    settings = get_settings()
    root = Path(__file__).resolve().parent.parent
    schema = root / "db" / "schema.sql"
    migrations = sorted((root / "db" / "migrations").glob("*.sql"))

    conn = await asyncpg.connect(dsn=settings.asyncpg_dsn)
    try:
        print(f"applying {schema.relative_to(root)}")
        await conn.execute(schema.read_text())
        for path in migrations:
            print(f"applying {path.relative_to(root)}")
            await conn.execute(path.read_text())
        mode = await conn.fetchval("SELECT value FROM system_meta WHERE key = 'dense_mode'")
        # Any process that read the mode before this point cached a fallback, so
        # invalidate it here rather than leaving a stale value in memory.
        from db import pool

        pool.reset_dense_mode()
        print(f"schema applied. dense retrieval mode: {mode}")
        if mode != "pgvector":
            print(
                "NOTE: pgvector was not available, so dense scoring runs in python over "
                "ACL-filtered rows. Access control is unaffected (it stays in SQL)."
            )
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
