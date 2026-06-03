"""Tests for the sectum-ai.yaml adapter-resolver helpers and unknown-kind errors."""

from collections.abc import Callable

import pytest
from sectum_ai.config import (
    AdapterConfig,
    _optional_str,
    _required_str,
    _resolve_secret,
    build_agent,
    build_cache,
    build_mcp,
    build_memory,
    build_model,
    build_observability,
    build_rag,
    build_vector_store,
)
from sectum_ai.spec import ConfigError

_BUILDERS: tuple[Callable[[AdapterConfig], object], ...] = (
    build_vector_store,
    build_cache,
    build_model,
    build_mcp,
    build_memory,
    build_rag,
    build_observability,
    build_agent,
)


@pytest.mark.parametrize("builder", _BUILDERS)
def test_builder_rejects_an_unknown_kind(builder: Callable[[AdapterConfig], object]) -> None:
    with pytest.raises(ConfigError):
        builder(AdapterConfig(kind="bogus-kind"))


def test_required_str_missing_raises() -> None:
    with pytest.raises(ConfigError):
        _required_str({}, "index")


def test_optional_str_returns_none_when_absent() -> None:
    assert _optional_str({}, "host") is None
    assert _optional_str({"host": "example"}, "host") == "example"


def test_resolve_secret_reads_the_named_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECTUM_TEST_SECRET", "s3cr3t")
    resolved = _resolve_secret({"api_key_env": "SECTUM_TEST_SECRET"}, "api_key", "api_key_env")
    assert resolved == "s3cr3t"


def test_resolve_secret_missing_raises() -> None:
    with pytest.raises(ConfigError):
        _resolve_secret({}, "api_key", "api_key_env")
