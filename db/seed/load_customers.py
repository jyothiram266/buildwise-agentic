"""Load customers, bookings, payment milestones and documents (P1-T2)."""

from __future__ import annotations

import asyncio

from db.seed._loader import connect, load_json, report, upsert


async def run(conn=None) -> None:
    own = conn is None
    conn = conn or await connect()
    try:
        print("customers and bookings")
        report("customers", await upsert(conn, "customers", load_json("customers.json"), "customer_id"))
        report("bookings", await upsert(conn, "bookings", load_json("bookings.json"), "booking_id"))
        report(
            "payment_milestones",
            await upsert(conn, "payment_milestones", load_json("payment_milestones.json"), "milestone_id"),
        )
        report("documents", await upsert(conn, "documents", load_json("documents.json"), "doc_id"))
    finally:
        if own:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
