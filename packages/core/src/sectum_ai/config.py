"""Read and validate ``sectum-ai.yaml`` and resolve its adapter blocks.

The CLI flag ``--config sectum-ai.yaml`` loads a ``SectumConfig``: a typed view
of the configuration that ``sectum-ai init`` scaffolds. Explicit CLI flags
override the values the config supplies, and the config supplies values the
built-in defaults would otherwise use (the engineering spec, section 10).

``build_adapters`` turns the config's ``adapters`` block into concrete
adapter instances the CLI's probe suite can drive. Each family resolves
``kind: fake`` to its in-memory fake and dispatches the live kinds to their
adapters (for example
``pgvector``/``chroma``/``weaviate``/``pinecone``/``qdrant``/``milvus``/
``opensearch``/``azure-search`` for the vector store, ``redis`` for the cache,
``phoenix``/``langfuse``/``langsmith``/``otel``/``helicone``/``datadog``
for observability, ``http``/``langchain`` for RAG,
``http``/``langgraph``/``autogen``/``crewai``/``openai-assistants``/
``anthropic-tooluse`` for agents, ``stdio``/``http`` for MCP); an unsupported
kind raises ``ConfigError`` with a clear message.

Credentials never appear inline in the file. Adapter blocks will reference
environment variables (for example ``dsn_env: SECTUM_PGVECTOR_DSN``) so the
adapter resolver can look them up at run time without storing secrets.
"""

import hashlib
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from sectum_ai.adapters import (
    Adapter,
    AgentAdapter,
    BackupAdapter,
    CacheAdapter,
    EvalSetAdapter,
    FakeAgent,
    FakeBackup,
    FakeCache,
    FakeEvalSet,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeRAGPipeline,
    FakeSearchIndex,
    FakeVectorStore,
    MCPAdapter,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RAGPipelineAdapter,
    SearchIndexAdapter,
    VectorStoreAdapter,
)
from sectum_ai.embeddings import validate_embedding_spec
from sectum_ai.probes import (
    AnthropicJudge,
    DetectionProviders,
    EmbeddingProvider,
    Judge,
    OpenAIEmbeddingProvider,
    OpenAIJudge,
    resolve_semantic_threshold,
)
from sectum_ai.spec import AdapterError, ConfigError, Surface, SurfaceProvenance


class ScenarioConfig(BaseModel):
    """Scenario settings driving substrate generation."""

    model_config = ConfigDict(extra="forbid")

    seed: int = 2026
    corpus_profile: str = "demo"
    # ~500 documents per tenant is the demo default (the engineering spec, section
    # 6.2); lower it in a config for a faster run. Tests build small corpora by
    # passing ``corpus_size`` to ``default_scenario`` directly.
    corpus_size: int = 500
    embedding_models: tuple[str, ...] = ("fake-deterministic",)

    @field_validator("embedding_models")
    @classmethod
    def _check_embedding_models(cls, models: tuple[str, ...]) -> tuple[str, ...]:
        """Reject an unknown embedding-model name at config-load time (not silently)."""
        for spec in models:
            try:
                validate_embedding_spec(spec)
            except ConfigError as error:
                raise ValueError(str(error)) from error
        return models


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
    # `sectum-ai seed` seals the substrate (and its ground-truth manifest) at rest.
    manifest_key_env: str | None = None


class EmbedderConfig(BaseModel):
    """The embedding provider for the detection pipeline's semantic step."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["fake", "openai"] = "fake"
    model: str | None = None
    api_key_env: str | None = None
    # An OpenAI-compatible base URL. Point it at a local server that speaks the
    # OpenAI embeddings API - e.g. Ollama at "http://localhost:11434/v1"
    # (model: "nomic-embed-text"), vLLM, or LM Studio - to run the semantic step
    # with no OpenAI account. When set, the API key is optional (these endpoints
    # ignore the Authorization header); leave it unset for the real OpenAI API.
    base_url: str | None = None


class JudgeConfig(BaseModel):
    """The judge provider that adjudicates semantic leak candidates."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["fake", "openai", "anthropic"] = "fake"
    model: str | None = None
    api_key_env: str | None = None
    # An OpenAI-/Anthropic-compatible base URL (see EmbedderConfig.base_url): point
    # `kind: openai` at a local Ollama ("http://localhost:11434/v1",
    # model: "qwen2.5") to adjudicate candidates with no OpenAI account.
    base_url: str | None = None


class DetectionConfig(BaseModel):
    """Detection-pipeline providers and calibration."""

    model_config = ConfigDict(extra="forbid")

    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    # The semantic-similarity gate. A number is used verbatim (back-compat). The
    # literal "auto" resolves to the calibrated per-model preset for the configured
    # embedder (`sectum-ai calibrate` recommends these), falling back to the
    # conservative 0.62 default with a logged warning for an unknown model. The
    # default suits the fake embedder; raise it (or set "auto") once a real
    # embedding model is configured - a stronger model surfaces more (the spec §7).
    #
    # Bounded to the range a cosine similarity can actually occupy. Unbounded, a
    # threshold above 1.0 was accepted and silently switched the semantic detector
    # OFF: no similarity can clear it, so every candidate was skipped before the
    # judge, a paraphrased cross-tenant leak was not recorded even as an unverified
    # candidate, and the run still signed a pack asserting isolation. NaN was worse
    # than unsatisfiable - it inverted the gate, since every `<` against NaN is
    # False - and inf/-inf were accepted too. A gate the operator can disable by
    # typo, with no trace in the evidence, is the anti-over-claim guarantee's
    # blind spot. 0.0 stays legal: it admits every candidate to the judge, which
    # errs toward surfacing rather than away from it.
    semantic_threshold: Annotated[float, Field(ge=0.0, le=1.0)] | Literal["auto"] = 0.62
    # Detection deployment mode. "hosted" (default) permits hosted embedder/judge
    # providers (the real OpenAI/Anthropic APIs). "local" is the BYOC / "no data
    # leaves the box" guarantee: it fails fast if any configured embedder or judge
    # would call a default third-party AI API. Only the offline `fake` providers,
    # and providers explicitly pointed at an operator-controlled `base_url` (a local
    # or in-VPC endpoint), are allowed — so Sectum itself makes no call to a hosted
    # AI API. The `base_url` target is the operator's trust boundary, not Sectum's;
    # the threat model documents this. Detection is the only stage that embeds or
    # judges tenant content, so gating it is what makes the zero-egress claim real.
    mode: Literal["hosted", "local"] = "hosted"

    @model_validator(mode="after")
    def _enforce_local_mode(self) -> "DetectionConfig":
        """In ``local`` mode, reject any provider that would egress to a hosted AI API.

        A ``fake`` provider is offline; an ``openai``/``anthropic`` provider calls
        its vendor API unless ``base_url`` points it at an operator-controlled local
        or in-VPC endpoint. So ``local`` mode requires every non-``fake`` embedder
        and judge to set ``base_url`` — otherwise the detector would leave the box,
        breaking the zero-egress guarantee. Raises ``ValueError`` (surfaced as a
        ``ConfigError`` by :func:`load_config`) naming each offending provider.
        """
        if self.mode != "local":
            return self
        offenders: list[str] = []
        if self.embedder.kind != "fake" and self.embedder.base_url is None:
            offenders.append(f"embedder (kind={self.embedder.kind!r})")
        if self.judge.kind != "fake" and self.judge.base_url is None:
            offenders.append(f"judge (kind={self.judge.kind!r})")
        if offenders:
            joined = ", ".join(offenders)
            raise ValueError(
                f"detection.mode 'local' forbids hosted providers, but {joined} "
                "would call a hosted AI API. Use kind 'fake', or set base_url to a "
                "local/in-VPC endpoint (e.g. http://localhost:11434/v1)."
            )
        return self


class SectumConfig(BaseModel):
    """The parsed ``sectum-ai.yaml`` configuration."""

    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioConfig = Field(default_factory=ScenarioConfig)
    workdir: Path = Path(".sectum-ai")
    adapters: dict[str, AdapterConfig] = Field(default_factory=dict)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)

    @model_validator(mode="before")
    @classmethod
    def _drop_null_sections(cls, data: Any) -> Any:
        """Treat a section commented down to ``key: null`` as absent (use its default).

        A ``sectum-ai.yaml`` that comments out a whole section's body - e.g. a
        ``security:`` header whose only remaining line is ``# manifest_key_env:`` -
        parses that section to ``None``. A non-optional section field would then
        reject ``None``; dropping such keys lets the field's default apply, which
        matches the obvious intent and keeps a ``sectum-ai init`` template loadable.
        """
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data


def load_config(path: Path) -> SectumConfig:
    """Load and validate a ``sectum-ai.yaml`` configuration file.

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


# Which surface each bundle field speaks for, for the signed provenance block.
_BUNDLE_SURFACES: tuple[tuple[str, Surface], ...] = (
    ("vector", Surface.VECTOR_DB),
    ("cache", Surface.SEMANTIC_CACHE),
    ("model", Surface.MODEL_ADAPTER),
    ("mcp", Surface.MCP),
    ("memory", Surface.AGENT_MEMORY),
    ("rag", Surface.RAG_PIPELINE),
    ("observability", Surface.TRACING),
    ("agent", Surface.AGENT_FRAMEWORK),
)


def surface_provenance(bundle: AdapterBundle) -> dict[str, str]:
    """Map each exercised surface to whether its adapter was live or synthetic.

    Read off the adapter instances rather than the config, so a family that fell
    back to a fake - an omitted key, a misspelled one - is recorded as what it
    actually is and not as what the config appeared to ask for.
    """

    def provenance(field: str) -> SurfaceProvenance:
        adapter: Adapter = getattr(bundle, field)
        return SurfaceProvenance.SYNTHETIC if adapter.synthetic else SurfaceProvenance.LIVE

    return {surface.value: provenance(field).value for field, surface in _BUNDLE_SURFACES}


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


@contextmanager
def _optional_extra(extra: str) -> Iterator[None]:
    """Map a missing optional adapter dependency to a typed ``AdapterError``.

    The SDK-backed live adapters import their client SDK lazily (either at module
    import or at construction). If the operator selected ``kind: <extra>`` without
    ``pip install sectum-ai-adapters[<extra>]``, surface a clear install hint -
    which the CLI maps to the documented config/adapter exit code (3) - instead of
    a bare ``ModuleNotFoundError`` traceback (exit 1). Mirrors the model adapter's
    ``_import_required``. Only ``ImportError`` is mapped; a ``ConfigError`` from
    resolving backend fields passes through unchanged.
    """
    try:
        yield
    except ImportError as error:
        raise AdapterError(
            f"the '{extra}' adapter requires the optional `{extra}` dependency; "
            f"install sectum-ai-adapters[{extra}] to enable it"
        ) from error


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
        with _optional_extra("pgvector"):
            from sectum_ai.adapters.vector.pgvector import PgVectorStore

            dsn = _resolve_secret(extras, "dsn", "dsn_env")
            return PgVectorStore(
                dsn, _hashing_embed, dim=_EMBED_DIM, user_scoped=_bool(extras, "user_scoped", False)
            )
    if config.kind == "chroma":
        with _optional_extra("chroma"):
            from sectum_ai.adapters.vector.chroma import ChromaVectorStore

            host = _str(extras, "host", "localhost")
            port = _int(extras, "port", 8000)
            return ChromaVectorStore(
                host, port, _hashing_embed, user_scoped=_bool(extras, "user_scoped", False)
            )
    if config.kind == "weaviate":
        with _optional_extra("weaviate"):
            from sectum_ai.adapters.vector.weaviate import WeaviateVectorStore

            host = _str(extras, "host", "localhost")
            port = _int(extras, "port", 8080)
            grpc_port = _int(extras, "grpc_port", 50051)
            return WeaviateVectorStore(
                host,
                port,
                grpc_port,
                _hashing_embed,
                user_scoped=_bool(extras, "user_scoped", False),
            )
    if config.kind == "pinecone":
        with _optional_extra("pinecone"):
            from sectum_ai.adapters.vector.pinecone import PineconeVectorStore

            api_key = _resolve_secret(extras, "api_key", "api_key_env")
            index_name = _required_str(extras, "index")
            return PineconeVectorStore.connect(
                api_key,
                index_name,
                _hashing_embed,
                host=_optional_str(extras, "host"),
                user_scoped=_bool(extras, "user_scoped", False),
            )
    if config.kind == "qdrant":
        with _optional_extra("qdrant"):
            from sectum_ai.adapters.vector.qdrant import QdrantVectorStore

            # api_key is optional: a local/self-hosted Qdrant typically has no auth.
            # (distinct variable name so mypy doesn't narrow it against pinecone's str)
            qdrant_api_key = (
                _resolve_secret(extras, "api_key", "api_key_env")
                if "api_key" in extras or "api_key_env" in extras
                else None
            )
            return QdrantVectorStore(
                _hashing_embed,
                dim=_EMBED_DIM,
                host=_str(extras, "host", "localhost"),
                port=_int(extras, "port", 6333),
                grpc_port=_int(extras, "grpc_port", 6334),
                api_key=qdrant_api_key,
                user_scoped=_bool(extras, "user_scoped", False),
            )
    if config.kind == "milvus":
        with _optional_extra("milvus"):
            from sectum_ai.adapters.vector.milvus import MilvusVectorStore

            # token is optional: a local/self-hosted Milvus typically has no auth.
            milvus_token = (
                _resolve_secret(extras, "token", "token_env")
                if "token" in extras or "token_env" in extras
                else None
            )
            return MilvusVectorStore(
                _hashing_embed,
                dim=_EMBED_DIM,
                uri=_str(extras, "uri", "http://localhost:19530"),
                token=milvus_token,
                user_scoped=_bool(extras, "user_scoped", False),
            )
    if config.kind == "opensearch":
        with _optional_extra("opensearch"):
            from sectum_ai.adapters.vector.opensearch import OpenSearchVectorStore

            # password is optional: a local OpenSearch with the security plugin
            # disabled has no auth.
            opensearch_password = (
                _resolve_secret(extras, "password", "password_env")
                if "password" in extras or "password_env" in extras
                else None
            )
            return OpenSearchVectorStore(
                _hashing_embed,
                dim=_EMBED_DIM,
                host=_str(extras, "host", "localhost"),
                port=_int(extras, "port", 9200),
                user=_optional_str(extras, "user"),
                password=opensearch_password,
                use_ssl=_bool(extras, "use_ssl", False),
                verify_certs=_bool(extras, "verify_certs", False),
                user_scoped=_bool(extras, "user_scoped", False),
            )
    if config.kind == "azure-search":
        with _optional_extra("azure-search"):
            from sectum_ai.adapters.vector.azure_search import AzureSearchVectorStore

            return AzureSearchVectorStore(
                _hashing_embed,
                dim=_EMBED_DIM,
                endpoint=_required_str(extras, "endpoint"),
                api_key=_resolve_secret(extras, "api_key", "api_key_env"),
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
        with _optional_extra("redis"):
            from sectum_ai.adapters.cache.redis import RedisCache

            host = _str(extras, "host", "localhost")
            port = _int(extras, "port", 6379)
            tenant_scoped = _bool(extras, "tenant_scoped", True)
            user_scoped = _bool(extras, "user_scoped", False)
            prefix = _str(extras, "prefix", "sectum-ai")
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
            user_scoped=_bool(extras, "user_scoped", False),
        )
    if config.kind == "huggingface":
        # A live HuggingFace + PEFT LoRA model. Like the agent live kinds,
        # ``connect`` imports the heavy transformers/peft/torch stack only
        # when this branch fires; an operator who set ``kind: huggingface``
        # without the extras group sees a typed AdapterError at construction
        # rather than an opaque ImportError mid-run.
        from sectum_ai.adapters.model.huggingface import HuggingFaceLoraModel

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
    if config.kind == "vllm":
        # A live vLLM server over its OpenAI-compatible API. Serving-only: it
        # runs inference against fixed weights and shares one prefix cache, so it
        # drives Class 5 (KV-cache timing) but trains no per-tenant adapter - the
        # CLI skips Class 9 for it. The ``openai`` client is imported lazily by
        # ``connect``; ``_optional_extra`` maps a missing dependency to a typed
        # AdapterError (exit 3) with an install hint.
        from sectum_ai.adapters.model.vllm import VLLMModel

        base_url = _required_str(extras, "base_url")
        model_name = _required_str(extras, "model")
        api_key = (
            _resolve_secret(extras, "api_key", "api_key_env")
            if "api_key" in extras or "api_key_env" in extras
            else "EMPTY"
        )
        with _optional_extra("vllm"):
            return VLLMModel.connect(
                base_url=base_url,
                model=model_name,
                api_key=api_key,
                timeout=_float(extras, "timeout", 30.0),
                max_tokens=_int(extras, "max_tokens", 16),
            )
    if config.kind == "tgi":
        # A live HuggingFace Text Generation Inference server. Serving-only like
        # vLLM (Class 5 KV-cache timing, no per-tenant training -> Class 9 skipped).
        # TGI serves one model per endpoint, so only ``base_url`` is required;
        # ``api_key`` is an optional bearer token. The ``huggingface_hub`` client
        # is imported lazily by ``connect``.
        from sectum_ai.adapters.model.tgi import TGIModel

        tgi_base_url = _required_str(extras, "base_url")
        tgi_api_key = (
            _resolve_secret(extras, "api_key", "api_key_env")
            if "api_key" in extras or "api_key_env" in extras
            else None
        )
        with _optional_extra("tgi"):
            return TGIModel.connect(
                base_url=tgi_base_url,
                api_key=tgi_api_key,
                timeout=_float(extras, "timeout", 30.0),
                max_tokens=_int(extras, "max_tokens", 16),
            )
    raise _unsupported("model", config.kind)


def build_mcp(config: AdapterConfig) -> MCPAdapter:
    """Build the MCP adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeMCP(
            confused_deputy=_bool(extras, "confused_deputy", False),
            token_passthrough=_bool(extras, "token_passthrough", False),
            user_scoped=_bool(extras, "user_scoped", False),
        )
    if config.kind == "stdio":
        from sectum_ai.adapters.mcp.client import StdioMCPClient

        command = _required_str(extras, "command")
        raw_args = extras.get("args", [])
        if not isinstance(raw_args, list):
            raise ConfigError(f"mcp 'args' must be a list, got {raw_args!r}")
        args = [str(item) for item in raw_args]
        tenant_argument = _optional_str(extras, "tenant_argument")
        return StdioMCPClient(command, args, tenant_argument=tenant_argument)
    if config.kind == "http":
        from sectum_ai.adapters.mcp.http import HttpMCPClient

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
            user_scoped=_bool(extras, "user_scoped", False),
        )
    if config.kind == "redis":
        with _optional_extra("redis"):
            from sectum_ai.adapters.memory.redis import RedisMemory

            host = _str(extras, "host", "localhost")
            port = _int(extras, "port", 6379)
            shared_memory = _bool(extras, "shared_memory", False)
            user_scoped = _bool(extras, "user_scoped", False)
            soft_delete = _bool(extras, "soft_delete", False)
            prefix = _str(extras, "prefix", "sectum-ai-mem")
            return RedisMemory(
                host,
                port,
                shared_memory=shared_memory,
                user_scoped=user_scoped,
                soft_delete=soft_delete,
                prefix=prefix,
            )
    if config.kind == "mem0":
        if _bool(extras, "user_scoped", False):
            raise ConfigError(
                "memory kind 'mem0' does not support user_scoped - mem0's flat user_id "
                "space has no per-user erasure boundary; use kind 'redis' for that"
            )
        shared_memory = _bool(extras, "shared_memory", False)
        soft_delete = _bool(extras, "soft_delete", False)
        mem0_config = extras.get("config")
        if mem0_config is not None and not isinstance(mem0_config, dict):
            raise ConfigError(f"memory 'config' must be a mapping, got {mem0_config!r}")
        with _optional_extra("mem0"):
            from sectum_ai.adapters.memory.mem0 import Mem0Memory

            return Mem0Memory.connect(
                mem0_config, shared_memory=shared_memory, soft_delete=soft_delete
            )
    raise _unsupported("memory", config.kind)


def build_search_index(config: AdapterConfig) -> SearchIndexAdapter:
    """Build the search-index adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeSearchIndex(soft_delete=_bool(extras, "soft_delete", False))
    if config.kind == "opensearch":
        with _optional_extra("opensearch"):
            from sectum_ai.adapters.search_index.opensearch import OpenSearchSearchIndex

            # password is optional: a local OpenSearch with the security plugin
            # disabled has no auth.
            password = (
                _resolve_secret(extras, "password", "password_env")
                if "password" in extras or "password_env" in extras
                else None
            )
            return OpenSearchSearchIndex(
                _str(extras, "host", "localhost"),
                _int(extras, "port", 9200),
                user=_optional_str(extras, "user"),
                password=password,
                use_ssl=_bool(extras, "use_ssl", False),
                verify_certs=_bool(extras, "verify_certs", False),
                prefix=_str(extras, "prefix", "sectum-ai-search"),
                soft_delete=_bool(extras, "soft_delete", False),
            )
    raise _unsupported("search index", config.kind)


def build_eval_set(config: AdapterConfig) -> EvalSetAdapter:
    """Build the eval-set adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeEvalSet(soft_delete=_bool(extras, "soft_delete", False))
    if config.kind == "langsmith":
        api_key = _resolve_secret(extras, "api_key", "api_key_env")
        api_url = _optional_str(extras, "api_url")
        prefix = _str(extras, "prefix", "sectum-ai-eval")
        soft_delete = _bool(extras, "soft_delete", False)
        with _optional_extra("langsmith"):
            from sectum_ai.adapters.eval_set.langsmith import LangSmithEvalSet

            return LangSmithEvalSet.connect(
                api_key, api_url, prefix=prefix, soft_delete=soft_delete
            )
    raise _unsupported("eval set", config.kind)


def build_backup(config: AdapterConfig) -> BackupAdapter:
    """Build the backup adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeBackup(
            soft_delete=_bool(extras, "soft_delete", False),
            no_erasure=_bool(extras, "no_erasure", False),
        )
    if config.kind == "s3":
        bucket = _required_str(extras, "bucket")
        access_key_id = (
            _resolve_secret(extras, "access_key_id", "access_key_id_env")
            if "access_key_id" in extras or "access_key_id_env" in extras
            else None
        )
        secret_access_key = (
            _resolve_secret(extras, "secret_access_key", "secret_access_key_env")
            if "secret_access_key" in extras or "secret_access_key_env" in extras
            else None
        )
        with _optional_extra("boto3"):
            from sectum_ai.adapters.backup.s3 import S3Backup

            return S3Backup.connect(
                bucket,
                endpoint_url=_optional_str(extras, "endpoint_url"),
                region_name=_optional_str(extras, "region_name"),
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                prefix=_str(extras, "prefix", "sectum-ai-backup"),
                no_erasure=_bool(extras, "no_erasure", False),
                soft_delete=_bool(extras, "soft_delete", False),
            )
    if config.kind == "gcs":
        bucket = _required_str(extras, "bucket")
        with _optional_extra("gcs"):
            from sectum_ai.adapters.backup.gcs import GCSBackup

            return GCSBackup.connect(
                bucket,
                project=_optional_str(extras, "project"),
                prefix=_str(extras, "prefix", "sectum-ai-backup"),
                no_erasure=_bool(extras, "no_erasure", False),
                soft_delete=_bool(extras, "soft_delete", False),
            )
    raise _unsupported("backup", config.kind)


def build_rag(config: AdapterConfig) -> RAGPipelineAdapter:
    """Build the RAG-pipeline adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeRAGPipeline(shared_index=_bool(extras, "shared_index", False))
    if config.kind == "http":
        from sectum_ai.adapters.rag.http import HttpRAGPipeline

        url = _required_str(extras, "url")
        headers = _str_dict(extras, "headers")
        timeout = _float(extras, "timeout", 30.0)
        return HttpRAGPipeline(url, headers=headers, timeout=timeout)
    if config.kind == "langchain":
        # A live LangChain RAG pipeline is wired in code (the chain is a
        # composed Runnable, not a YAML value): the resolver expects the
        # caller to expose a chain-factory callable and refer to it by
        # ``module.path:callable``. The factory is imported and called with
        # no arguments; it must return any object exposing
        # ``invoke(input) -> str | dict``.
        from importlib import import_module

        from sectum_ai.adapters.rag.langchain import LangChainRAGPipeline

        factory_path = _required_str(extras, "factory")
        module_name, _, attr = factory_path.rpartition(":")
        if not module_name or not attr:
            raise ConfigError(
                f"langchain 'factory' must be 'module.path:callable', got {factory_path!r}"
            )
        try:
            module = import_module(module_name)
        except ImportError as error:
            raise ConfigError(
                f"langchain factory module {module_name!r} cannot be imported: {error}"
            ) from error
        if not hasattr(module, attr):
            raise ConfigError(f"langchain factory {factory_path!r} is not exported")
        factory = getattr(module, attr)
        if not callable(factory):
            raise ConfigError(f"langchain factory {factory_path!r} is not callable")
        return LangChainRAGPipeline(factory())
    raise _unsupported("rag", config.kind)


def build_observability(config: AdapterConfig) -> ObservabilityAdapter:
    """Build the observability adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeObservability(
            soft_delete=_bool(extras, "soft_delete", False),
            no_erasure=_bool(extras, "no_erasure", False),
        )
    if config.kind == "phoenix":
        from sectum_ai.adapters.observability.phoenix import PhoenixObservability

        base_url = _required_str(extras, "base_url")
        prefix = _str(extras, "prefix", "sectum-ai")
        return PhoenixObservability(base_url, prefix=prefix)
    if config.kind == "langfuse":
        from sectum_ai.adapters.observability.langfuse import LangfuseObservability

        public_key = _resolve_secret(extras, "public_key", "public_key_env")
        secret_key = _resolve_secret(extras, "secret_key", "secret_key_env")
        host = _required_str(extras, "host")
        return LangfuseObservability.connect(public_key, secret_key, host)
    if config.kind == "langsmith":
        from sectum_ai.adapters.observability.langsmith import LangSmithObservability

        api_key = _resolve_secret(extras, "api_key", "api_key_env")
        api_url = _optional_str(extras, "api_url")
        prefix = _str(extras, "prefix", "sectum-ai")
        return LangSmithObservability.connect(api_key, api_url, prefix=prefix)
    if config.kind == "otel":
        from sectum_ai.adapters.observability.otel import OtelObservability

        base_url = _resolve_secret(extras, "base_url", "base_url_env")
        query_path = _str(extras, "query_path", "/v1/traces/query")
        headers = _str_dict(extras, "headers")
        timeout = _float(extras, "timeout", 30.0)
        tenant_attribute = _str(extras, "tenant_attribute", "tenant.id")
        return OtelObservability.connect(
            base_url,
            query_path=query_path,
            headers=headers,
            timeout=timeout,
            tenant_attribute=tenant_attribute,
        )
    if config.kind == "helicone":
        from sectum_ai.adapters.observability.helicone import HeliconeObservability

        api_key = _resolve_secret(extras, "api_key", "api_key_env")
        base_url = _str(extras, "base_url", "https://api.helicone.ai")
        tenant_property = _str(extras, "tenant_property", "tenant")
        return HeliconeObservability.connect(
            api_key, base_url=base_url, tenant_property=tenant_property
        )
    if config.kind == "datadog":
        from sectum_ai.adapters.observability.datadog import (
            DEFAULT_SEARCH_WINDOW,
            DatadogObservability,
        )

        api_key = _resolve_secret(extras, "api_key", "api_key_env")
        application_key = _resolve_secret(extras, "application_key", "application_key_env")
        base_url = _str(extras, "base_url", "https://api.datadoghq.com")
        tenant_tag = _str(extras, "tenant_tag", "tenant")
        return DatadogObservability.connect(
            api_key,
            application_key,
            base_url=base_url,
            tenant_tag=tenant_tag,
            search_window=_str(extras, "search_window", DEFAULT_SEARCH_WINDOW),
        )
    raise _unsupported("observability", config.kind)


def build_agent(config: AdapterConfig) -> AgentAdapter:
    """Build the agent adapter the config selects."""
    extras = config.model_extra or {}
    if config.kind == "fake":
        return FakeAgent(
            confused_deputy=_bool(extras, "confused_deputy", False),
            tool_call_passthrough=_bool(extras, "tool_call_passthrough", False),
        )
    if config.kind == "http":
        from sectum_ai.adapters.agent.http import HttpAgent

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

        from sectum_ai.adapters.agent.langgraph import LangGraphAgent

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

        from sectum_ai.adapters.agent.autogen import AutoGenAgent

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

        from sectum_ai.adapters.agent.crewai import CrewAIAgent

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

        from sectum_ai.adapters.agent.openai_assistants import OpenAIAssistantsAgent

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
    if config.kind == "anthropic-tooluse":
        # A live Anthropic native tool-use agent is wired in code (the tool
        # specs are Python objects carrying a ``__sectum_callable__`` sidecar
        # so the backend can execute them in the tool-use loop). The resolver
        # expects a client-factory callable referenced by
        # ``module.path:callable`` that returns an object implementing the
        # ``_AnthropicClient`` protocol the adapter consumes — typically the
        # ``LiveAnthropicClient`` built by ``AnthropicToolUseAgent.connect``.
        from importlib import import_module

        from sectum_ai.adapters.agent.anthropic_tooluse import AnthropicToolUseAgent

        factory_path = _required_str(extras, "factory")
        module_name, _, attr = factory_path.rpartition(":")
        if not module_name or not attr:
            raise ConfigError(
                f"anthropic-tooluse 'factory' must be 'module.path:callable', got {factory_path!r}"
            )
        try:
            module = import_module(module_name)
        except ImportError as error:
            raise ConfigError(
                f"anthropic-tooluse factory module {module_name!r} cannot be imported: {error}"
            ) from error
        if not hasattr(module, attr):
            raise ConfigError(f"anthropic-tooluse factory {factory_path!r} is not exported")
        factory = getattr(module, attr)
        if not callable(factory):
            raise ConfigError(f"anthropic-tooluse factory {factory_path!r} is not callable")
        return AnthropicToolUseAgent(factory())
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


def _provider_api_key(api_key_env: str | None, default_env: str, base_url: str | None) -> str:
    """Resolve a provider API key, lenient for OpenAI-compatible local endpoints.

    A real remote endpoint (``base_url`` unset) requires the key. A local
    OpenAI-compatible server (e.g. Ollama or vLLM, ``base_url`` set) ignores the
    Authorization header, so fall back to a placeholder when no key is configured -
    letting ``kind: openai`` run against a local model with no account.
    """
    if base_url is not None:
        return os.environ.get(api_key_env or default_env) or "sk-local-no-auth"
    return _resolve_api_key(api_key_env, default_env)


def _build_provider[ProviderT](
    ctor: Callable[..., ProviderT], api_key: str, model: str | None, base_url: str | None
) -> ProviderT:
    """Construct an OpenAI-/Anthropic-style provider, passing only the set options.

    The provider classes take ``model`` and ``base_url`` as keyword args with their
    own defaults, so each is forwarded only when the config sets it.
    """
    kwargs: dict[str, str] = {}
    if model is not None:
        kwargs["model"] = model
    if base_url is not None:
        kwargs["base_url"] = base_url
    return ctor(api_key, **kwargs)


# The OpenAI embedding model the provider defaults to when the config names
# none; kept in sync with OpenAIEmbeddingProvider's default so a bare
# ``kind: openai`` resolves to the right per-model preset under ``auto``.
_DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"


def embedder_model_name(config: EmbedderConfig) -> str | None:
    """The canonical embedder model name for preset lookup, or ``None`` for the fake.

    Mirrors the ``kind:model`` naming ``sectum_ai.embeddings`` produces and the
    keys in ``MODEL_THRESHOLDS``: an ``openai`` embedder is ``openai:<model>``
    (defaulting the model to the provider's own default when unset). The fake
    embedder has no model, so ``semantic_threshold: auto`` falls back to the
    conservative default for it.
    """
    if config.kind == "openai":
        return f"openai:{config.model or _DEFAULT_OPENAI_EMBEDDING_MODEL}"
    return None


def build_embedder(config: EmbedderConfig) -> EmbeddingProvider | None:
    """Resolve the configured embedding provider, or ``None`` to use the fake."""
    if config.kind == "fake":
        return None
    if config.kind == "openai":
        api_key = _provider_api_key(config.api_key_env, "OPENAI_API_KEY", config.base_url)
        return _build_provider(OpenAIEmbeddingProvider, api_key, config.model, config.base_url)
    raise ConfigError(f"unknown embedder kind: {config.kind!r}")


def build_judge(config: JudgeConfig) -> Judge | None:
    """Resolve the configured judge provider, or ``None`` to use the fake."""
    if config.kind == "fake":
        return None
    if config.kind == "openai":
        api_key = _provider_api_key(config.api_key_env, "OPENAI_API_KEY", config.base_url)
        return _build_provider(OpenAIJudge, api_key, config.model, config.base_url)
    if config.kind == "anthropic":
        api_key = _provider_api_key(config.api_key_env, "ANTHROPIC_API_KEY", config.base_url)
        return _build_provider(AnthropicJudge, api_key, config.model, config.base_url)
    raise ConfigError(f"unknown judge kind: {config.kind!r}")


def resolve_semantic_threshold_config(config: DetectionConfig) -> float:
    """Resolve ``detection.semantic_threshold`` to a concrete gate value.

    A numeric value is used verbatim (the back-compatible behaviour). The literal
    ``"auto"`` resolves to the calibrated per-model preset for the configured
    embedder (``resolve_semantic_threshold``), which falls back to the conservative
    default - with a logged warning - for an unknown or absent model.
    """
    threshold = config.semantic_threshold
    if isinstance(threshold, str):  # the only string form Literal allows is "auto"
        return resolve_semantic_threshold(embedder_model_name(config.embedder))
    return threshold


def build_detection_providers(config: DetectionConfig) -> DetectionProviders:
    """Build the detection-providers bundle from config (the fakes by default)."""
    return DetectionProviders(
        embedder=build_embedder(config.embedder),
        judge=build_judge(config.judge),
        semantic_threshold=resolve_semantic_threshold_config(config),
    )
