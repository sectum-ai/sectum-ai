"""Pydantic data models for Sectum AI (the engineering spec, section 9).

Every aggregate model carries ``schema_version``. Models are frozen: substrate
generation produces them and nothing mutates them afterwards, which keeps the
reproducibility contract (the engineering spec, section 6.5) easy to reason about.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sectum.spec.enums import FindingStatus, MarkerType, Severity, Surface

SCHEMA_VERSION = "0.1.0"
"""Version stamped onto every aggregate model; bumped on any schema change."""


class SectumModel(BaseModel):
    """Base model for all Sectum AI schemas: immutable, rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Scenario inputs --------------------------------------------------------


class SyntheticTenantSpec(SectumModel):
    """Configuration for one synthetic tenant (the engineering spec, section 6.1)."""

    tenant_id: UUID
    display_name: str
    industry: str
    locale: str = "en-US"
    corpus_size: int = Field(gt=0)


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


# --- Markers and corpus -----------------------------------------------------


class PlantedLocation(SectumModel):
    """Where a marker was planted within a document."""

    doc_id: str
    field: str  # one of: body, title, metadata, tags


class Marker(SectumModel):
    """A planted canary whose appearance in the wrong tenant proves leakage."""

    marker_id: str
    marker_type: MarkerType
    owner_tenant_id: UUID
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


# --- Probe execution --------------------------------------------------------


class ProbeStep(SectumModel):
    """A single planned probe action issued from one tenant's session."""

    step_id: str
    probe_id: str
    actor_tenant_id: UUID
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


class Finding(BaseModel):
    """A detected cross-tenant leakage result (the engineering spec, section 9).

    Not frozen: a finding's status may be downgraded from confirmed to
    unverified by the false-positive control (the engineering spec, section 6.4).
    """

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    probe_id: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    status: FindingStatus
    owner_tenant_id: UUID
    observed_in_tenant_id: UUID
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
