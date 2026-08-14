"""Shared machinery for the seed loaders.

Loading is idempotent by design (ON CONFLICT DO UPDATE keyed on the primary key)
so `make seed` can be run repeatedly against a live database without producing
duplicates or requiring a drop. Columns present in the JSON but absent from the
table are dropped rather than raising, which lets the fixtures carry extra
annotation fields such as the persona `note` used by the demo script.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from api.config import get_settings

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"


def load_json(name: str) -> list[dict[str, Any]]:
    path = SEED_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing. Run `python -m db.seed.generate` first to build the fixtures."
        )
    return json.loads(path.read_text())


async def table_types(conn: Any, table: str) -> dict[str, str]:
    """Column name to Postgres data type, read from the catalogue.

    Types come from the database rather than from the column name. The first
    version of this module guessed from suffixes (`_date`, `_on`) and silently
    failed on `planned_possession` — a DATE column whose name matches no suffix —
    which surfaced as an unreadable asyncpg encoder error 400 rows into the load.
    The database already knows every type; asking it is both shorter and correct.
    """
    rows = await conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = $1",
        table,
    )
    return {r["column_name"]: r["data_type"] for r in rows}


async def table_columns(conn: Any, table: str) -> set[str]:
    return set(await table_types(conn, table))


def _coerce(value: Any, pg_type: str) -> Any:
    """Convert a JSON scalar into what asyncpg requires for this column type.

    asyncpg is strict by design: it will not accept a string for a DATE column or a
    float for NUMERIC. That strictness is useful, so this converts rather than
    working around it.
    """
    if value is None:
        return None

    if pg_type == "date":
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            return date.fromisoformat(value[:10])
        return value

    if pg_type in {"timestamp with time zone", "timestamp without time zone"}:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            # Accept a bare date for a timestamp column: midnight is the sensible
            # reading, and the fixtures use both forms.
            text = value.replace("Z", "+00:00")
            return datetime.fromisoformat(text) if "T" in text or " " in text else datetime.fromisoformat(f"{text[:10]}T00:00:00")
        return value

    if pg_type == "numeric":
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float, str)):
            return Decimal(str(value))
        return value

    if pg_type in {"jsonb", "json"}:
        # A codec is registered on every pooled connection (db/pool.py), so JSONB
        # takes a python object. Encoding here would double-encode.
        return json.loads(value) if isinstance(value, str) else value

    if pg_type == "boolean" and isinstance(value, str):
        return value.strip().lower() in {"true", "t", "yes", "1"}

    return value


async def upsert(conn: Any, table: str, rows: list[dict[str, Any]], pk: str) -> int:
    """Insert or update `rows` into `table`, keyed on `pk`. Returns row count."""
    if not rows:
        return 0
    types = await table_types(conn, table)
    columns = [c for c in rows[0] if c in types]
    if pk not in columns:
        raise ValueError(f"primary key {pk} not present in fixture for {table}")
    placeholders = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != pk)
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk}) DO UPDATE SET {updates}"
        if updates
        else f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk}) DO NOTHING"
    )
    payload = [[_coerce(row.get(c), types[c]) for c in columns] for row in rows]
    await conn.executemany(sql, payload)
    return len(rows)


async def insert_only(conn: Any, table: str, rows: list[dict[str, Any]]) -> int:
    """For child tables without a natural key (ticket events). Truncated first."""
    if not rows:
        return 0
    types = await table_types(conn, table)
    columns = [c for c in rows[0] if c in types]
    placeholders = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    payload = [[_coerce(row.get(c), types[c]) for c in columns] for row in rows]
    await conn.executemany(sql, payload)
    return len(rows)


async def connect() -> Any:
    import asyncpg

    return await asyncpg.connect(dsn=get_settings().asyncpg_dsn)


def report(label: str, n: int) -> None:
    print(f"  {label:24s} {n:>5}")
