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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sectum.adapters import (
    CacheAdapter,
    FakeCache,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeVectorStore,
    MCPAdapter,
    MemoryAdapter,
    ModelAdapter,
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


def _bool(extras: dict[str, Any], key: str, default: bool) -> bool:
    """Pull a boolean from an ``AdapterConfig``'s extras with a default."""
    value = extras.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"adapter field {key!r} must be a boolean, got {value!r}")
    return value


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
    raise _unsupported("vector_store", config.kind)


def build_cache(config: AdapterConfig) -> CacheAdapter:
    """Build the cache adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeCache(tenant_scoped=_bool(extras, "tenant_scoped", True))
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
    raise _unsupported("mcp", config.kind)


def build_memory(config: AdapterConfig) -> MemoryAdapter:
    """Build the memory adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeMemory(shared_memory=_bool(extras, "shared_memory", False))
    raise _unsupported("memory", config.kind)


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
    )
