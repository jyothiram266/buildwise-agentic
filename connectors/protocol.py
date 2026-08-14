"""Connector interface and shared HTTP behaviour.

Three things are enforced here rather than in the agents that call connectors:

* **Approval tokens.** A write whose declared risk tier is 2 or above is rejected
  inside the connector when the token is missing (AGENTS.md Section 5). The caller
  is sometimes an agent acting on model output, so the caller is exactly the wrong
  place to trust with that check.
* **Scope.** Every call carries an `AccessScope`, which is sent to the system of
  record and applied there as a query predicate. Adapters never post-filter.
* **Failure shape.** A timeout or a bad payload becomes `ConnectorError`, never a
  hang and never a `None` that a caller mistakes for "no results".
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from api.config import get_logger, get_settings
from core.enums import RiskTier
from core.errors import ApprovalRequiredError, ConnectorError, PolicyViolationError
from core.models import AccessScope

log = get_logger(__name__)


@runtime_checkable
class SystemConnector(Protocol):
    """The uniform contract every system of record implements (real or mock)."""

    name: str

    async def health(self) -> dict: ...

    async def query(self, request: BaseModel, scope: AccessScope) -> BaseModel: ...

    async def write(
        self, action: BaseModel, scope: AccessScope, approval: str | None = None
    ) -> BaseModel: ...


class WriteResult(BaseModel):
    ok: bool
    action: str
    record_id: str | None = None
    detail: str | None = None


class Health(BaseModel):
    name: str
    ok: bool
    latency_ms: int = 0
    detail: str | None = None


class HttpConnector:
    """Base adapter: retry with backoff, Redis response cache, typed errors.

    Subclasses declare `name`, `base_path`, the risk tier of each write action,
    and the request/response models for each operation.
    """

    name: str = "base"
    base_path: str = "/"
    #: action kind -> minimum risk tier. Anything at tier 2+ needs an approval token.
    action_risk: dict[str, RiskTier] = {}
    #: Set True for connectors that must never accept a write at all.
    read_only: bool = False
    cache_ttl_seconds: int | None = None

    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.mock_connector_url).rstrip("/")
        self.timeout = settings.connector_timeout_seconds
        self.cache_ttl_seconds = self.cache_ttl_seconds or settings.connector_cache_ttl_seconds

    # -- transport ---------------------------------------------------------

    async def _post(self, path: str, payload: dict[str, Any], attempts: int = 2) -> dict[str, Any]:
        import httpx

        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload)
                if response.status_code >= 500:
                    raise ConnectorError(
                        f"{self.name} returned {response.status_code}", connector=self.name
                    )
                if response.status_code == 403:
                    # The system of record refused on scope grounds. Surface it as a
                    # policy violation so it cannot be mistaken for "no data".
                    raise PolicyViolationError(
                        f"{self.name} refused the request for this scope", connector=self.name
                    )
                if response.status_code >= 400:
                    raise ConnectorError(
                        f"{self.name} rejected the request: {response.text[:200]}",
                        connector=self.name,
                    )
                return response.json()
            except PolicyViolationError:
                raise
            except Exception as exc:  # noqa: BLE001 - retried, then converted
                last_error = exc
                if attempt < attempts:
                    await asyncio.sleep(0.25 * attempt)
                    log.warning(
                        "connector_retry", connector=self.name, attempt=attempt, error=str(exc)
                    )
        raise ConnectorError(
            f"{self.name} unavailable after {attempts} attempts: {last_error}",
            connector=self.name,
        )

    # -- cache -------------------------------------------------------------

    def _cache_key(self, path: str, payload: dict[str, Any]) -> str:
        blob = json.dumps(payload, sort_keys=True, default=str).encode()
        return f"conn:{self.name}:{path}:{hashlib.sha256(blob).hexdigest()[:24]}"

    async def _cached_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Read-through cache. A cache miss or a Redis outage falls through to HTTP."""
        key = self._cache_key(path, payload)
        redis = await _get_redis()
        if redis is not None:
            try:
                hit = await redis.get(key)
                if hit:
                    return json.loads(hit)
            except Exception as exc:  # noqa: BLE001
                log.warning("connector_cache_read_failed", connector=self.name, error=str(exc))
        data = await self._post(path, payload)
        if redis is not None:
            try:
                await redis.set(key, json.dumps(data, default=str), ex=self.cache_ttl_seconds)
            except Exception as exc:  # noqa: BLE001
                log.warning("connector_cache_write_failed", connector=self.name, error=str(exc))
        return data

    # -- contract ----------------------------------------------------------

    async def health(self) -> dict:
        import time

        started = time.perf_counter()
        try:
            data = await self._post(f"{self.base_path}/health", {}, attempts=1)
            ok = bool(data.get("ok"))
            detail = data.get("detail")
        except Exception as exc:  # noqa: BLE001 - health reports, never raises
            ok, detail = False, str(exc)
        return Health(
            name=self.name,
            ok=ok,
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail=detail,
        ).model_dump()

    def _guard_write(self, action_kind: str, approval: str | None) -> RiskTier:
        """Reject unauthorised or unapproved writes before any network call."""
        if self.read_only:
            raise NotImplementedError(
                f"{self.name} is read-only by design; there is no write path in this system."
            )
        if action_kind not in self.action_risk:
            raise PolicyViolationError(
                f"{self.name} has no declared risk tier for action {action_kind!r}; "
                "declare it in action_risk before calling."
            )
        tier = self.action_risk[action_kind]
        if tier >= RiskTier.DRAFT_APPROVAL and not approval:
            raise ApprovalRequiredError(
                f"{self.name}.{action_kind} is tier {int(tier)} and requires an approval token",
                connector=self.name,
                action=action_kind,
            )
        return tier

    async def _write(
        self, action_kind: str, body: dict[str, Any], scope: AccessScope, approval: str | None
    ) -> WriteResult:
        tier = self._guard_write(action_kind, approval)
        payload = {
            "action": action_kind,
            "risk_tier": int(tier),
            "approval": approval,
            "scope": scope.model_dump(mode="json"),
            "payload": body,
        }
        data = await self._post(f"{self.base_path}/write", payload)
        return WriteResult(**data)

    async def _query(
        self, operation: str, body: dict[str, Any], scope: AccessScope, use_cache: bool = True
    ) -> dict[str, Any]:
        payload = {
            "operation": operation,
            "scope": scope.model_dump(mode="json"),
            "payload": body,
        }
        path = f"{self.base_path}/query"
        if use_cache:
            return await self._cached_post(path, payload)
        return await self._post(path, payload)


_redis_client: Any = None
_redis_failed = False


async def _get_redis() -> Any:
    """Shared Redis client, or None when Redis is unavailable.

    Cache is an optimisation. Losing it degrades latency, not correctness, so the
    absence is logged once and then tolerated.
    """
    global _redis_client, _redis_failed
    if _redis_failed:
        return None
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis

            _redis_client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
            await _redis_client.ping()
        except Exception as exc:  # noqa: BLE001
            log.warning("redis_unavailable_cache_disabled", error=str(exc))
            _redis_failed = True
            _redis_client = None
    return _redis_client


async def clear_connector_cache() -> None:
    """Used by tests and by the seed loader after data changes."""
    redis = await _get_redis()
    if redis is None:
        return
    async for key in redis.scan_iter("conn:*"):
        await redis.delete(key)
