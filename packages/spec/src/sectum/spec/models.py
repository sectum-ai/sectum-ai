"""Pydantic data models for Sectum AI (the engineering spec, section 9).

Every aggregate model carries ``schema_version``. Models are frozen: substrate
generation produces them and nothing mutates them afterwards, which keeps the
reproducibility contract (the engineering spec, section 6.5) easy to reason about.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sectum.spec.enums import FindingStatus, MarkerType, PrincipalKind, Severity, Surface

SCHEMA_VERSION = "0.1.0"
"""Version stamped onto every aggregate model; bumped on any schema change."""


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
    plaintext: str
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


class GroundTruthManifest(SectumModel):
    """Authoritative record of which marker belongs to which tenant.

    The manifest is a pure function of the scenario and seed; it carries no
    wall-clock time so the reproducibility contract holds byte-for-byte. Its
    canonical hash is computed via ``sectum.spec.hashing.canonical_hash``.
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
    erasure_residue: dict[str, int] = Field(default_factory=dict)
    side_channel_effect_sizes: dict[str, float] = Field(default_factory=dict)


class RunResult(SectumModel):
    """The canonical record of one probe run (the engineering spec, section 9)."""

    run_id: str
    scenario_hash: str
    manifest_hash: str
    started_at: datetime
    finished_at: datetime
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
    schema_version: str = SCHEMA_VERSION
