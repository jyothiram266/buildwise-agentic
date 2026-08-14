"""Provider-agnostic LLM client.

Responsibilities kept in one place so no agent has to think about them:
model tiering, timeouts, retry with backoff, per-case token and cost accounting,
and prompt-version resolution for the audit trail.

The default provider is `mock`: a deterministic, offline, rule-based generator in
`llm/mock_provider.py`. It exists so the whole system — graph, governance,
evaluation, UI — runs and is testable with no API key and no network. Its outputs
are honest stand-ins, not model quality, and every eval report states which
provider produced the numbers.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from api.config import get_logger, get_settings
from core.errors import BuildWiseError
from core.models import LLMResult, LLMUsage
from governance.policy_registry import get_registry

log = get_logger(__name__)

#: USD per million tokens (prompt, completion). Approximate list prices used for
#: telemetry only; being slightly wrong is fine, having no number is not.
PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-opus-4-1": (15.00, 75.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "mock": (0.0, 0.0),
}


class LLMError(BuildWiseError):
    """Provider failed after every retry. The graph degrades; it does not guess."""


class CostLedger:
    """Per-case token and cost accumulation.

    In-process and intentionally simple: the durable record is the audit trace.
    This exists so a graph run can attach a running total to its state and so the
    dashboard can show cost per case without re-aggregating traces on every read.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, int] = defaultdict(int)
        self._cost: dict[str, float] = defaultdict(float)
        self._calls: dict[str, int] = defaultdict(int)

    def record(self, case_id: str, usage: LLMUsage) -> None:
        self._tokens[case_id] += usage.total_tokens
        self._cost[case_id] += usage.cost_usd
        self._calls[case_id] += 1

    def totals(self, case_id: str) -> dict[str, Any]:
        return {
            "tokens": self._tokens.get(case_id, 0),
            "cost_usd": round(self._cost.get(case_id, 0.0), 6),
            "calls": self._calls.get(case_id, 0),
        }

    def reset(self, case_id: str) -> None:
        self._tokens.pop(case_id, None)
        self._cost.pop(case_id, None)
        self._calls.pop(case_id, None)


ledger = CostLedger()


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prompt_rate, completion_rate = PRICING.get(model, (1.0, 3.0))
    return (prompt_tokens * prompt_rate + completion_tokens * completion_rate) / 1_000_000


class LLMClient:
    """Single entry point for every model call in the system."""

    def __init__(self) -> None:
        settings = get_settings()
        self.provider = settings.llm_provider
        self.timeout = settings.llm_timeout_seconds
        self.max_retries = max(1, settings.llm_max_retries)
        self.models = {"small": settings.llm_model_small, "large": settings.llm_model_large}

    def model_for(self, tier: str) -> str:
        if self.provider == "mock":
            return "mock"
        return self.models.get(tier, self.models["large"])

    async def complete(
        self,
        prompt_id: str,
        variables: dict[str, Any],
        *,
        case_id: str,
        version: str | None = None,
        tier_override: str | None = None,
        max_tokens: int = 1400,
    ) -> LLMResult:
        """Render a registered prompt, call the provider, and account for the cost.

        Raises `LLMError` after exhausting retries rather than returning a partial
        or empty result — a caller that receives "" will happily build a response
        around nothing.
        """
        registry = get_registry()
        prompt = registry.get(prompt_id, version)
        tier = tier_override or prompt.model_tier
        model = self.model_for(tier)
        rendered = prompt.render(variables)

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            started = time.perf_counter()
            try:
                text, prompt_tokens, completion_tokens = await self._dispatch(
                    model, rendered, variables, prompt_id, max_tokens
                )
                latency_ms = int((time.perf_counter() - started) * 1000)
                usage = LLMUsage(
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=estimate_cost(model, prompt_tokens, completion_tokens),
                    latency_ms=latency_ms,
                    attempts=attempt,
                )
                ledger.record(case_id, usage)
                log.info(
                    "llm_call",
                    prompt=prompt.qualified,
                    model=model,
                    tier=tier,
                    tokens=usage.total_tokens,
                    cost_usd=round(usage.cost_usd, 6),
                    latency_ms=latency_ms,
                    attempt=attempt,
                )
                return LLMResult(
                    text=text,
                    usage=usage,
                    prompt_id=prompt.prompt_id,
                    prompt_version=prompt.version,
                )
            except Exception as exc:  # noqa: BLE001 - retried then converted
                last_error = exc
                # Never log the rendered prompt or any key material.
                log.warning(
                    "llm_call_failed",
                    prompt=prompt.qualified,
                    model=model,
                    attempt=attempt,
                    error=type(exc).__name__,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        raise LLMError(
            f"{self.provider} provider failed for {prompt.qualified} after "
            f"{self.max_retries} attempts: {type(last_error).__name__}",
            case_id=case_id,
        )

    async def _dispatch(
        self,
        model: str,
        rendered: str,
        variables: dict[str, Any],
        prompt_id: str,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        if self.provider == "mock":
            from llm.mock_provider import generate

            text = generate(prompt_id, variables)
            return text, len(rendered) // 4, len(text) // 4
        if self.provider == "anthropic":
            return await self._anthropic(model, rendered, max_tokens)
        if self.provider == "openai":
            return await self._openai(model, rendered, max_tokens)
        raise LLMError(f"unknown provider {self.provider!r}")

    async def _anthropic(self, model: str, rendered: str, max_tokens: int) -> tuple[str, int, int]:
        import httpx

        settings = get_settings()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": rendered}],
                },
            )
        response.raise_for_status()
        data = response.json()
        text = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        return text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))

    async def _openai(self, model: str, rendered: str, max_tokens: int) -> tuple[str, int, int]:
        import httpx

        settings = get_settings()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": rendered}],
                },
            )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def reset_client() -> None:
    """Used by tests after changing settings."""
    global _client
    _client = None
