"""Property information agent.

Answers availability, configuration and price questions from the CRM and the
published price list — never from the model's own sense of what a 2BHK in
Whitefield costs.

The interesting behaviour is the no-match path (PRD UJ-1). Three different zero
results need three different answers, and conflating them is the most common way
a sales assistant becomes untrustworthy:

* the configuration exists here but nothing is available → sold out
* the configuration is not offered at this project → say so, do not substitute
* the project has not launched → no inventory has been released

Silent substitution ("no 2BHK, but here is a 3BHK!") is a fabrication about what
the customer asked for, so it is refused by construction: the agent reports the
absence, and offering an alternative is a separate, human-visible step.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from connectors import registry
from connectors.crm import InventoryQuery
from core.enums import Collection
from core.models import AgentFinding
from orchestration.state import CaseState

from agents.base import BaseAgent

#: Anything commercial is out of bounds for generated text (design rule #5 in
#: spirit: no code path invents a price concession).
COMMERCIAL_TERMS = (
    "discount", "waiver", "waive", "cashback", "free", "negotiate", "negotiable",
    "best price", "reduce the price", "lower the price", "offer me", "concession",
    "rebate", "commission",
)

_LAKH = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs)\b", re.I)
_CRORE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:cr|crore|crores)\b", re.I)
_PLAIN = re.compile(r"(?:under|below|upto|up to|within|budget of|max)\s*(?:inr|rs\.?|₹)?\s*([\d,]{5,})", re.I)


def parse_budget(text: str) -> int | None:
    """Read an Indian-format budget out of free text.

    Handled in code rather than left to the model: a mis-parsed budget silently
    changes which units are shown, and there is no citation that would reveal it.
    """
    if match := _CRORE.search(text):
        return int(float(match.group(1)) * 10_000_000)
    if match := _LAKH.search(text):
        return int(float(match.group(1)) * 100_000)
    if match := _PLAIN.search(text):
        return int(match.group(1).replace(",", ""))
    return None


class PropertyInfoOutput(BaseModel):
    summary: str
    next_action: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class PropertyInfoAgent(BaseAgent):
    name = "property_info"
    prompt_id = "property_info"
    collections = [Collection.PROPERTY_CATALOG.value, Collection.PRICING_SHEETS.value,
                   Collection.FAQ.value]

    async def _run(self, state: CaseState) -> AgentFinding:
        entities = state.classification.entities if state.classification else {}
        text = state.masked_input

        query = InventoryQuery(
            config=entities.get("config"),
            city=entities.get("city"),
            project_name=entities.get("project"),
            budget_max=parse_budget(text),
            limit=8,
        )
        result = await registry.crm().query_inventory(query, state.scope)

        chunks = await self.retrieve(state, text)
        facts: dict = {
            "query": query.model_dump(mode="json", exclude_none=True),
            "match_count": result.match_count,
            "total_in_project": result.total_in_project,
            "units": [u.model_dump(mode="json") for u in result.units],
            "price_ref": result.price_ref,
            "price_effective_date": (
                result.price_effective_date.isoformat() if result.price_effective_date else None
            ),
            "price_stale": self._price_is_stale(chunks, result.price_ref),
            "project_status": result.project_status,
            "config_exists_in_project": result.config_exists_in_project,
            "project_name": result.units[0].project_name if result.units else entities.get("project"),
            "commercial_request": any(term in text.lower() for term in COMMERCIAL_TERMS),
            "configs_available": sorted({u.config for u in result.units}),
            "planned_possession": self._possession_from_context(chunks),
            "note": result.note,
        }

        if result.match_count == 0 and not facts["commercial_request"]:
            # Not an error: a truthful "nothing matches, here is why" is the answer.
            output = await self.generate(state, self._variables(state, facts, chunks), PropertyInfoOutput)
            assert isinstance(output, PropertyInfoOutput)
            return AgentFinding(
                agent=self.name,
                status="ok",
                summary=output.summary,
                structured={
                    "match_count": 0,
                    "reason": (
                        "not_launched" if result.project_status == "pre_launch"
                        else "config_not_offered" if not result.config_exists_in_project
                        else "no_availability"
                    ),
                    "config_requested": query.config,
                    "budget_max": query.budget_max,
                    "substitution_offered": False,
                    "next_action": output.next_action,
                },
                citations=self.citations_from(chunks),
                confidence=min(output.confidence, 0.9),
            )

        output = await self.generate(state, self._variables(state, facts, chunks), PropertyInfoOutput)
        assert isinstance(output, PropertyInfoOutput)
        return AgentFinding(
            agent=self.name,
            status="ok",
            summary=output.summary,
            structured={
                "match_count": result.match_count,
                "unit_ids": [u.unit_id for u in result.units],
                "price_min": min((u.all_in_price for u in result.units), default=None),
                "price_max": max((u.all_in_price for u in result.units), default=None),
                "price_ref": result.price_ref,
                "price_effective_date": facts["price_effective_date"],
                "price_stale": facts["price_stale"],
                "commercial_request": facts["commercial_request"],
                "next_action": output.next_action,
            },
            citations=self.citations_from(chunks),
            confidence=output.confidence,
        )

    def _variables(self, state: CaseState, facts: dict, chunks: list) -> dict:
        return {
            "facts": facts,
            "context": self.context_block(chunks),
            "request": state.masked_input,
        }

    @staticmethod
    def _price_is_stale(chunks: list, price_ref: str | None) -> bool:
        """A price list past its freshness window must be disclosed as such."""
        for chunk in chunks:
            if chunk.collection == Collection.PRICING_SHEETS and chunk.is_stale:
                return True
            if price_ref and chunk.source_id == price_ref and chunk.is_stale:
                return True
        return False

    @staticmethod
    def _possession_from_context(chunks: list) -> str | None:
        for chunk in chunks:
            if match := re.search(
                r"possession[^.\n]*?(\d{4}-\d{2}-\d{2}|Q[1-4]\s*(?:FY)?\s*\d{2,4})",
                chunk.content,
                re.I,
            ):
                return match.group(1)
        return None
