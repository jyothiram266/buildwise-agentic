"""Schema-validated model output.

Architecture Section 3.4 allows exactly one repair attempt on a schema failure,
then triage. That number is deliberate: a second repair on the same malformed
output almost never succeeds and it doubles latency on the path where the system
is already misbehaving. One retry, then hand the case to a human.

`ValidationFailure` carries the raw text so the trace shows what the model
actually said. Diagnosing a schema bug from "validation failed" alone is guesswork.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from api.config import get_logger
from core.errors import ValidationFailure
from llm.client import LLMClient

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a completion.

    Models wrap JSON in fences and prose despite instructions. Tolerating that
    here is cheaper than a repair round trip, and it is not the same thing as
    tolerating a wrong schema.
    """
    candidate = text.strip()
    if match := _FENCE.search(candidate):
        candidate = match.group(1).strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise ValidationFailure("no JSON object found in model output", raw=text[:2000])
        candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"model output is not valid JSON: {exc.msg}", raw=text[:2000]) from exc
    if not isinstance(parsed, dict):
        raise ValidationFailure("model output parsed to a non-object", raw=text[:2000])
    return parsed


def _schema_summary(model: type[BaseModel]) -> str:
    schema = model.model_json_schema()
    return json.dumps(
        {
            "properties": {
                name: {k: v for k, v in spec.items() if k in {"type", "enum", "items", "anyOf"}}
                for name, spec in schema.get("properties", {}).items()
            },
            "required": schema.get("required", []),
        },
        indent=2,
    )


async def parse_or_repair(
    raw_text: str,
    model: type[T],
    *,
    client: LLMClient,
    case_id: str,
    agent: str,
) -> tuple[T, bool]:
    """Validate, and on failure make exactly one repair attempt.

    Returns `(instance, repaired)`. `repaired=True` is worth recording in the
    trace: a rising repair rate is an early signal that a prompt has drifted from
    its schema.
    """
    try:
        return model.model_validate(extract_json(raw_text)), False
    except (ValidationFailure, ValidationError) as first:
        error_text = _readable_error(first)
        log.warning("schema_validation_failed", agent=agent, case_id=case_id, error=error_text[:200])

    try:
        repair = await client.complete(
            "repair",
            {"schema": _schema_summary(model), "error": error_text, "output": raw_text[:4000]},
            case_id=case_id,
        )
        return model.model_validate(extract_json(repair.text)), True
    except (ValidationFailure, ValidationError) as second:
        raise ValidationFailure(
            f"{agent}: output failed schema validation and one repair attempt did not fix it "
            f"({_readable_error(second)})",
            case_id=case_id,
            raw=raw_text[:2000],
        ) from second


def _readable_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:6]
        )
    return str(exc)
