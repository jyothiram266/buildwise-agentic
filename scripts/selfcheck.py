"""Pre-demo check. Answers one question: will the demo work right now?

Every check prints what it found and, on failure, the command that fixes it. A
health check that says "FAILED" without a next step wastes the five minutes before
a presentation.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CHECKS: list[tuple[str, str]] = []


def record(name: str, ok: bool, detail: str, fix: str = "") -> bool:
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {name}: {detail}")
    if not ok and fix:
        print(f"         fix: {fix}")
    CHECKS.append((name, "ok" if ok else "fail"))
    return ok


async def main() -> int:
    from api.config import get_settings
    from db import pool

    settings = get_settings()
    print("BuildWise selfcheck\n")

    # --- configuration ----------------------------------------------------
    print("configuration")
    record("provider", True, f"llm={settings.llm_provider}, embeddings={settings.embedding_provider}")
    if settings.llm_provider == "anthropic":
        record(
            "api key",
            bool(settings.anthropic_api_key),
            "present" if settings.anthropic_api_key else "missing",
            "set ANTHROPIC_API_KEY in .env, or use LLM_PROVIDER=mock",
        )

    # --- prompts and policies (fail at boot, not per request) -------------
    print("\nprompts and policies")
    try:
        from governance.policy_registry import REQUIRED_PROMPTS, get_registry

        registry = get_registry()
        registry.validate_all(REQUIRED_PROMPTS)
        record("prompt registry", True, f"{len(registry.list_prompts())} prompts resolved")
        for policy_id in ("severity_matrix", "escalation_matrix", "warranty_policy"):
            record(f"policy {policy_id}", True, f"v{registry.policy_version(policy_id)}")
    except Exception as exc:  # noqa: BLE001
        record("prompt registry", False, str(exc), "check llm/prompts/*.md frontmatter")
        return 1

    # --- database ---------------------------------------------------------
    print("\ndatabase")
    try:
        await pool.get_pool()
        health = await pool.healthcheck()
        record(
            "postgres",
            bool(health.get("ok")),
            f"reachable · {health.get('chunks', 0)} chunks, {health.get('cases', 0)} cases"
            if health.get("ok")
            else str(health.get("error", ""))[:60],
            "docker compose up -d postgres",
        )
    except Exception as exc:  # noqa: BLE001
        record("postgres", False, str(exc)[:80], "make up")
        return 1

    tables = {
        "units": "make bootstrap",
        "bookings": "make bootstrap",
        "actors": "make seed",
        "chunks": "make ingest",
        "documents_corpus": "make ingest",
    }
    for table, fix in tables.items():
        try:
            count = int(await pool.fetchval(f"SELECT count(*) FROM {table}") or 0)
            record(f"table {table}", count > 0, f"{count} rows", fix)
        except Exception as exc:  # noqa: BLE001
            record(f"table {table}", False, str(exc)[:60], fix)

    record("dense retrieval", True, await pool.dense_mode())

    # --- connectors -------------------------------------------------------
    print("\nsystems of record")
    try:
        from connectors import registry as connector_registry

        for health in await connector_registry.health_all():
            record(
                # The Health model calls this `name`; reading `system` printed
                # "connector None" for all five.
                f"connector {health.get('name') or health.get('system')}",
                bool(health.get("ok")),
                health.get("detail") or "reachable",
                "docker compose up -d mock-connectors",
            )
    except Exception as exc:  # noqa: BLE001
        record("connectors", False, str(exc)[:80], "docker compose up -d mock-connectors")

    # --- the demo personas must exist -------------------------------------
    print("\ndemo personas")
    for actor_id in ("LEAD-0001", "CUST-4471", "CUST-4802", "VEN-CEM-01", "STF-ENG-01", "STF-MGR-01"):
        # Every check is individually guarded. A selfcheck that dies on the first
        # missing table tells you about one problem when it could have told you
        # about all of them, which is the opposite of what a preflight is for.
        try:
            found = await pool.fetchval(
                "SELECT count(*) FROM actors WHERE actor_id = $1", actor_id
            )
            record(f"actor {actor_id}", bool(found), "present" if found else "missing", "make seed")
        except Exception as exc:  # noqa: BLE001
            record(f"actor {actor_id}", False, str(exc)[:60], "run bootstrap first")

    # --- the deliberate demo conditions -----------------------------------
    print("\nseeded demo conditions")

    async def probe(label: str, sql: str, expect, detail_fmt: str, fix: str = "run bootstrap") -> None:
        try:
            value = await pool.fetchval(sql)
        except Exception as exc:  # noqa: BLE001
            record(label, False, str(exc)[:60], fix)
            return
        record(label, expect(value), detail_fmt.format(value=value), fix)

    await probe(
        "Aurora has no 1BHK",
        "SELECT count(*) FROM units WHERE project_id = 'PRJ-AUR' AND config = '1BHK'",
        lambda v: v == 0,
        "{value} units (expected 0)",
    )
    await probe(
        "Tower B revision approved",
        "SELECT revised_approved FROM towers WHERE tower_id = 'TWR-AUR-B'",
        lambda v: v is True,
        "{value}",
    )
    await probe(
        "Tower E revision NOT approved",
        "SELECT revised_approved FROM towers WHERE tower_id = 'TWR-PLM-E'",
        lambda v: v is False,
        "{value}",
    )
    await probe(
        "injection probes present",
        "SELECT count(*) FROM site_reports WHERE contains_injection_probe",
        lambda v: (v or 0) > 0,
        "{value} reports",
    )
    await probe(
        "stale price list present",
        """
        SELECT count(*) FROM documents_corpus
        WHERE collection = 'pricing_sheets'
          AND effective_date < CURRENT_DATE - freshness_days
        """,
        lambda v: (v or 0) > 0,
        "{value} sheets past their window",
        "make ingest",
    )

    await pool.close_pool()

    failed = [name for name, status in CHECKS if status == "fail"]
    print("\n" + "-" * 60)
    if failed:
        print(f"{len(failed)} check(s) failed: {', '.join(failed)}")
        return 1
    print(f"all {len(CHECKS)} checks passed — the demo is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
