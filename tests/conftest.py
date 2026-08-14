"""Shared fixtures.

Tests split into three groups by what they need:

* `tests/unit` — pure functions only. No database, no network, no model. These run
  in CI on every commit and are the ones that guard the deterministic policy.
* `tests/integration` — needs Postgres and the mock connector service. Marked
  `integration` so they can be skipped locally without hiding failures.
* `tests/security` — ACL and prompt-injection properties. Marked `security`.

The LLM provider is forced to `mock` for the whole session. A test suite whose
results depend on a network call to a model is not a test suite.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")
os.environ.setdefault("APP_ENV", "dev")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


#: Tables that hold per-case state. Seed data (units, bookings, leads, chunks) is
#: deliberately not here: tests read it and must not have to reload it.
CASE_STATE_TABLES = (
    "agent_trace",
    "escalations",
    "review_queue",
    "approval_tokens",
    "team_notifications",
    "kb_gaps",
    "conversation_turns",
    "cases",
)


@pytest.fixture(autouse=True)
def _isolate_case_state(request):
    """Give every database-backed test a clean slate for case state.

    Three tests failed without this, and all three failures were the tests' fault
    rather than the product's:

    * a prospect's availability question came back tier 2 instead of tier 0, because
      earlier tests in the same session had created cases for the same actor and the
      repeated-contact rule fired — correct behaviour, wrong assumption in the test
    * two escalation tests inserted a fixed `esc_id` with `ON CONFLICT DO NOTHING`,
      so a resolved row left behind by the *previous run* silently survived and the
      new row was never created

    The second one is the more instructive: `ON CONFLICT DO NOTHING` made stale state
    look like success. Order-dependent tests that pass in isolation and fail in a
    suite are worse than failing tests, because the failure moves around.

    TRUNCATE rather than DELETE, because `agent_trace` has a BEFORE DELETE trigger
    enforcing append-only. TRUNCATE does not fire row triggers, so the guarantee
    stands in production while tests can still reset.

    Deliberately a *sync* fixture that opens its own short-lived loop. Some tests in
    the security suite are synchronous (pattern matching needs no database), and an
    async autouse fixture would fail for them. Doing the reset in its own loop keeps
    the fixture usable by every test regardless of how the test itself is written.
    """
    # Gated on `integration` alone. Several security tests are pure pattern matching
    # and need no database; making them depend on one would turn a fast, always-runnable
    # check into a skip whenever the stack is down.
    needs_db = request.node.get_closest_marker("integration") is not None
    if not needs_db:
        yield
        return

    import asyncio

    async def reset() -> None:
        from db import pool

        try:
            await pool.execute(
                f"TRUNCATE {', '.join(CASE_STATE_TABLES)} RESTART IDENTITY CASCADE"
            )
        finally:
            # The pool created for this loop must not outlive it.
            await pool.close_pool()

    try:
        asyncio.run(reset())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database not reachable for case-state reset: {exc}")
    yield


@pytest.fixture(autouse=True)
async def _close_db_pool(anyio_backend):
    """Release the connection pool at the end of every async test.

    The test runner gives each test its own event loop, and an asyncpg pool is bound
    to the loop that created it. `db.pool` now keys pools by loop, so this fixture is
    belt-and-braces: it stops a session accumulating one idle pool per test, which is
    how a long suite runs out of Postgres connections.
    """
    yield
    from db import pool

    await pool.close_pool()


@pytest.fixture
def scopes() -> dict:
    """One scope per role, matching the seeded identity directory."""
    from core.enums import Role
    from core.models import AccessScope

    return {
        "public_lead": AccessScope(actor_id="LEAD-0001", role=Role.PUBLIC_LEAD),
        "customer": AccessScope(
            actor_id="CUST-4471",
            role=Role.CUSTOMER,
            booking_ids=["BK-9901"],
            unit_ids=["BW-B-0704"],
            project_ids=["PRJ-AUR"],
        ),
        "resident": AccessScope(
            actor_id="CUST-4802",
            role=Role.RESIDENT,
            booking_ids=["BK-9902"],
            unit_ids=["BW-D-0704"],
            project_ids=["PRJ-PLM"],
        ),
        "broker": AccessScope(actor_id="BRK-201", role=Role.BROKER),
        "contractor": AccessScope(
            actor_id="VEN-CEM-01",
            role=Role.CONTRACTOR,
            project_ids=["PRJ-AUR"],
            work_package_ids=["WP-AUR-B-STR"],
        ),
        "sales_staff": AccessScope(actor_id="STF-SALES-01", role=Role.SALES_STAFF),
        "site_engineer": AccessScope(
            actor_id="STF-ENG-01", role=Role.SITE_ENGINEER, project_ids=["PRJ-AUR"]
        ),
        "legal_finance": AccessScope(actor_id="STF-LEG-01", role=Role.LEGAL_FINANCE),
        "manager": AccessScope(actor_id="STF-MGR-01", role=Role.MANAGER),
    }


@pytest.fixture
def state_factory(scopes):
    """Build a CaseState without touching the database."""
    from core.enums import Channel
    from orchestration.state import CaseState

    def make(text: str, role: str = "customer", case_id: str = "CASE-TEST-0001") -> CaseState:
        return CaseState(
            case_id=case_id,
            channel=Channel.WEB_CHAT,
            scope=scopes[role],
            raw_input=text,
            masked_input=text,
        )

    return make
