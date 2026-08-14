"""Retrieval behaviour against the ingested corpus."""

from __future__ import annotations

import pytest

from core.enums import Collection
from retrieval import search

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_hybrid_search_returns_relevant_chunks(scopes) -> None:
    chunks = await search.search("what documents are needed for registration", scopes["customer"])
    assert chunks
    assert any(chunk.collection == Collection.DOC_CHECKLISTS for chunk in chunks)


async def test_diagnostics_report_both_retrieval_arms(scopes) -> None:
    _, diag = await search.search_with_diagnostics("possession timeline", scopes["customer"])
    assert diag.dense_mode in {"pgvector", "array"}
    # Field names follow SearchDiagnostics: candidates_dense / candidates_sparse.
    assert diag.candidates_dense >= 0
    assert diag.candidates_sparse >= 0
    assert diag.acl_filtered_total >= 0


async def test_stale_pricing_sheet_is_flagged(scopes) -> None:
    """The Aurora price list is seeded past its 7-day freshness window on purpose."""
    chunks = await search.search(
        "Aurora Heights price list per square foot", scopes["sales_staff"],
        collections=[Collection.PRICING_SHEETS.value],
    )
    assert chunks
    assert any(chunk.is_stale for chunk in chunks)


async def test_nonsense_query_returns_nothing_and_logs_a_gap(scopes) -> None:
    from db import pool

    before = int(await pool.fetchval("SELECT count(*) FROM kb_gaps") or 0)
    from agents.property_info import PropertyInfoAgent
    from orchestration.state import CaseState
    from core.enums import Channel

    agent = PropertyInfoAgent()
    state = CaseState(
        case_id="CASE-GAP-TEST",
        channel=Channel.WEB_CHAT,
        scope=scopes["customer"],
        raw_input="zzzz qqqq xxxx",
        masked_input="zzzz qqqq xxxx",
    )
    await agent.retrieve(state, "zzzz qqqq xxxx vvvv")
    after = int(await pool.fetchval("SELECT count(*) FROM kb_gaps") or 0)
    assert after > before, "an empty retrieval must be logged as a content gap"
