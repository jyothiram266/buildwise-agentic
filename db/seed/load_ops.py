"""Load maintenance tickets, ticket history and leads (P1-T4)."""

from __future__ import annotations

import asyncio

from db.seed._loader import connect, insert_only, load_json, report, upsert


async def run(conn=None) -> None:
    own = conn is None
    conn = conn or await connect()
    try:
        print("operations")
        report("tickets", await upsert(conn, "tickets", load_json("tickets.json"), "ticket_id"))
        # Events have no natural key, so replace the seeded history wholesale.
        await conn.execute("DELETE FROM ticket_events WHERE actor IN ('system','facility_plumbing','facility_electrical','facility_civil','vendor_lift','facility_housekeeping','facility_security','customer_relations')")
        report("ticket_events", await insert_only(conn, "ticket_events", load_json("ticket_events.json")))
        report("leads", await upsert(conn, "leads", load_json("leads.json"), "lead_id"))
    finally:
        if own:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
