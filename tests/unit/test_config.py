"""Configuration and the fail-fast contract (build plan P0-T3).

The requirement is that the app starts with a valid `.env` and fails with a clear
message when something required is missing — at startup, not on the first request
that happens to need it.
"""

from __future__ import annotations

import pytest

from api.config import get_settings, validate_runtime
from core.errors import ConfigurationError


def test_settings_load_with_defaults() -> None:
    settings = get_settings()
    assert settings.database_url.startswith("postgres")
    assert settings.llm_provider in {"mock", "anthropic", "openai"}
    assert 0.0 < settings.classification_confidence_threshold <= 1.0
    assert settings.embedding_dim > 0


def test_settings_are_cached() -> None:
    assert get_settings() is get_settings()


def test_mock_provider_needs_no_key() -> None:
    """The whole point of the offline provider: a reviewer with no key can run this."""
    settings = get_settings()
    if settings.llm_provider == "mock":
        validate_runtime()  # must not raise


def test_a_real_provider_without_a_key_fails_at_startup(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError):
            validate_runtime()
    finally:
        get_settings.cache_clear()


def test_prod_refuses_the_dev_jwt_secret(monkeypatch) -> None:
    """A default secret in production is a hole, so the app refuses to start."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "dev-only-secret")
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError):
            validate_runtime()
    finally:
        get_settings.cache_clear()


def test_thresholds_are_within_range() -> None:
    settings = get_settings()
    for value in (
        settings.classification_confidence_threshold,
        settings.agent_confidence_threshold,
    ):
        assert 0.0 < value < 1.0
