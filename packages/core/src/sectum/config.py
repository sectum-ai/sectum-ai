"""Read and validate ``sectum.yaml`` and resolve its adapter blocks.

The CLI flag ``--config sectum.yaml`` loads a ``SectumConfig``: a typed view
of the configuration that ``sectum init`` scaffolds. Explicit CLI flags
override the values the config supplies, and the config supplies values the
built-in defaults would otherwise use (the engineering spec, section 10).

``build_adapters`` turns the config's ``adapters`` block into concrete
adapter instances the CLI's probe suite can drive. Each family resolves
``kind: fake`` to its in-memory fake and dispatches the live kinds to their
adapters (for example ``pgvector``/``chroma``/``weaviate``/``pinecone`` for the
vector store, ``redis`` for the cache, ``phoenix``/``langfuse``/``langsmith``
for observability, ``http`` for RAG,
``http``/``langgraph``/``autogen``/``crewai``/``openai-assistants`` for
agents, ``stdio``/``http`` for MCP); an unsupported kind raises ``ConfigError``
with a clear message.

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
from sectum.probes import (
    AnthropicJudge,
    DetectionProviders,
    EmbeddingProvider,
    Judge,
    OpenAIEmbeddingProvider,
    OpenAIJudge,
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
    rekor: bool = False
    rekor_url: str | None = None


class SecurityConfig(BaseModel):
    """At-rest protection settings for the seeded substrate."""

    model_config = ConfigDict(extra="forbid")

    # Name of the env var holding a base64-encoded 32-byte AES-256 key. When set,
    # `sectum seed` seals the substrate (and its ground-truth manifest) at rest.
    manifest_key_env: str | None = None


class EmbedderConfig(BaseModel):
    """The embedding provider for the detection pipeline's semantic step."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["fake", "openai"] = "fake"
    model: str | None = None
    api_key_env: str | None = None


class JudgeConfig(BaseModel):
    """The judge provider that adjudicates semantic leak candidates."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["fake", "openai", "anthropic"] = "fake"
    model: str | None = None
    api_key_env: str | None = None


class DetectionConfig(BaseModel):
    """Detection-pipeline providers and calibration."""

    model_config = ConfigDict(extra="forbid")

    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    # The semantic-similarity gate; the conservative default suits the fake
    # embedder and is the knob to raise once a real embedding model is configured.
    semantic_threshold: float = 0.62


class SectumConfig(BaseModel):
    """The parsed ``sectum.yaml`` configuration."""

    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioConfig = Field(default_factory=ScenarioConfig)
    workdir: Path = Path(".sectum")
    adapters: dict[str, AdapterConfig] = Field(default_factory=dict)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)


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
            user_scoped=_bool(extras, "user_scoped", False),
            soft_delete=_bool(extras, "soft_delete", False),
        )
    if config.kind == "pgvector":
        from sectum.adapters.vector.pgvector import PgVectorStore

        dsn = _resolve_secret(extras, "dsn", "dsn_env")
        return PgVectorStore(
            dsn, _hashing_embed, dim=_EMBED_DIM, user_scoped=_bool(extras, "user_scoped", False)
        )
    if config.kind == "chroma":
        from sectum.adapters.vector.chroma import ChromaVectorStore

        host = _str(extras, "host", "localhost")
        port = _int(extras, "port", 8000)
        return ChromaVectorStore(
            host, port, _hashing_embed, user_scoped=_bool(extras, "user_scoped", False)
        )
    if config.kind == "weaviate":
        from sectum.adapters.vector.weaviate import WeaviateVectorStore

        host = _str(extras, "host", "localhost")
        port = _int(extras, "port", 8080)
        grpc_port = _int(extras, "grpc_port", 50051)
        return WeaviateVectorStore(
            host, port, grpc_port, _hashing_embed, user_scoped=_bool(extras, "user_scoped", False)
        )
    if config.kind == "pinecone":
        from sectum.adapters.vector.pinecone import PineconeVectorStore

        api_key = _resolve_secret(extras, "api_key", "api_key_env")
        index_name = _required_str(extras, "index")
        return PineconeVectorStore.connect(
            api_key,
            index_name,
            _hashing_embed,
            host=_optional_str(extras, "host"),
            user_scoped=_bool(extras, "user_scoped", False),
        )
    raise _unsupported("vector_store", config.kind)


def build_cache(config: AdapterConfig) -> CacheAdapter:
    """Build the cache adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeCache(
            tenant_scoped=_bool(extras, "tenant_scoped", True),
            user_scoped=_bool(extras, "user_scoped", False),
            soft_delete=_bool(extras, "soft_delete", False),
        )
    if config.kind == "redis":
        from sectum.adapters.cache.redis import RedisCache

        host = _str(extras, "host", "localhost")
        port = _int(extras, "port", 6379)
        tenant_scoped = _bool(extras, "tenant_scoped", True)
        user_scoped = _bool(extras, "user_scoped", False)
        prefix = _str(extras, "prefix", "sectum")
        return RedisCache(
            host, port, tenant_scoped=tenant_scoped, user_scoped=user_scoped, prefix=prefix
        )
    raise _unsupported("cache", config.kind)


def build_model(config: AdapterConfig) -> ModelAdapter:
    """Build the model adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeModel(
            adapter_bleed=_bool(extras, "adapter_bleed", False),
            prefix_cache=_bool(extras, "prefix_cache", False),
            soft_delete=_bool(extras, "soft_delete", False),
        )
    if config.kind == "huggingface":
        # A live HuggingFace + PEFT LoRA model. Like the agent live kinds,
        # ``connect`` imports the heavy transformers/peft/torch stack only
        # when this branch fires; an operator who set ``kind: huggingface``
        # without the extras group sees a typed AdapterError at construction
        # rather than an opaque ImportError mid-run.
        from sectum.adapters.model.huggingface import HuggingFaceLoraModel

        base_model_id = _required_str(extras, "base_model_id")
        adapters_dir = _required_str(extras, "adapters_dir")
        return HuggingFaceLoraModel.connect(
            base_model_id=base_model_id,
            adapters_dir=adapters_dir,
            adapter_bleed=_bool(extras, "adapter_bleed", False),
            user_scoped=_bool(extras, "user_scoped", False),
            soft_delete=_bool(extras, "soft_delete", False),
            lora_rank=_int(extras, "lora_rank", 8),
            lora_alpha=_int(extras, "lora_alpha", 16),
            train_epochs=_int(extras, "train_epochs", 1),
            device_map=_str(extras, "device_map", "auto"),
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
    if config.kind == "http":
        from sectum.adapters.mcp.http import HttpMCPClient

        url = _required_str(extras, "url")
        headers = _str_dict(extras, "headers")
        timeout = _float(extras, "timeout", 30.0)
        tenant_argument = _optional_str(extras, "tenant_argument")
        return HttpMCPClient(url, headers=headers, timeout=timeout, tenant_argument=tenant_argument)
    raise _unsupported("mcp", config.kind)


def build_memory(config: AdapterConfig) -> MemoryAdapter:
    """Build the memory adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeMemory(
            shared_memory=_bool(extras, "shared_memory", False),
            soft_delete=_bool(extras, "soft_delete", False),
        )
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
    if config.kind == "langfuse":
        from sectum.adapters.observability.langfuse import LangfuseObservability

        public_key = _resolve_secret(extras, "public_key", "public_key_env")
        secret_key = _resolve_secret(extras, "secret_key", "secret_key_env")
        host = _required_str(extras, "host")
        return LangfuseObservability.connect(public_key, secret_key, host)
    if config.kind == "langsmith":
        from sectum.adapters.observability.langsmith import LangSmithObservability

        api_key = _resolve_secret(extras, "api_key", "api_key_env")
        api_url = _optional_str(extras, "api_url")
        prefix = _str(extras, "prefix", "sectum")
        return LangSmithObservability.connect(api_key, api_url, prefix=prefix)
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
    if config.kind == "langgraph":
        # A live LangGraph agent is wired in code (the graph is a Python object,
        # not a YAML value): the resolver expects the caller to expose a
        # graph-factory callable and refer to it by ``module.path:callable``.
        # The factory is imported and called with no arguments; it must return
        # a compiled graph object (or any object exposing
        # ``invoke(input, config) -> mapping``).
        from importlib import import_module

        from sectum.adapters.agent.langgraph import LangGraphAgent

        factory_path = _required_str(extras, "factory")
        module_name, _, attr = factory_path.rpartition(":")
        if not module_name or not attr:
            raise ConfigError(
                f"langgraph 'factory' must be 'module.path:callable', got {factory_path!r}"
            )
        try:
            module = import_module(module_name)
        except ImportError as error:
            raise ConfigError(
                f"langgraph factory module {module_name!r} cannot be imported: {error}"
            ) from error
        if not hasattr(module, attr):
            raise ConfigError(f"langgraph factory {factory_path!r} is not exported")
        factory = getattr(module, attr)
        if not callable(factory):
            raise ConfigError(f"langgraph factory {factory_path!r} is not callable")
        recursion_limit = _int(extras, "recursion_limit", 25)
        return LangGraphAgent(factory(), recursion_limit=recursion_limit)
    if config.kind == "autogen":
        # A live AutoGen agent is wired in code (the assistant and user-proxy
        # are Python objects, not YAML values): the resolver expects the caller
        # to expose a pair-factory callable and refer to it by
        # ``module.path:callable``. The factory is imported and called with no
        # arguments; it must return a 2-tuple ``(assistant, user_proxy)`` where
        # ``user_proxy`` exposes ``initiate_chat(recipient, message=...)``.
        from importlib import import_module

        from sectum.adapters.agent.autogen import AutoGenAgent

        factory_path = _required_str(extras, "factory")
        module_name, _, attr = factory_path.rpartition(":")
        if not module_name or not attr:
            raise ConfigError(
                f"autogen 'factory' must be 'module.path:callable', got {factory_path!r}"
            )
        try:
            module = import_module(module_name)
        except ImportError as error:
            raise ConfigError(
                f"autogen factory module {module_name!r} cannot be imported: {error}"
            ) from error
        if not hasattr(module, attr):
            raise ConfigError(f"autogen factory {factory_path!r} is not exported")
        factory = getattr(module, attr)
        if not callable(factory):
            raise ConfigError(f"autogen factory {factory_path!r} is not callable")
        pair = factory()
        if not (isinstance(pair, tuple) and len(pair) == 2):
            raise ConfigError(
                f"autogen factory {factory_path!r} must return a (assistant, user_proxy) tuple"
            )
        assistant, user_proxy = pair
        max_turns: int | None = None
        if "max_turns" in extras and extras["max_turns"] is not None:
            max_turns = _int(extras, "max_turns", 0)
        return AutoGenAgent(assistant, user_proxy, max_turns=max_turns)
    if config.kind == "crewai":
        # A live CrewAI agent is wired in code (the crew is a Python object
        # composed of agents + tasks, not a YAML value): the resolver expects
        # the caller to expose a crew-factory callable and refer to it by
        # ``module.path:callable``. The factory is imported and called with no
        # arguments; it must return a ``Crew`` (or any object exposing
        # ``kickoff(inputs: dict)``).
        from importlib import import_module

        from sectum.adapters.agent.crewai import CrewAIAgent

        factory_path = _required_str(extras, "factory")
        module_name, _, attr = factory_path.rpartition(":")
        if not module_name or not attr:
            raise ConfigError(
                f"crewai 'factory' must be 'module.path:callable', got {factory_path!r}"
            )
        try:
            module = import_module(module_name)
        except ImportError as error:
            raise ConfigError(
                f"crewai factory module {module_name!r} cannot be imported: {error}"
            ) from error
        if not hasattr(module, attr):
            raise ConfigError(f"crewai factory {factory_path!r} is not exported")
        factory = getattr(module, attr)
        if not callable(factory):
            raise ConfigError(f"crewai factory {factory_path!r} is not callable")
        input_key = _str(extras, "input_key", "task")
        tenant_key = _str(extras, "tenant_key", "tenant_id")
        return CrewAIAgent(factory(), input_key=input_key, tenant_key=tenant_key)
    if config.kind == "openai-assistants":
        # A live OpenAI Assistants agent is wired in code (the Assistant is a
        # persistent server-side object plus a Python callable map for the
        # tool execution loop, not a YAML value). The resolver expects a
        # client-factory callable referenced by ``module.path:callable`` that
        # returns a 2-tuple ``(client, assistant_id)`` where ``client``
        # implements the _AssistantsClient protocol the adapter consumes.
        from importlib import import_module

        from sectum.adapters.agent.openai_assistants import OpenAIAssistantsAgent

        factory_path = _required_str(extras, "factory")
        module_name, _, attr = factory_path.rpartition(":")
        if not module_name or not attr:
            raise ConfigError(
                f"openai-assistants 'factory' must be 'module.path:callable', got {factory_path!r}"
            )
        try:
            module = import_module(module_name)
        except ImportError as error:
            raise ConfigError(
                f"openai-assistants factory module {module_name!r} cannot be imported: {error}"
            ) from error
        if not hasattr(module, attr):
            raise ConfigError(f"openai-assistants factory {factory_path!r} is not exported")
        factory = getattr(module, attr)
        if not callable(factory):
            raise ConfigError(f"openai-assistants factory {factory_path!r} is not callable")
        pair = factory()
        if not (isinstance(pair, tuple) and len(pair) == 2):
            raise ConfigError(
                f"openai-assistants factory {factory_path!r} must return "
                "a (client, assistant_id) tuple"
            )
        client, assistant_id = pair
        if not isinstance(assistant_id, str) or not assistant_id:
            raise ConfigError(
                f"openai-assistants factory {factory_path!r} returned a non-string "
                "assistant_id; it must be the OpenAI Assistant's id"
            )
        return OpenAIAssistantsAgent(client, assistant_id)
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


def _resolve_api_key(api_key_env: str | None, default_env: str) -> str:
    env_var = api_key_env or default_env
    value = os.environ.get(env_var)
    if not value:
        raise ConfigError(f"the API key env var {env_var!r} is not set")
    return value


def build_embedder(config: EmbedderConfig) -> EmbeddingProvider | None:
    """Resolve the configured embedding provider, or ``None`` to use the fake."""
    if config.kind == "fake":
        return None
    if config.kind == "openai":
        api_key = _resolve_api_key(config.api_key_env, "OPENAI_API_KEY")
        if config.model is not None:
            return OpenAIEmbeddingProvider(api_key, model=config.model)
        return OpenAIEmbeddingProvider(api_key)
    raise ConfigError(f"unknown embedder kind: {config.kind!r}")


def build_judge(config: JudgeConfig) -> Judge | None:
    """Resolve the configured judge provider, or ``None`` to use the fake."""
    if config.kind == "fake":
        return None
    if config.kind == "openai":
        api_key = _resolve_api_key(config.api_key_env, "OPENAI_API_KEY")
        if config.model is not None:
            return OpenAIJudge(api_key, model=config.model)
        return OpenAIJudge(api_key)
    if config.kind == "anthropic":
        api_key = _resolve_api_key(config.api_key_env, "ANTHROPIC_API_KEY")
        if config.model is not None:
            return AnthropicJudge(api_key, model=config.model)
        return AnthropicJudge(api_key)
    raise ConfigError(f"unknown judge kind: {config.kind!r}")


def build_detection_providers(config: DetectionConfig) -> DetectionProviders:
    """Build the detection-providers bundle from config (the fakes by default)."""
    return DetectionProviders(
        embedder=build_embedder(config.embedder),
        judge=build_judge(config.judge),
        semantic_threshold=config.semantic_threshold,
    )
