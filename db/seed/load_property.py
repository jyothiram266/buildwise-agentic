"""Load projects, towers and units (BUILD_PLAN P1-T1). Idempotent."""

from __future__ import annotations

import asyncio

from db.seed._loader import connect, load_json, report, upsert


async def run(conn=None) -> None:
    own = conn is None
    conn = conn or await connect()
    try:
        print("property inventory")
        report("projects", await upsert(conn, "projects", load_json("projects.json"), "project_id"))
        report("towers", await upsert(conn, "towers", load_json("towers.json"), "tower_id"))
        report("units", await upsert(conn, "units", load_json("units.json"), "unit_id"))
    finally:
        if own:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
