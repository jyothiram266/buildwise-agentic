"""Configuration and logging.

Every tunable lives here so a policy change is a config diff rather than a code
hunt. The class fails loudly at import time when something required is missing:
a request-time configuration error is a lost case, a startup error is a fixed
deployment.
"""

from __future__ import annotations

import logging
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.errors import ConfigurationError

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings, read from environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=(".env", REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"
    api_port: int = 8000

    database_url: str = "postgresql://buildwise:buildwise@localhost:5432/buildwise"
    redis_url: str = "redis://localhost:6379/0"

    mock_connector_url: str = "http://localhost:8100"
    connector_timeout_seconds: float = 6.0
    connector_cache_ttl_seconds: int = 60

    jwt_secret: str = "dev-only-secret"
    jwt_issuer: str = "buildwise-mock-auth"
    jwt_ttl_minutes: int = 720

    llm_provider: Literal["mock", "anthropic", "openai"] = "mock"
    llm_model_large: str = "claude-sonnet-4-6"
    llm_model_small: str = "claude-haiku-4-5-20251001"
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 2
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "local-hash-384"
    embedding_dim: int = 384

    reranker: Literal["heuristic", "cross_encoder"] = "heuristic"
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    classification_confidence_threshold: float = 0.70
    agent_confidence_threshold: float = 0.70
    slippage_flag_days: int = 14
    retrieval_k: int = 20
    rerank_top_n: int = 5
    cost_alert_usd_per_case: float = 0.25

    business_hours_start: int = 9
    business_hours_end: int = 18
    timezone: str = "Asia/Kolkata"

    corpus_dir: Path = Field(default=REPO_ROOT / "data" / "corpus")
    seed_dir: Path = Field(default=REPO_ROOT / "data" / "seed")
    prompt_dir: Path = Field(default=REPO_ROOT / "llm" / "prompts")
    web_dist_dir: Path = Field(default=REPO_ROOT / "web" / "dist")

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("classification_confidence_threshold", "agent_confidence_threshold")
    @classmethod
    def _threshold_range(cls, v: float) -> float:
        if not 0.0 < v < 1.0:
            raise ValueError("confidence thresholds must sit strictly between 0 and 1")
        return v

    def validate_runtime(self) -> None:
        """Fail fast on combinations that would only break mid-request."""
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ConfigurationError(
                "LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY. "
                "Set the key, or use LLM_PROVIDER=mock for an offline demo."
            )
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ConfigurationError(
                "LLM_PROVIDER=openai requires OPENAI_API_KEY. "
                "Set the key, or use LLM_PROVIDER=mock for an offline demo."
            )
        if self.embedding_provider == "openai" and not self.openai_api_key:
            raise ConfigurationError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY.")
        if self.app_env == "prod" and self.jwt_secret in {"dev-only-secret", "change-me"}:
            raise ConfigurationError("JWT_SECRET must be set to a real value when APP_ENV=prod.")
        if not self.corpus_dir.exists():
            raise ConfigurationError(f"Corpus directory not found: {self.corpus_dir}")

    @property
    def asyncpg_dsn(self) -> str:
        """asyncpg rejects the SQLAlchemy-style `+driver` suffix some hosts emit."""
        dsn = self.database_url
        for prefix in ("postgresql+asyncpg://", "postgres://"):
            if dsn.startswith(prefix):
                dsn = "postgresql://" + dsn.split("://", 1)[1]
        return dsn

    @property
    def demo_mode(self) -> bool:
        """Demo mode exposes the role switcher and mock token issuer."""
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

_CONFIGURED = False


def configure_logging() -> None:
    """Structured JSON logs with `case_id` bound to context where available.

    structlog is preferred; if it is not installed the fallback keeps the same
    call sites working so a missing optional dependency cannot take the app down.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)

    try:
        import structlog

        logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                (
                    structlog.dev.ConsoleRenderer(colors=False)
                    if settings.app_env == "dev"
                    else structlog.processors.JSONRenderer()
                ),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            cache_logger_on_first_use=True,
        )
    except ModuleNotFoundError:  # pragma: no cover - structlog is a declared dep
        logging.basicConfig(
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            stream=sys.stdout,
            level=level,
        )
    _CONFIGURED = True


def get_logger(name: str):
    """Return a logger. Never use print(); traces must be machine-readable."""
    configure_logging()
    try:
        import structlog

        return structlog.get_logger(name)
    except ModuleNotFoundError:  # pragma: no cover
        return logging.getLogger(name)


def validate_runtime() -> None:
    """Module-level entry point for the startup validation.

    A thin wrapper over `Settings.validate_runtime` so callers — the API lifespan,
    the selfcheck script, tests — do not each have to fetch the settings object
    first. Keeping the logic on the model and the entry point here means there is
    one implementation and one obvious way to call it.
    """
    get_settings().validate_runtime()


def bind_case(case_id: str) -> None:
    """Bind a case id to the logging context for the rest of this task."""
    try:
        import structlog

        structlog.contextvars.bind_contextvars(case_id=case_id)
    except ModuleNotFoundError:  # pragma: no cover
        pass


def clear_case() -> None:
    try:
        import structlog

        structlog.contextvars.clear_contextvars()
    except ModuleNotFoundError:  # pragma: no cover
        pass


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
