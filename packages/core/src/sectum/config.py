"""Read and validate ``sectum.yaml`` and resolve its adapter blocks.

The CLI flag ``--config sectum.yaml`` loads a ``SectumConfig``: a typed view
of the configuration that ``sectum init`` scaffolds. Explicit CLI flags
override the values the config supplies, and the config supplies values the
built-in defaults would otherwise use (the engineering spec, section 10).

``build_adapters`` turns the config's ``adapters`` block into concrete
adapter instances the CLI's probe suite can drive. This module wires the
fake adapters today; live kinds (pgvector, chroma, weaviate, redis, phoenix,
http-rag, http-agent, stdio-mcp) are deferred to follow-ups - the resolver
raises ``ConfigError`` with a clear message until they are wired.

Credentials never appear inline in the file. Adapter blocks will reference
environment variables (for example ``dsn_env: SECTUM_PGVECTOR_DSN``) so the
adapter resolver can look them up at run time without storing secrets.
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sectum.adapters import (
    AgentAdapter,
    CacheAdapter,
    FakeAgent,
    FakeCache,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeRAGPipeline,
    FakeVectorStore,
    MCPAdapter,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RAGPipelineAdapter,
    VectorStoreAdapter,
)
from sectum.spec import ConfigError


class ScenarioConfig(BaseModel):
    """Scenario settings driving substrate generation."""

    model_config = ConfigDict(extra="forbid")

    seed: int = 2026
    corpus_profile: str = "demo"


class AdapterConfig(BaseModel):
    """One adapter's configuration: a kind plus any backend-specific fields.

    The resolver dispatches on ``kind`` (for example ``fake``, ``pgvector``,
    ``chroma``, ``redis``) and reads backend-specific fields from the extra
    keys (for example ``host``, ``port``, ``dsn_env``, ``shared_index``).
    """

    model_config = ConfigDict(extra="allow")

    kind: str


class EvidenceConfig(BaseModel):
    """Evidence-chain anchoring settings."""

    model_config = ConfigDict(extra="forbid")

    timestamper: Literal["local", "rfc3161"] = "local"
    tsa_url: str | None = None
    rekor_url: str | None = None


class SectumConfig(BaseModel):
    """The parsed ``sectum.yaml`` configuration."""

    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioConfig = Field(default_factory=ScenarioConfig)
    workdir: Path = Path(".sectum")
    adapters: dict[str, AdapterConfig] = Field(default_factory=dict)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)


def load_config(path: Path) -> SectumConfig:
    """Load and validate a ``sectum.yaml`` configuration file.

    Raises:
        ConfigError: if the file is missing, contains malformed YAML, or fails
            schema validation.
    """
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {path}: {error}") from error
    if raw is None:
        return SectumConfig()
    if not isinstance(raw, dict):
        raise ConfigError(f"config file must be a YAML mapping: {path}")
    try:
        return SectumConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(f"invalid config in {path}: {error}") from error


# --- adapter resolver -------------------------------------------------------


@dataclass(frozen=True)
class AdapterBundle:
    """The adapter set the CLI's probe suite needs."""

    vector: VectorStoreAdapter
    cache: CacheAdapter
    model: ModelAdapter
    mcp: MCPAdapter
    memory: MemoryAdapter
    rag: RAGPipelineAdapter
    observability: ObservabilityAdapter
    agent: AgentAdapter


def _bool(extras: dict[str, Any], key: str, default: bool) -> bool:
    """Pull a boolean from an ``AdapterConfig``'s extras with a default."""
    value = extras.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"adapter field {key!r} must be a boolean, got {value!r}")
    return value


def _int(extras: dict[str, Any], key: str, default: int) -> int:
    """Pull an integer from extras with a default."""
    value = extras.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"adapter field {key!r} must be an integer, got {value!r}")
    return value


def _str(extras: dict[str, Any], key: str, default: str) -> str:
    """Pull a string from extras with a default."""
    value = extras.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"adapter field {key!r} must be a string, got {value!r}")
    return value


def _required_str(extras: dict[str, Any], key: str) -> str:
    """Pull a required string from extras, or raise ``ConfigError`` if missing."""
    if key not in extras:
        raise ConfigError(f"adapter field {key!r} is required")
    return _str(extras, key, "")


def _optional_str(extras: dict[str, Any], key: str) -> str | None:
    """Pull an optional string from extras, or ``None`` when absent."""
    if key not in extras:
        return None
    return _str(extras, key, "")


def _float(extras: dict[str, Any], key: str, default: float) -> float:
    """Pull a number from extras with a default; rejects booleans."""
    value = extras.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"adapter field {key!r} must be a number, got {value!r}")
    return float(value)


def _str_dict(extras: dict[str, Any], key: str) -> dict[str, str] | None:
    """Pull an optional string-to-string mapping from extras."""
    value = extras.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"adapter field {key!r} must be a mapping, got {value!r}")
    return {str(k): str(v) for k, v in value.items()}


def _resolve_secret(extras: dict[str, Any], direct_key: str, env_key: str) -> str:
    """Resolve a secret value, preferring an environment-variable reference.

    The convention (the engineering spec, section 17 - "adapters never embed
    credentials"): the config holds ``dsn_env: SECTUM_PGVECTOR_DSN`` and the
    resolver reads the value from that environment variable. An inline
    ``dsn:`` is also accepted but discouraged.

    Empty values (``dsn_env: ""``, an unset env var, or ``dsn: ""``) are
    rejected with a ``ConfigError`` rather than silently passed through.
    """
    if env_key in extras:
        var = _str(extras, env_key, "")
        if not var:
            raise ConfigError(f"adapter field {env_key!r} must name an environment variable")
        value = os.environ.get(var)
        if not value:
            raise ConfigError(f"environment variable {var!r} is unset or empty")
        return value
    if direct_key in extras:
        value = _str(extras, direct_key, "")
        if not value:
            raise ConfigError(f"adapter field {direct_key!r} must not be empty")
        return value
    raise ConfigError(f"missing {direct_key!r} or {env_key!r} in adapter config")


_EMBED_DIM = 64
"""Dimension of the CLI's default hashing-trick embedder."""


def _hashing_embed(text: str) -> list[float]:
    """A deterministic hashing-trick embedding for the CLI's live vector adapters.

    No model, no network: a 64-dim sparse vector keyed on the alphanumeric
    tokens in ``text``. Deterministic across runs and machines, so a
    sectum-driven verification stays reproducible without an embedding-model
    account.
    """
    vector = [0.0] * _EMBED_DIM
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % _EMBED_DIM
        vector[index] += 1.0
    return vector


def _unsupported(family: str, kind: str) -> ConfigError:
    return ConfigError(f"{family} kind {kind!r} is not yet supported by the CLI resolver")


def build_vector_store(config: AdapterConfig) -> VectorStoreAdapter:
    """Build the vector-store adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeVectorStore(
            shared_index=_bool(extras, "shared_index", False),
            soft_delete=_bool(extras, "soft_delete", False),
        )
    if config.kind == "pgvector":
        from sectum.adapters.vector.pgvector import PgVectorStore

        dsn = _resolve_secret(extras, "dsn", "dsn_env")
        return PgVectorStore(dsn, _hashing_embed, dim=_EMBED_DIM)
    if config.kind == "chroma":
        from sectum.adapters.vector.chroma import ChromaVectorStore

        host = _str(extras, "host", "localhost")
        port = _int(extras, "port", 8000)
        return ChromaVectorStore(host, port, _hashing_embed)
    if config.kind == "weaviate":
        from sectum.adapters.vector.weaviate import WeaviateVectorStore

        host = _str(extras, "host", "localhost")
        port = _int(extras, "port", 8080)
        grpc_port = _int(extras, "grpc_port", 50051)
        return WeaviateVectorStore(host, port, grpc_port, _hashing_embed)
    raise _unsupported("vector_store", config.kind)


def build_cache(config: AdapterConfig) -> CacheAdapter:
    """Build the cache adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeCache(tenant_scoped=_bool(extras, "tenant_scoped", True))
    if config.kind == "redis":
        from sectum.adapters.cache.redis import RedisCache

        host = _str(extras, "host", "localhost")
        port = _int(extras, "port", 6379)
        tenant_scoped = _bool(extras, "tenant_scoped", True)
        prefix = _str(extras, "prefix", "sectum")
        return RedisCache(host, port, tenant_scoped=tenant_scoped, prefix=prefix)
    raise _unsupported("cache", config.kind)


def build_model(config: AdapterConfig) -> ModelAdapter:
    """Build the model adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeModel(
            adapter_bleed=_bool(extras, "adapter_bleed", False),
            prefix_cache=_bool(extras, "prefix_cache", False),
        )
    raise _unsupported("model", config.kind)


def build_mcp(config: AdapterConfig) -> MCPAdapter:
    """Build the MCP adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeMCP(
            confused_deputy=_bool(extras, "confused_deputy", False),
            token_passthrough=_bool(extras, "token_passthrough", False),
        )
    if config.kind == "stdio":
        from sectum.adapters.mcp.client import StdioMCPClient

        command = _required_str(extras, "command")
        raw_args = extras.get("args", [])
        if not isinstance(raw_args, list):
            raise ConfigError(f"mcp 'args' must be a list, got {raw_args!r}")
        args = [str(item) for item in raw_args]
        tenant_argument = _optional_str(extras, "tenant_argument")
        return StdioMCPClient(command, args, tenant_argument=tenant_argument)
    raise _unsupported("mcp", config.kind)


def build_memory(config: AdapterConfig) -> MemoryAdapter:
    """Build the memory adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeMemory(shared_memory=_bool(extras, "shared_memory", False))
    raise _unsupported("memory", config.kind)


def build_rag(config: AdapterConfig) -> RAGPipelineAdapter:
    """Build the RAG-pipeline adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeRAGPipeline()
    if config.kind == "http":
        from sectum.adapters.rag.http import HttpRAGPipeline

        url = _required_str(extras, "url")
        headers = _str_dict(extras, "headers")
        timeout = _float(extras, "timeout", 30.0)
        return HttpRAGPipeline(url, headers=headers, timeout=timeout)
    raise _unsupported("rag", config.kind)


def build_observability(config: AdapterConfig) -> ObservabilityAdapter:
    """Build the observability adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeObservability(soft_delete=_bool(extras, "soft_delete", False))
    if config.kind == "phoenix":
        from sectum.adapters.observability.phoenix import PhoenixObservability

        base_url = _required_str(extras, "base_url")
        prefix = _str(extras, "prefix", "sectum")
        return PhoenixObservability(base_url, prefix=prefix)
    raise _unsupported("observability", config.kind)


def build_agent(config: AdapterConfig) -> AgentAdapter:
    """Build the agent adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeAgent()
    if config.kind == "http":
        from sectum.adapters.agent.http import HttpAgent

        url = _required_str(extras, "url")
        headers = _str_dict(extras, "headers")
        timeout = _float(extras, "timeout", 30.0)
        return HttpAgent(url, headers=headers, timeout=timeout)
    raise _unsupported("agent", config.kind)


def build_adapters(config: SectumConfig) -> AdapterBundle:
    """Build every adapter the CLI's probe suite needs.

    A family that the config omits defaults to a plain (non-leaky) fake.
    """
    fake = AdapterConfig(kind="fake")
    return AdapterBundle(
        vector=build_vector_store(config.adapters.get("vector_store", fake)),
        cache=build_cache(config.adapters.get("cache", fake)),
        model=build_model(config.adapters.get("model", fake)),
        mcp=build_mcp(config.adapters.get("mcp", fake)),
        memory=build_memory(config.adapters.get("memory", fake)),
        rag=build_rag(config.adapters.get("rag", fake)),
        observability=build_observability(config.adapters.get("observability", fake)),
        agent=build_agent(config.adapters.get("agent", fake)),
    )
