"""Pydantic data models for Sectum AI (the engineering spec, section 9).

Every aggregate model carries ``schema_version``. Models are frozen: substrate
generation produces them and nothing mutates them afterwards, which keeps the
reproducibility contract (the engineering spec, section 6.5) easy to reason about.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from sectum_ai.spec.enums import (
    AccessOutcome,
    FindingStatus,
    MarkerType,
    PrincipalKind,
    Severity,
    Surface,
)

SCHEMA_VERSION = "0.2.0"
"""Version stamped onto every aggregate model; bumped on any schema change.

0.2.0 — the evidence anchors now bind the whole pack (manifest hash, control
mappings, pdf ref, transparency-log intent), not just the run record, and
timestamps in the canonical form are normalized to UTC so the digest is
reproducible regardless of the producer's local timezone.
"""


def _to_utc_iso(value: datetime) -> str:
    """Serialize a datetime to a UTC ISO-8601 string for the canonical form.

    The same instant must hash identically regardless of the producing
    machine's timezone, so a tz-aware value is converted to UTC and a naive
    value is assumed to already be UTC. This keeps ``canonical_hash`` injective
    over equal instants (the reproducibility contract, the engineering spec
    section 6.5, and the evidence chain, section 8).
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


# A datetime whose JSON/canonical form is always UTC ISO-8601.
UtcDateTime = Annotated[datetime, PlainSerializer(_to_utc_iso, return_type=str)]


class SectumModel(BaseModel):
    """Base model for all Sectum AI schemas: immutable, rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Scenario inputs --------------------------------------------------------


class SyntheticUserSpec(SectumModel):
    """A synthetic user within a tenant - a sub-principal (ADR-0006).

    When a tenant declares users, the substrate distributes that tenant's
    markers across them, so isolation can be verified at user granularity
    (one employee must not see another's data) as well as tenant granularity.
    """

    user_id: UUID
    display_name: str


class SyntheticTenantSpec(SectumModel):
    """Configuration for one synthetic tenant (the engineering spec, section 6.1)."""

    tenant_id: UUID
    display_name: str
    industry: str
    locale: str = "en-US"
    corpus_size: int = Field(gt=0)
    users: tuple[SyntheticUserSpec, ...] = ()


class SharedEntity(SectumModel):
    """An organic entity deliberately shared across tenants as leakage bait.

    Shared people, vendors, compliance terms, amounts, and dates reproduce the
    Retrieval Pivot conditions (the engineering spec, section 6.1).
    """

    kind: str
    value: str


class Scenario(SectumModel):
    """A reproducible test scenario (the engineering spec, section 9)."""

    scenario_id: str
    seed: int
    tenants: tuple[SyntheticTenantSpec, ...]
    corpus_profile: str = "demo"
    shared_entities: tuple[SharedEntity, ...] = ()
    embedding_models: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION


class Principal(SectumModel):
    """An isolation boundary Sectum verifies: a tenant, or a user within one.

    A tenant-level principal carries ``user_id is None``; a user-level
    principal carries both its tenant and its user id. The marker substrate
    and detection treat both identically - a principal is just the owner of a
    marker and the actor in a session (ADR-0006).
    """

    tenant_id: UUID
    user_id: UUID | None = None

    @property
    def kind(self) -> PrincipalKind:
        """Whether this principal is a tenant or a user within a tenant."""
        return PrincipalKind.TENANT if self.user_id is None else PrincipalKind.USER


# --- Markers and corpus -----------------------------------------------------


class PlantedLocation(SectumModel):
    """Where a marker was planted within a document."""

    doc_id: str
    field: str  # one of: body, title, metadata, tags


class Marker(SectumModel):
    """A planted canary whose appearance in the wrong principal proves leakage.

    ``owner_user_id`` is set only when the marker is owned by a specific user
    within ``owner_tenant_id``'s tenant (ADR-0006); a tenant-level marker
    leaves it ``None``.
    """

    marker_id: str
    marker_type: MarkerType
    owner_tenant_id: UUID
    owner_user_id: UUID | None = None
    plaintext: str = Field(min_length=1)
    embedding_ref: str | None = None
    planted_locations: tuple[PlantedLocation, ...] = ()


class CorpusDocument(SectumModel):
    """One synthetic document in a tenant's corpus (the engineering spec, section 6.2)."""

    doc_id: str
    tenant_id: UUID
    doc_type: str
    title: str
    content: str
    metadata: dict[str, str] = Field(default_factory=dict)
    marker_ids: tuple[str, ...] = ()
    owner_user_id: UUID | None = None
    """The user that owns this document within the tenant (ADR-0006), or ``None``.

    A pivot document inherits its planted marker's owner user; filler documents
    (and every document in a scenario that declares no users) are tenant-level
    (``None``). A user-scoped store uses this to decide what a user may retrieve.
    """


class GroundTruthManifest(SectumModel):
    """Authoritative record of which marker belongs to which tenant.

    The manifest is a pure function of the scenario and seed; it carries no
    wall-clock time so the reproducibility contract holds byte-for-byte. Its
    canonical hash is computed via ``sectum_ai.spec.hashing.canonical_hash``.
    """

    manifest_id: str
    scenario_hash: str
    markers: tuple[Marker, ...]
    schema_version: str = SCHEMA_VERSION


class Substrate(SectumModel):
    """The seeded substrate: tenants, corpora, markers, and the manifest."""

    scenario: Scenario
    tenants: tuple[SyntheticTenantSpec, ...]
    documents: tuple[CorpusDocument, ...]
    manifest: GroundTruthManifest
    schema_version: str = SCHEMA_VERSION

    def principals(self) -> tuple[Principal, ...]:
        """Every isolation boundary in the substrate (ADR-0006).

        Each tenant contributes a tenant-level principal; a tenant that
        declares users also contributes one principal per user. A tenant with
        no users contributes only its tenant-level principal.
        """
        result: list[Principal] = []
        for tenant in self.tenants:
            result.append(Principal(tenant_id=tenant.tenant_id))
            result.extend(
                Principal(tenant_id=tenant.tenant_id, user_id=user.user_id) for user in tenant.users
            )
        return tuple(result)


# --- Probe execution --------------------------------------------------------


class ProbeStep(SectumModel):
    """A single planned probe action issued from one principal's session.

    ``actor_user_id`` is set when the step is issued from a specific user within
    ``actor_tenant_id``'s tenant (ADR-0006); a tenant-level step leaves it
    ``None`` and behaves exactly as before.
    """

    step_id: str
    probe_id: str
    actor_tenant_id: UUID
    actor_user_id: UUID | None = None
    action: str
    payload: dict[str, str] = Field(default_factory=dict)


class Observation(SectumModel):
    """A response or observation captured for a probe step."""

    step_id: str
    surface: Surface
    raw_response: str
    structured: dict[str, str] | None = None
    latency_ms: float | None = None
    # How an authorization-boundary fetch resolved (Class 1). ``None`` for steps
    # that are not a direct object fetch; set by the runner on a vector.fetch so a
    # 200-empty result is distinguishable from a real deny (the spec, Class 1).
    access_outcome: AccessOutcome | None = None


# --- Findings ---------------------------------------------------------------


class Finding(SectumModel):
    """A detected cross-tenant leakage result (the engineering spec, section 9).

    Frozen like every other aggregate model. The detection pipeline classifies
    each finding as confirmed or unverified - the false-positive control (the
    engineering spec, section 6.4) - when it constructs the finding.
    """

    finding_id: str
    probe_id: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    status: FindingStatus
    owner_tenant_id: UUID
    observed_in_tenant_id: UUID
    # The user dimension (ADR-0006): set when the leak crosses a user boundary
    # within a tenant. Both ``None`` for a tenant-level finding (unchanged).
    owner_user_id: UUID | None = None
    observed_in_user_id: UUID | None = None
    surface: Surface
    marker_id: str | None = None
    evidence_span: str = ""
    owasp_llm: str = ""
    # Secondary OWASP LLM Top 10 classes this finding also evidences (the spec
    # §18: "LLM08:2025 primary; LLM02/LLM06 secondary"). Empty when the probe
    # declares no secondary mapping.
    owasp_secondary: tuple[str, ...] = ()
    atlas: tuple[str, ...] = ()
    nist: tuple[str, ...] = ()
    remediation_pointer: str = ""


# --- Run results and evidence -----------------------------------------------


class RunMetrics(SectumModel):
    """Aggregate metrics for a run (the engineering spec, section 9)."""

    per_probe_findings: dict[str, int] = Field(default_factory=dict)
    confirmed_findings: int = 0
    retrieval_pivot_rate: float | None = None
    retrieval_pivot_rate_by_model: dict[str, float] = Field(default_factory=dict)
    # Genuine residual: markers still present on a surface that *was* erased (an
    # erasure failure). Caveat counts are tracked separately so a backend with
    # no per-tenant erasure API (attestable-with-caveat, Class 11 hiding place
    # #8) is never conflated with a failure here, in the baseline diff, or in
    # the signed evidence pack.
    erasure_residue: dict[str, int] = Field(default_factory=dict)
    erasure_caveats: dict[str, int] = Field(default_factory=dict)
    side_channel_effect_sizes: dict[str, float] = Field(default_factory=dict)
    # Headline rates for Class 3 (poisoning), Class 6 (inversion), and Class 10
    # (extraction), each in [0, 1]: the fraction of that probe's benign query
    # steps that surfaced a confirmed foreign canary. ``None`` when the probe did
    # not run. Poisoning's rate is the post-plant cross-tenant bleed over an
    # implicit zero baseline - the lure phrase does not exist before the poison is
    # planted - so the rate *is* the delta the spec (section 7, Class 3) calls for.
    poisoning_bleed_delta: float | None = None
    inversion_reconstruction_rate: float | None = None
    extraction_efficiency: float | None = None


class RunResult(SectumModel):
    """The canonical record of one probe run (the engineering spec, section 9)."""

    run_id: str
    scenario_hash: str
    manifest_hash: str
    started_at: UtcDateTime
    finished_at: UtcDateTime
    adapter_versions: dict[str, str] = Field(default_factory=dict)
    probe_versions: dict[str, str] = Field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    schema_version: str = SCHEMA_VERSION


class ControlMapping(SectumModel):
    """A mapping from findings to a compliance framework's controls."""

    framework: str
    control_ids: tuple[str, ...]
    assertion: str


class EvidencePack(SectumModel):
    """A signed, control-mapped evidence bundle (the engineering spec, section 8)."""

    run_result: RunResult
    manifest_hash: str
    tsa_token: str | None = None
    rekor_proof: str | None = None
    control_mappings: tuple[ControlMapping, ...] = ()
    pdf_ref: str | None = None
    # True when the pack was anchored in a transparency log at build time. The
    # flag is bound into the anchored digest, so a verifier requires a valid
    # Rekor inclusion proof whenever it is set: stripping ``rekor_proof`` to
    # skip the check (a downgrade) no longer passes verification.
    anchored_in_log: bool = False
    schema_version: str = SCHEMA_VERSION
