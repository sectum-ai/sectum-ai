"""NIST OSCAL 1.1.x assessment-results projection of a run.

GRC platforms and auditors increasingly ingest `NIST OSCAL`_ assessment-results
(AR) as the machine-readable form of an assessment. Sectum AI already produces
control-mapped findings, so emitting OSCAL AR lets a consumer pull a Sectum run
into their compliance tooling as a first-class assessment artifact. This is a
projection of :class:`~sectum_ai.spec.RunResult` for *interchange*; the canonical,
signed, tamper-evident record remains ``evidence.json`` (the OSCAL is derived and
unsigned).

Mapping choices (verified against the OSCAL AR 1.1.2 JSON reference and the NIST
``ifa_assessment-results-example.json``):

- one OSCAL **observation** per :class:`~sectum_ai.spec.Finding`: what was tested
  (``methods: ["TEST"]``), the surface it touched, and the marker-grounded
  evidence span. Each observation's ``props`` carry the Sectum finding id, its
  status, the surface, and the owning/observing tenants so the linkage back to
  the signed record is explicit.
- one OSCAL **finding** per mapped framework control (from
  :func:`~sectum_ai.evidence.controls.control_mappings`): its ``target`` is the
  control id (``type: "objective-id"``) and its ``status.state`` reflects the run
  honestly — ``not-satisfied`` when the run confirmed any cross-tenant leak,
  otherwise ``satisfied`` ("tested, no confirmed cross-tenant leakage"). Every
  control finding links to all observations via ``related-observations`` so the
  consumer can trace a control verdict to the evidence behind it. Control linkage
  is run-level because :func:`control_mappings` is run-level — a Sectum run as a
  whole speaks to these controls; it does not vary the mapping per finding.
- **honesty / anti-over-claim**: an OSCAL finding's ``status.state`` is
  ``not-satisfied`` only when a *confirmed* (manifest-grounded) Sectum finding
  exists. An ``UNVERIFIED`` Sectum candidate is recorded as an observation (so the
  evidence is not lost) but never on its own flips a control to ``not-satisfied``
  — a candidate is not a confirmed control failure. The
  :data:`~sectum_ai.evidence.controls.COVERAGE_DISCLAIMER` is embedded in the
  metadata remarks so the OSCAL consumer sees the same caveat the audit PDF
  carries: these mappings are assertions of test coverage, not legal
  certification.

Determinism: every ``uuid`` is derived with ``uuid5`` from the run id (never
``uuid4``), and timestamps come from the run's ``started_at``/``finished_at``, so
the same run renders byte-identical OSCAL — a requirement of the reproducibility
contract (the engineering spec, section 6.5) and the tamper-evident chain.

.. _NIST OSCAL: https://pages.nist.gov/OSCAL/
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sectum_ai.evidence.controls import (
    COVERAGE_DISCLAIMER,
    ERASURE,
    control_mappings,
    erasure_scanned_surfaces,
    live_surfaces,
    mapping_requirement,
)
from sectum_ai.evidence.labels import backing_surface, leak_label
from sectum_ai.spec import CoverageVerdict, Finding, FindingStatus

if TYPE_CHECKING:
    from sectum_ai.spec import ControlMapping, RunResult

OSCAL_VERSION = "1.1.2"
"""The OSCAL model version this projection targets (assessment-results 1.1.x)."""

# A stable namespace for deriving deterministic document/object UUIDs from the run
# id, so the same run always renders the same OSCAL doc (no uuid4). The string is
# arbitrary but fixed; changing it would change every emitted UUID.
_UUID_NS = uuid5(NAMESPACE_URL, "https://sectum.ai/oscal/assessment-results")

# An OSCAL ``prop`` namespace identifying Sectum-specific properties, so an OSCAL
# consumer can tell our props apart from the core OSCAL vocabulary.
_PROP_NS = "https://sectum.ai/ns/oscal"

# OSCAL finding target status states (assessment-results 1.1.2). A run that
# confirmed a cross-tenant leak leaves the tested control objective unsatisfied;
# a run with zero confirmed leaks reads as satisfied for the surfaces it tested.
_STATE_SATISFIED = "satisfied"
_STATE_NOT_SATISFIED = "not-satisfied"


def _oscal_timestamp(value: datetime) -> str:
    """Serialize a datetime to an OSCAL ``date-time-with-timezone`` string.

    OSCAL's timestamp fields (``last-modified``, ``start``, ``end``,
    ``collected``) require an ISO-8601 string with an explicit timezone offset,
    not a bare ``datetime``. This normalizes to UTC the same way the canonical
    run form does (tz-aware values are converted to UTC; a naive value is assumed
    UTC), so the emitted OSCAL is deterministic and ``json.dumps``-safe — the same
    instant always renders the same string regardless of the producer's local
    timezone (the reproducibility contract, the engineering spec section 6.5).
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


def _uuid(*parts: str) -> str:
    """Derive a deterministic UUID (string form) from the run-scoped ``parts``.

    Args:
        *parts: components that, joined, identify the object within a run (e.g.
            the run id plus an observation discriminator). The same parts always
            yield the same UUID, so a run renders byte-identical OSCAL.

    Returns:
        The ``uuid5`` of the joined parts under the Sectum OSCAL namespace, as a
        canonical lowercase UUID string.
    """
    return str(uuid5(_UUID_NS, "\x1f".join(parts)))


def _prop(name: str, value: str) -> dict[str, str]:
    """Build a Sectum-namespaced OSCAL ``prop`` (a ``{name, value, ns}`` object)."""
    return {"name": name, "value": value, "ns": _PROP_NS}


def _observation(run: RunResult, finding: Finding) -> dict[str, Any]:
    """Build one OSCAL ``observation`` from a Sectum finding.

    The observation records *what Sectum tested and saw*: the probe and surface,
    the marker-grounded evidence span, and — via ``props`` — the Sectum finding
    id and status so the OSCAL evidence is traceable back to the signed
    ``evidence.json`` record. ``methods`` is ``["TEST"]`` because every Sectum
    finding is the product of an executed probe; ``collected`` is the run's finish
    time (deterministic, no wall clock).

    Args:
        run: the run the finding belongs to (its id and finish time).
        finding: the Sectum finding to project.

    Returns:
        An OSCAL observation object as a JSON-serialisable ``dict``.
    """
    evidence = finding.evidence_span or (
        f"marker {finding.marker_id} owned by tenant {finding.owner_tenant_id} "
        f"observed in tenant {finding.observed_in_tenant_id}"
    )
    description = (
        f"Sectum AI probe {finding.probe_id!r} tested tenant isolation on the "
        f"{finding.surface.value} surface. {finding.status.value.upper()} "
        f"{finding.severity.value} {leak_label(finding)}: {evidence}"
    )
    props = [
        _prop("sectum-finding-id", finding.finding_id),
        _prop("sectum-status", finding.status.value),
        _prop("sectum-severity", finding.severity.value),
        _prop("sectum-probe-id", finding.probe_id),
        _prop("sectum-surface", finding.surface.value),
        _prop("sectum-owner-tenant-id", str(finding.owner_tenant_id)),
        _prop("sectum-observed-in-tenant-id", str(finding.observed_in_tenant_id)),
    ]
    if finding.marker_id is not None:
        props.append(_prop("sectum-marker-id", finding.marker_id))
    if finding.owasp_llm:
        props.append(_prop("owasp-llm", finding.owasp_llm))
    for technique in finding.atlas:
        props.append(_prop("mitre-atlas", technique))
    for control in finding.nist:
        props.append(_prop("nist-ai-rmf", control))
    return {
        "uuid": _uuid(run.run_id, "observation", finding.finding_id),
        "title": f"{finding.probe_id} on {finding.surface.value}",
        "description": description,
        "methods": ["TEST"],
        "types": ["finding"],
        "props": props,
        "collected": _oscal_timestamp(run.finished_at),
    }


def _finding(
    run: RunResult,
    mapping: ControlMapping,
    control_id: str,
    *,
    has_confirmed_leak: bool,
    has_residual: bool,
    residual_surfaces: tuple[str, ...],
    observation_uuids: list[str],
) -> dict[str, Any]:
    """Build one OSCAL ``finding`` for a single mapped framework control.

    The finding's ``target`` names the control objective (``type:
    "objective-id"``, ``target-id`` the control id) and its ``status.state`` is
    the honest verdict for the run: ``not-satisfied`` when the run confirmed any
    cross-tenant leak, otherwise ``satisfied`` (tested, no confirmed leakage). The
    finding links to *every* observation via ``related-observations`` so a
    consumer can trace the verdict to the evidence behind it.

    Args:
        run: the run being projected (for the deterministic UUID seed).
        mapping: the framework mapping this control belongs to (for its framework
            name and the coverage assertion).
        control_id: the specific control id within the framework (e.g. ``CC6.1``).
        has_confirmed_leak: whether a live surface produced a *confirmed*
            cross-principal leak; only that flips an isolation control to
            ``not-satisfied``.
        has_residual: whether a live erasure surface kept a marker after the
            erasure; only that flips an erasure control to ``not-satisfied``.
        residual_surfaces: the surfaces the residual markers were found on.
        observation_uuids: UUIDs of every observation in the result, linked back.

    Returns:
        An OSCAL finding object as a JSON-serialisable ``dict``.
    """
    if mapping_requirement(mapping) == ERASURE:
        objective = "erasure verification"
        failed = has_residual
        verdict = (
            "Sectum AI found markers remaining, or presumed retained, after the erasure "
            f"on {', '.join(residual_surfaces)}; the erasure objective is not satisfied "
            "for this run."
            if failed
            else "Sectum AI verified the erasure on every live surface it scanned for this run."
        )
    else:
        objective = "tenant isolation"
        failed = has_confirmed_leak
        verdict = (
            "Sectum AI confirmed at least one manifest-grounded cross-principal "
            "leak on a live surface; the tested isolation objective is not satisfied "
            "for this run."
            if failed
            else "Sectum AI tested tenant isolation across the live configured AI "
            "surfaces and confirmed no cross-principal leakage for this run."
        )
    state = _STATE_NOT_SATISFIED if failed else _STATE_SATISFIED
    return {
        "uuid": _uuid(run.run_id, "finding", mapping.framework, control_id),
        "title": f"{mapping.framework} {control_id} — {objective}",
        "description": f"{mapping.assertion} {verdict}",
        "target": {
            "type": "objective-id",
            "target-id": control_id,
            "description": verdict,
            "props": [_prop("framework", mapping.framework)],
            "status": {"state": state, "reason": "tested"},
        },
        "related-observations": [{"observation-uuid": uuid} for uuid in observation_uuids],
    }


def _metadata(run: RunResult, tool_version: str) -> dict[str, Any]:
    """Build the OSCAL ``metadata`` block for the assessment-results document.

    ``last-modified`` is the run's finish time (deterministic), ``version`` is the
    Sectum tool version, ``oscal-version`` is :data:`OSCAL_VERSION`, and the
    :data:`~sectum_ai.evidence.controls.COVERAGE_DISCLAIMER` is embedded in
    ``remarks`` so the OSCAL consumer sees the same coverage caveat the audit PDF
    carries. The producing tool is named via the OSCAL ``assessment-tool`` /
    ``tool`` prop convention through a Sectum-namespaced prop.
    """
    return {
        "title": f"Sectum AI multi-tenant isolation assessment — run {run.run_id}",
        "last-modified": _oscal_timestamp(run.finished_at),
        "version": tool_version,
        "oscal-version": OSCAL_VERSION,
        "props": [
            _prop("assessment-tool", "Sectum AI"),
            _prop("sectum-run-id", run.run_id),
            _prop("sectum-scenario-hash", run.scenario_hash),
            _prop("sectum-manifest-hash", run.manifest_hash),
            # Which stack the document describes, surface by surface; absent, an
            # all-synthetic demo projected exactly like a production assessment.
            *(
                _prop(f"sectum-surface-provenance-{surface}", provenance)
                for surface, provenance in sorted(run.surface_provenance.items())
            ),
        ],
        "remarks": COVERAGE_DISCLAIMER,
    }


def run_to_oscal(run: RunResult, *, tool_version: str = "0") -> dict[str, Any]:
    """Project a :class:`~sectum_ai.spec.RunResult` into an OSCAL 1.1.x AR document.

    Produces a valid NIST OSCAL ``assessment-results`` object: one ``results``
    entry whose ``observations`` carry one entry per Sectum finding (the
    marker-grounded evidence) and whose ``findings`` carry one entry per mapped
    framework control (from
    :func:`~sectum_ai.evidence.controls.control_mappings`), each linking to the
    observations and stating an honest ``status.state``. A run with zero confirmed
    leaks renders as a valid AR reading "tested, no confirmed cross-tenant
    leakage" — never an empty or ambiguous document.

    The document is derived and unsigned; the canonical, signed record remains
    ``evidence.json``. Every UUID is deterministic (``uuid5`` over the run id) and
    every timestamp comes from the run, so the same run renders byte-identical
    OSCAL.

    Args:
        run: the completed run whose findings and control coverage to export.
        tool_version: the Sectum AI version to stamp as the document version.

    Returns:
        An OSCAL ``assessment-results`` 1.1.x document as a JSON-serialisable
        ``dict`` (top-level key ``"assessment-results"``).
    """
    # Only a finding from a LIVE surface speaks to the operator's controls: one
    # from the built-in fake describes that fake (`score` withholds it too), so a
    # confirmed leak on a fake surface used to flip every control not-satisfied on
    # a mixed run, and a clean fake used to earn satisfied. A residual after an
    # erasure is a different failure from a cross-principal leak and moves the
    # erasure controls only.
    live = live_surfaces(run)
    attested = [
        f
        for f in run.findings
        if f.status is FindingStatus.CONFIRMED and backing_surface(f) in live
    ]
    # An erasure verdict comes from the coverage block, not from findings alone:
    # a caveat surface (no per-tenant erasure API, data presumed retained) emits
    # UNVERIFIED findings, and "verified the erasure on every live surface" was
    # rendered over three markers presumed retained.
    residual_surfaces = tuple(
        sorted(
            s
            for s, v in run.metrics.erasure_coverage.items()
            if s in erasure_scanned_surfaces(run) and v != CoverageVerdict.ERASED.value
        )
    )
    has_confirmed_leak = any(leak_label(f) != "residual-data finding" for f in attested)
    has_residual = bool(residual_surfaces)
    erasure_run = bool(run.metrics.erasure_coverage)
    observations = [_observation(run, finding) for finding in run.findings]
    observation_uuids = [observation["uuid"] for observation in observations]

    findings: list[dict[str, Any]] = []
    reviewed_control_ids: list[str] = []
    # A run that touched no live backend (or whose provenance is unrecorded)
    # assessed nobody's controls: its every verdict is about Sectum's built-in
    # fakes, so projecting the mappings as ``satisfied`` control findings asserted
    # a production result a demo run cannot support. The observations still ship
    # (they are what the run saw); the control findings do not - and
    # `control_mappings` returns none for such a run.
    for mapping in control_mappings(run):
        for control_id in mapping.control_ids:
            if control_id not in reviewed_control_ids:
                reviewed_control_ids.append(control_id)
            findings.append(
                _finding(
                    run,
                    mapping,
                    control_id,
                    has_confirmed_leak=has_confirmed_leak,
                    has_residual=has_residual,
                    residual_surfaces=residual_surfaces,
                    observation_uuids=observation_uuids,
                )
            )
    synthetic = sorted(set(run.surface_provenance) - live)
    excluded = (
        " Surfaces that ran against the built-in fake and are excluded from every "
        f"control verdict: {', '.join(synthetic)}."
        if synthetic and live
        else ""
    )

    if not live:
        result_description = (
            "Sectum AI ran its probes against its own built-in synthetic stack only "
            "(or recorded no surface provenance): no surface in this run is known to "
            "be a live, configured backend, so no control objective was assessed and "
            "no control finding is stated. The observations describe that synthetic "
            "stack, not any production system."
        )
    elif erasure_run and not has_confirmed_leak:
        result_description = (
            "Sectum AI scanned an erasure across the live configured AI surfaces. "
            + (
                f"Markers remained, or were presumed retained, on {', '.join(residual_surfaces)}; "
                "see the observations and findings."
                if has_residual
                else "No marker remained on any live surface scanned."
            )
            + excluded
        )
    elif has_confirmed_leak:
        result_description = (
            "Sectum AI provisioned synthetic tenants seeded with cryptographic "
            "canary markers and ran benign and adversarial probes across the "
            "configured AI surfaces. At least one manifest-grounded cross-principal "
            "leak was confirmed on a live surface; see the observations and findings." + excluded
        )
    else:
        result_description = (
            "Sectum AI provisioned synthetic tenants seeded with cryptographic "
            "canary markers and ran benign and adversarial probes across the "
            "configured AI surfaces. No cross-principal leakage was confirmed on "
            "the live surfaces tested." + excluded
        )

    result: dict[str, Any] = {
        "uuid": _uuid(run.run_id, "result"),
        "title": "Multi-tenant isolation verification",
        "description": result_description,
        "start": _oscal_timestamp(run.started_at),
        "end": _oscal_timestamp(run.finished_at),
        # OSCAL requires reviewed-controls on every result: the controls this
        # assessment spoke to (the union of the framework control ids from
        # control_mappings, deduped in stable order).
        "reviewed-controls": {
            "control-selections": [
                {"include-controls": [{"control-id": cid} for cid in reviewed_control_ids]}
            ]
        },
        "observations": observations,
        "findings": findings,
    }

    document_uuid: UUID = uuid5(_UUID_NS, run.run_id)
    return {
        "assessment-results": {
            "uuid": str(document_uuid),
            "metadata": _metadata(run, tool_version),
            # OSCAL AR requires import-ap (a reference to the assessment plan).
            # Sectum emits assessment-results directly from a run with no separate
            # OSCAL assessment-plan document, so the href is a stable, non-resolving
            # placeholder; the real scope is the scenario + ground-truth manifest
            # named in the metadata props (sectum-scenario-hash / -manifest-hash).
            "import-ap": {
                "href": "https://sectum.ai/oscal/no-assessment-plan",
                "remarks": (
                    "Sectum AI emits OSCAL assessment-results directly from a run; "
                    "there is no separate OSCAL assessment-plan. The assessment "
                    "scope is the scenario and ground-truth manifest referenced in "
                    "the metadata props."
                ),
            },
            "results": [result],
        }
    }
