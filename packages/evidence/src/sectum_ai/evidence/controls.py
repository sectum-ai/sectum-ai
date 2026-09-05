"""Compliance control mappings for Sectum AI evidence (the engineering spec, section 18).

These map a Sectum AI verification run to the specific framework controls its
evidence speaks to. They are assertions of test coverage, not a legal
certification of compliance - see ``COVERAGE_DISCLAIMER``.

Each mapping declares the *evidence it requires*, and :func:`control_mappings`
filters by what a given run actually produced. A run only asserts a control it
earned: the deletion controls (GDPR Article 17, CCPA 1798.105) need erasure
coverage, which the isolation probes structurally cannot produce - they are the
separate ``sectum-ai erasure`` workflow's output. Without that filter a run of a
single probe emitted the same fully-satisfied 9-framework assessment as a full
suite, which is the over-claim this product exists to refuse.
"""

from sectum_ai.spec import ControlMapping, CoverageVerdict, RunResult, SurfaceProvenance

COVERAGE_DISCLAIMER = (
    "These control mappings assert that Sectum AI produced test-coverage "
    "evidence for the named controls. They are not a legal certification of "
    "compliance and do not substitute for an audit or a Data Protection Impact "
    "Assessment."
)

# What a mapping needs before a run may assert it.
ISOLATION = "isolation"  # at least one isolation probe ran, against a live surface
ERASURE = "erasure"  # an erasure surface scanned to a verdict, on a live backend
_ISOLATION = ISOLATION
_ERASURE = ERASURE

# The erasure probes are control checks, not isolation probes, so a run in which
# only they executed has produced no isolation evidence. Their ids are pinned here
# rather than imported: the evidence package sits below probes in the package graph
# (ADR-0004). tests/unit/test_controls.py holds this set to the probes' own
# declarations so the two cannot drift.
_ERASURE_PROBE_IDS = frozenset({"gdpr-erasure-verification", "gdpr-subject-erasure-verification"})
# The coverage verdicts that mean a surface was scanned and answered: a run whose
# every surface is NOT_COVERED (or attestable-with-caveat, where nothing was
# deleted) verified no erasure, whatever its coverage block's length.
_ERASURE_VERDICTS = frozenset({CoverageVerdict.ERASED.value, CoverageVerdict.RESIDUAL.value})

# Framework -> control IDs -> what a Sectum AI verification run asserts about
# them -> the evidence required to assert it (the engineering spec, section 18).
# (framework, control ids, assertion, requirement, surfaces). ``surfaces`` names
# the surfaces an assertion is about; empty means any surface an isolation probe
# exercised live. A row was asserted on the strength of ANY live surface - the
# OWASP row ("vector and embedding weaknesses") on a run whose only live surface
# was MCP and whose vector store was the leaking fake.
_CONTROL_TABLE: tuple[tuple[str, tuple[str, ...], str, str, tuple[str, ...]], ...] = (
    (
        "SOC 2 (TSC)",
        ("CC6.1", "CC6.6", "CC6.7"),
        "Tenant logical separation tested by benign and adversarial probing "
        "across the AI surfaces.",
        _ISOLATION,
        (),
    ),
    (
        "ISO/IEC 27001:2022",
        ("A.5.15", "A.8.3", "A.8.12"),
        "Cross-tenant information leakage tested; residual leakage itemized.",
        _ISOLATION,
        (),
    ),
    (
        "ISO/IEC 42001:2023",
        ("A.6.2.6", "A.7.2", "A.7.5"),
        "Per-tenant data management and provenance in the AI system tested; "
        "isolation verified under AI system operation and monitoring.",
        _ISOLATION,
        (),
    ),
    (
        "GDPR",
        ("Article 25", "Article 32"),
        "Tenant isolation tested across the AI surfaces.",
        _ISOLATION,
        (),
    ),
    (
        "GDPR",
        ("Article 17",),
        "Erasure across the AI surfaces verified.",
        _ERASURE,
        (),
    ),
    (
        "CCPA/CPRA",
        ("1798.100", "1798.150"),
        "Segregation of consumer data tested across the AI surfaces.",
        _ISOLATION,
        (),
    ),
    (
        "CCPA/CPRA",
        ("1798.105",),
        "Deletion of a consumer's personal information across the AI surfaces verified.",
        _ERASURE,
        (),
    ),
    (
        "EU AI Act",
        ("Article 15",),
        "Robustness of tenant isolation tested under benign and adversarial conditions.",
        _ISOLATION,
        (),
    ),
    (
        "HIPAA",
        ("164.312(a)(1)", "164.312(c)(1)", "164.312(e)(1)"),
        "Segregation of regulated tenant data verified across the AI surfaces.",
        _ISOLATION,
        (),
    ),
    (
        "NIST AI RMF",
        ("MEASURE 2.7", "MANAGE 2.x"),
        "Documented measurement of multi-tenant security risk.",
        _ISOLATION,
        (),
    ),
    (
        "OWASP LLM Top 10",
        ("LLM08:2025",),
        "Direct test coverage of vector and embedding multi-tenant weaknesses.",
        _ISOLATION,
        ("vector_db", "api", "rag_pipeline"),
    ),
)


def _run_supports(run: RunResult, requirement: str, surfaces: tuple[str, ...] = ()) -> bool:
    """Whether ``run`` produced the evidence ``requirement`` names, on ``surfaces``.

    Isolation evidence counts a finding as well as ``probe_versions``: a finding is
    itself proof its probe executed, the same reasoning ``score._confirmed_probe_ids``
    applies, so a record whose bookkeeping disagrees with its own findings cannot
    drop a control it demonstrably tested. An erasure probe is neither: a run in
    which only ``gdpr-erasure-verification`` executed used to satisfy this test and
    ship SOC 2 / ISO / EU AI Act mappings asserting "tested by adversarial probing"
    on the strength of a deletion check, in the artifact built for auditors.
    """
    live = live_surfaces(run)
    if surfaces:
        live = live & frozenset(surfaces)
    if requirement == _ERASURE:
        # The coverage block names every erasure surface, so it is non-empty for a
        # run that verified nothing (all NOT_COVERED, or only caveats). Only a
        # surface that was actually scanned to a verdict - on a live backend - is
        # erasure evidence.
        return any(
            verdict in _ERASURE_VERDICTS and surface in live
            for surface, verdict in run.metrics.erasure_coverage.items()
        )
    exercised = set(run.probe_versions) | {finding.probe_id for finding in run.findings}
    # A verdict from the built-in fake describes nothing the operator runs, so a
    # run whose every surface was synthetic (or whose provenance is unrecorded)
    # asserts no control at all - the same answer `verify` and `score` give it.
    return bool(exercised - _ERASURE_PROBE_IDS) and bool(live)


def asserted_surfaces(run: RunResult, mapping: ControlMapping) -> tuple[str, ...]:
    """The live surfaces ``mapping`` speaks for in ``run``, in catalog order."""
    row = next(
        (r for r in _CONTROL_TABLE if r[0] == mapping.framework and r[1] == mapping.control_ids),
        None,
    )
    live = live_surfaces(run)
    if row is not None and row[4]:
        live = live & frozenset(row[4])
    if row is not None and row[3] == _ERASURE:
        live = frozenset(
            s
            for s, v in run.metrics.erasure_coverage.items()
            if s in live and v in _ERASURE_VERDICTS
        )
    return tuple(sorted(live))


def live_surfaces(run: RunResult) -> frozenset[str]:
    """The surfaces this run exercised against a live backend."""
    return frozenset(
        surface
        for surface, provenance in run.surface_provenance.items()
        if provenance == SurfaceProvenance.LIVE.value
    )


def mapping_requirement(mapping: ControlMapping) -> str:
    """Whether ``mapping`` rests on isolation evidence or on erasure evidence."""
    for framework, control_ids, _assertion, requirement, _surfaces in _CONTROL_TABLE:
        if framework == mapping.framework and control_ids == mapping.control_ids:
            return requirement
    return _ISOLATION


def control_mappings(run: RunResult | None = None) -> tuple[ControlMapping, ...]:
    """Return the framework control mappings a Sectum AI run speaks to.

    With ``run``, only the mappings that run's evidence supports: a control is
    asserted because the run produced evidence for it, never by default. With no
    ``run`` this is the full table - what Sectum can attest to in principle -
    which is what the docs and the catalog describe.
    """
    if run is None:
        return tuple(
            ControlMapping(framework=framework, control_ids=control_ids, assertion=assertion)
            for framework, control_ids, assertion, _requirement, _surfaces in _CONTROL_TABLE
        )
    mappings: list[ControlMapping] = []
    for framework, control_ids, assertion, requirement, surfaces in _CONTROL_TABLE:
        if not _run_supports(run, requirement, surfaces):
            continue
        mapping = ControlMapping(framework=framework, control_ids=control_ids, assertion=assertion)
        # The assertion names the live surfaces it rests on, inside the signed
        # pack: "across the AI surfaces" read as all of them.
        covered = ", ".join(asserted_surfaces(run, mapping))
        mappings.append(
            mapping.model_copy(update={"assertion": f"{assertion} Live surfaces: {covered}."})
        )
    return tuple(mappings)
