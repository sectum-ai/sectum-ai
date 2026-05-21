"""Enumerations shared across the Sectum AI data models."""

from enum import StrEnum


class MarkerType(StrEnum):
    """The three canary marker types (the engineering spec, section 6.3)."""

    HARD_CANARY = "HARD_CANARY"
    ENTITY_CANARY = "ENTITY_CANARY"
    SECRET_CANARY = "SECRET_CANARY"


class Severity(StrEnum):
    """Finding severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingStatus(StrEnum):
    """Whether a finding is manifest-confirmed or merely a candidate."""

    CONFIRMED = "confirmed"
    UNVERIFIED = "unverified"


class PrincipalKind(StrEnum):
    """The kind of isolation boundary a principal represents.

    Sectum verifies that one principal's data does not reach another. A tenant
    is the top-level principal; a user is a sub-principal within a tenant. The
    substrate, detection, and surfaces are identical at either granularity -
    only the boundary being verified differs (ADR-0006).
    """

    TENANT = "tenant"
    USER = "user"


class Surface(StrEnum):
    """A place tenant data can live or leak (the engineering spec, section 23)."""

    API = "api"
    VECTOR_DB = "vector_db"
    RAG_PIPELINE = "rag_pipeline"
    PROMPT_LOGS = "prompt_logs"
    SEMANTIC_CACHE = "semantic_cache"
    KV_CACHE = "kv_cache"
    AGENT_MEMORY = "agent_memory"
    AGENT_FRAMEWORK = "agent_framework"
    MCP = "mcp"
    MODEL_ADAPTER = "model_adapter"
    EVAL_SET = "eval_set"
    BACKUP = "backup"
    SEARCH_INDEX = "search_index"
    TRACING = "tracing"
