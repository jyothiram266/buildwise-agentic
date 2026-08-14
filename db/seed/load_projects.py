"""Load construction milestones, site reports, vendors, packages, blockers (P1-T3)."""

from __future__ import annotations

import asyncio

from db.seed._loader import connect, load_json, report, upsert


async def run(conn=None) -> None:
    own = conn is None
    conn = conn or await connect()
    try:
        print("construction progress")
        report("vendors", await upsert(conn, "vendors", load_json("vendors.json"), "vendor_id"))
        report(
            "work_packages",
            await upsert(conn, "work_packages", load_json("work_packages.json"), "work_package_id"),
        )
        report("milestones", await upsert(conn, "milestones", load_json("milestones.json"), "milestone_id"))
        report("site_reports", await upsert(conn, "site_reports", load_json("site_reports.json"), "report_id"))
        report("blockers", await upsert(conn, "blockers", load_json("blockers.json"), "blocker_id"))
    finally:
        if own:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
