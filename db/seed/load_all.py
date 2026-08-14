"""Load every fixture in dependency order.

Regenerates the JSON first when it is missing, so a clean checkout needs one
command rather than two.
"""

from __future__ import annotations

import asyncio

from db.seed import load_customers, load_ops, load_projects, load_property
from db.seed._loader import SEED_DIR, connect, load_json, report, upsert


async def main() -> None:
    if not (SEED_DIR / "units.json").exists():
        from db.seed import generate

        generate.main()

    conn = await connect()
    try:
        await load_property.run(conn)
        await load_customers.run(conn)
        await load_projects.run(conn)
        await load_ops.run(conn)

        # The mock identity directory lives in Postgres so the role switcher and
        # RBAC resolution read from one place.
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS actors (
                actor_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                booking_ids TEXT[] NOT NULL DEFAULT '{}',
                unit_ids TEXT[] NOT NULL DEFAULT '{}',
                project_ids TEXT[] NOT NULL DEFAULT '{}',
                work_package_ids TEXT[] NOT NULL DEFAULT '{}'
            )
            """
        )
        print("identity")
        report("actors", await upsert(conn, "actors", load_json("actors.json"), "actor_id"))

        counts = await conn.fetch(
            """
            SELECT 'units' t, count(*) n FROM units
            UNION ALL SELECT 'bookings', count(*) FROM bookings
            UNION ALL SELECT 'tickets', count(*) FROM tickets
            UNION ALL SELECT 'leads', count(*) FROM leads
            UNION ALL SELECT 'milestones', count(*) FROM milestones
            UNION ALL SELECT 'site_reports', count(*) FROM site_reports
            """
        )
        print("\nloaded:", ", ".join(f"{r['t']}={r['n']}" for r in counts))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
