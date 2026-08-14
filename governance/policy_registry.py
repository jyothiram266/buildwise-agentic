"""Prompt and policy registry.

Prompts live in `llm/prompts/*.md` with frontmatter, never inline in python. Two
reasons that matters beyond tidiness:

* **Audit reproducibility.** Every LLM call records the resolved `prompt_version`.
  A response can be reproduced only if the exact text that produced it is
  retrievable by version, which means prompts must be addressable artefacts.
* **Change control.** A prompt edit without a version bump silently invalidates
  every earlier trace. `validate_all()` runs at startup so a malformed or missing
  prompt fails the deploy rather than the request.

Policies (severity matrix, escalation routing, warranty periods) are versioned the
same way, from `governance/policies/*.yaml`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from api.config import get_logger, get_settings
from core.errors import ConfigurationError

log = get_logger(__name__)

POLICY_DIR = Path(__file__).resolve().parent / "policies"
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
REQUIRED_PROMPT_KEYS = ("prompt_id", "version", "agent", "model_tier")


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    version: str
    agent: str
    model_tier: str
    updated_at: str | None
    body: str
    path: Path

    @property
    def qualified(self) -> str:
        return f"{self.prompt_id}@{self.version}"

    def render(self, variables: dict[str, Any]) -> str:
        """Substitute {{name}} placeholders.

        Missing placeholders raise instead of rendering "None" into a prompt: a
        prompt with a silently empty context block is how ungrounded answers get
        generated.
        """
        missing = [
            name for name in set(_PLACEHOLDER.findall(self.body)) if name not in variables
        ]
        if missing:
            raise ConfigurationError(
                f"prompt {self.qualified} is missing variables: {', '.join(sorted(missing))}"
            )

        def replace(match: re.Match[str]) -> str:
            value = variables[match.group(1)]
            if isinstance(value, list | dict):
                import json

                return json.dumps(value, indent=2, default=str)
            return str(value)

        return _PLACEHOLDER.sub(replace, self.body)


class PolicyRegistry:
    """Loads and caches prompts and policy documents."""

    def __init__(self, prompt_dir: Path | None = None) -> None:
        self.prompt_dir = prompt_dir or get_settings().prompt_dir
        self._prompts: dict[tuple[str, str], Prompt] = {}
        self._latest: dict[str, str] = {}
        self._policies: dict[str, dict[str, Any]] = {}
        self._loaded = False

    # -- loading -----------------------------------------------------------

    def load(self) -> None:
        if self._loaded:
            return
        if not self.prompt_dir.exists():
            raise ConfigurationError(f"prompt directory not found: {self.prompt_dir}")

        for path in sorted(self.prompt_dir.glob("*.md")):
            prompt = self._parse_prompt(path)
            self._prompts[(prompt.prompt_id, prompt.version)] = prompt
            current = self._latest.get(prompt.prompt_id)
            if current is None or _version_key(prompt.version) > _version_key(current):
                self._latest[prompt.prompt_id] = prompt.version

        for path in sorted(POLICY_DIR.glob("*.yaml")):
            data = yaml.safe_load(path.read_text()) or {}
            policy_id = str(data.get("policy_id") or path.stem)
            self._policies[policy_id] = data
            self._policies[path.stem] = data

        if not self._prompts:
            raise ConfigurationError(f"no prompts found in {self.prompt_dir}")
        self._loaded = True
        log.info(
            "policy_registry_loaded",
            prompts=len(self._prompts),
            policies=len({id(v) for v in self._policies.values()}),
        )

    def _parse_prompt(self, path: Path) -> Prompt:
        raw = path.read_text()
        if not raw.startswith("---"):
            raise ConfigurationError(f"{path.name}: prompt is missing frontmatter")
        _, fm, body = raw.split("---", 2)
        meta = yaml.safe_load(fm) or {}
        missing = [k for k in REQUIRED_PROMPT_KEYS if k not in meta]
        if missing:
            raise ConfigurationError(f"{path.name}: frontmatter missing {', '.join(missing)}")
        if meta["model_tier"] not in {"small", "large"}:
            raise ConfigurationError(
                f"{path.name}: model_tier must be 'small' or 'large', got {meta['model_tier']!r}"
            )
        return Prompt(
            prompt_id=str(meta["prompt_id"]),
            version=str(meta["version"]),
            agent=str(meta["agent"]),
            model_tier=str(meta["model_tier"]),
            updated_at=str(meta.get("updated_at")) if meta.get("updated_at") else None,
            body=body.strip(),
            path=path,
        )

    # -- resolution --------------------------------------------------------

    def get(self, prompt_id: str, version: str | None = None) -> Prompt:
        """Resolve by explicit version, or the latest when version is None."""
        self.load()
        resolved = version or self._latest.get(prompt_id)
        if resolved is None:
            raise ConfigurationError(
                f"unknown prompt_id {prompt_id!r}. Available: {sorted(self._latest)}"
            )
        prompt = self._prompts.get((prompt_id, resolved))
        if prompt is None:
            available = sorted(v for (pid, v) in self._prompts if pid == prompt_id)
            raise ConfigurationError(
                f"prompt {prompt_id!r} has no version {resolved!r}. Available: {available}"
            )
        return prompt

    def policy(self, policy_id: str) -> dict[str, Any]:
        self.load()
        if policy_id not in self._policies:
            raise ConfigurationError(f"unknown policy {policy_id!r}")
        return self._policies[policy_id]

    def policy_version(self, policy_id: str) -> str:
        return str(self.policy(policy_id).get("version", "unversioned"))

    def list_prompts(self) -> list[dict[str, str]]:
        self.load()
        return [
            {
                "prompt_id": p.prompt_id,
                "version": p.version,
                "agent": p.agent,
                "model_tier": p.model_tier,
                "is_latest": self._latest.get(p.prompt_id) == p.version,
                "file": p.path.name,
            }
            for p in sorted(self._prompts.values(), key=lambda x: (x.prompt_id, x.version))
        ]

    def validate_all(self, expected: list[str] | None = None) -> None:
        """Startup check: every prompt parses and every expected id resolves."""
        self.load()
        for prompt_id in expected or []:
            self.get(prompt_id)


def _version_key(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version)
    return tuple(int(p) for p in parts) or (0,)


@lru_cache
def get_registry() -> PolicyRegistry:
    registry = PolicyRegistry()
    registry.load()
    return registry


#: Prompts the application cannot start without.
REQUIRED_PROMPTS = [
    "classification",
    "property_info",
    "documentation",
    "construction_internal",
    "construction_customer",
    "maintenance",
    "contractor",
    "escalation_brief",
    "response_customer",
    "response_broker",
    "response_contractor",
    "response_internal",
    "repair",
]
