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


class SurfaceProvenance(StrEnum):
    """What a run's probes actually interrogated on one surface.

    The third anti-over-claim block, after :class:`CoverageVerdict` (which
    surface was scanned) and :class:`ClassVerdict` (which class was checked).
    Those two answer *what did the run look at*; this one answers the question
    underneath them - *was there anything real behind it*.

    Sectum ships a synthetic in-memory adapter for every family, and an omitted
    or misspelled adapter key resolves to one silently. A whole run against
    those stores is well-formed, signs cleanly, and describes nothing about the
    operator's production systems - so the fact has to travel inside the signed
    record, where a third party reading the pack can see it, rather than in a
    console warning only the operator ever sees.
    """

    LIVE = "LIVE"
    """A configured backend outside this process - the run touched a real system."""

    SYNTHETIC = "SYNTHETIC"
    """The built-in in-memory fake: a verdict here says nothing about production."""


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


class ClassVerdict(StrEnum):
    """The per-attack-class verdict in an isolation scorecard (``sectum-ai score``).

    The scorecard analogue of :class:`CoverageVerdict`, and it carries the same
    anti-over-claim guarantee: a class whose probe did not run can only ever be
    :data:`NOT_COVERED` - never :data:`PASS`. A grade must never imply the stack
    passed a check it was never asked to perform, so untested classes are excluded
    from the grade entirely and lower the scorecard's *confidence* instead (see
    ``docs/scorecard.md``).
    """

    PASS = "PASS"
    """Covered and clean: the probe ran and confirmed no cross-tenant leak."""

    FAIL = "FAIL"
    """Covered and failed: the probe ran and confirmed at least one leak."""

    NOT_COVERED = "NOT_COVERED"
    """Not run - the stack could not satisfy the probe, or it was not in the run."""


class Grade(StrEnum):
    """The overall multi-tenant isolation grade (``sectum-ai score``).

    Derived from the *covered* classes only, then capped by the worst weight *band*
    among the failing classes (the band of the class, declared by the published
    methodology - never the severity recorded on an individual finding): a failing
    critical-band class can never grade above :data:`F`. The published weights,
    thresholds, and caps are in ``docs/scorecard.md``, so the grade is recomputable
    from a run.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class Confidence(StrEnum):
    """How much of the catalog a scorecard's grade actually rests on.

    Coverage-driven and reported *beside* the grade, never folded into it: a run
    that exercised three classes and a run that exercised all eleven can both grade
    ``A``, and the confidence is what tells them apart honestly.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
