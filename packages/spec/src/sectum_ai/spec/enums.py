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


class AccessOutcome(StrEnum):
    """How an authorization-boundary fetch resolved (the engineering spec, Class 1).

    A direct cross-tenant fetch should be *denied*. The spec calls out the
    ambiguity a competitor's scanner misses: a backend that returns ``200`` with
    an empty body looks like a deny but never enforced one. ``RETURNED`` is the
    object actually surfacing (a leak if the object is foreign); ``EMPTY`` is the
    ambiguous empty result; ``DENIED`` is an explicit authorization refusal.
    """

    RETURNED = "returned"
    EMPTY = "empty"
    DENIED = "denied"


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


class CoverageVerdict(StrEnum):
    """The per-surface coverage verdict in a Class 11 erasure attestation.

    A coverage block (surface -> verdict) makes the attestation honest about
    *what it actually verified*: an attestation must never imply more coverage
    than it has. The anti-over-claim guarantee is that a surface which was not
    scanned can only ever be :data:`NOT_COVERED` - never :data:`ERASED` (the
    engineering spec, section 7, Class 11).

    The first three values are the tri-state every surface resolves to;
    :data:`ATTESTABLE_WITH_CAVEAT` is the fourth, DPO-facing distinction the
    spec calls out at Class 11 hiding place #8: the surface *was* scanned and a
    baseline existed, but the backend exposes no programmatic per-tenant erasure
    API, so the data is presumed retained until it ages out of the backend's
    retention window. It is a documented backend limitation, never a clean pass
    and never conflated with a residual-after-erasure *failure*.
    """

    ERASED = "ERASED"
    """Covered and clean: a baseline existed and no marker survived erasure."""

    RESIDUAL = "RESIDUAL"
    """Covered and failed: the backend was asked to erase and a marker survived."""

    ATTESTABLE_WITH_CAVEAT = "ATTESTABLE_WITH_CAVEAT"
    """Covered, but the backend exposes no per-tenant erasure API (hiding place #8)."""

    NOT_COVERED = "NOT_COVERED"
    """Out of scope, not scanned, or no pre-erasure baseline - never ``ERASED``."""
