"""Tests for the section 18 compliance-control mappings."""

from datetime import UTC, datetime

from sectum_ai.evidence import COVERAGE_DISCLAIMER, control_mappings
from sectum_ai.spec import ControlMapping, RunMetrics, RunResult


def test_control_mappings_cover_the_expected_frameworks() -> None:
    mappings = control_mappings()
    frameworks = {mapping.framework for mapping in mappings}
    assert {"SOC 2 (TSC)", "GDPR", "EU AI Act", "OWASP LLM Top 10"} <= frameworks
    assert all(isinstance(mapping, ControlMapping) for mapping in mappings)
    assert all(mapping.control_ids and mapping.assertion for mapping in mappings)


def test_gdpr_mapping_names_the_erasure_article() -> None:
    # GDPR spans two mappings - isolation (Art. 25/32) and erasure (Art. 17) - because
    # they require different evidence; the full table names both.
    ids = {i for m in control_mappings() if m.framework == "GDPR" for i in m.control_ids}
    assert "Article 17" in ids
    assert {"Article 25", "Article 32"} <= ids


def test_iso_42001_maps_the_ai_data_and_operation_controls() -> None:
    # ISO/IEC 42001:2023 is the AI-management-system standard; the run speaks to
    # its data-governance and operational-monitoring Annex A controls.
    iso = next(m for m in control_mappings() if m.framework == "ISO/IEC 42001:2023")
    assert "A.7.5" in iso.control_ids  # data provenance
    assert "A.6.2.6" in iso.control_ids  # AI system operation and monitoring


def test_ccpa_mapping_names_the_deletion_right() -> None:
    # The CCPA/CPRA deletion right (§1798.105) is the US parallel to the GDPR
    # Art. 17 erasure wedge.
    ids = {i for m in control_mappings() if m.framework == "CCPA/CPRA" for i in m.control_ids}
    assert "1798.105" in ids


def test_disclaimer_states_the_mappings_are_not_certification() -> None:
    assert "not a legal certification" in COVERAGE_DISCLAIMER


def _run(
    *,
    probes: bool = True,
    erasure: bool = False,
    erasure_only: bool = False,
    provenance: dict[str, str] | None = None,
) -> RunResult:
    moment = datetime(2026, 5, 18, 12, 30, tzinfo=UTC)
    if erasure_only:
        ran = {"gdpr-erasure-verification": "0.11.0"}
    else:
        ran = {"tenant-boundary-fetch": "0.7.1"} if probes else {}
    return RunResult(
        run_id="run-1",
        scenario_hash="s",
        manifest_hash="m",
        started_at=moment,
        finished_at=moment,
        metrics=RunMetrics(
            erasure_coverage={"vector_db": "ERASED"} if (erasure or erasure_only) else {}
        ),
        probe_versions=ran,
        # The mappings need evidence from a LIVE surface; a fixture without
        # provenance would assert nothing.
        surface_provenance={"vector_db": "LIVE"} if provenance is None else provenance,
    )


def test_an_erasure_only_run_asserts_only_the_deletion_controls() -> None:
    """The artifact built for auditors must not assert what the run never tested.

    `sectum-ai erasure` records exactly one probe id, and that id used to satisfy
    the isolation requirement: both shipped erasure sample packs carried all eleven
    mappings, including SOC 2 CC6.x "tested by benign and adversarial probing"
    and EU AI Act Article 15 "robustness ... under adversarial conditions", on the
    strength of a deletion check.
    """
    mappings = control_mappings(_run(erasure_only=True))
    ids = {i for m in mappings for i in m.control_ids}
    assert ids == {"Article 17", "1798.105"}, sorted(ids)
    assert all("adversarial" not in m.assertion for m in mappings)


def test_the_pinned_erasure_probe_ids_match_the_probes_own_declarations() -> None:
    # controls.py cannot import the probes (the evidence package sits below them in
    # the package graph), so it pins their ids. This holds the pin to the source.
    from sectum_ai.evidence.controls import _ERASURE_PROBE_IDS
    from sectum_ai.probes import ErasureProbe, SubjectErasureProbe

    assert {ErasureProbe.id, SubjectErasureProbe.id} == _ERASURE_PROBE_IDS


def test_an_erasure_finding_alone_is_not_isolation_evidence() -> None:
    # Rule 4's reasoning - a finding proves its probe ran - must not let an erasure
    # residual finding smuggle the isolation controls back in.
    from uuid import uuid4

    from sectum_ai.spec import Finding, FindingStatus, Severity, Surface

    run = _run(probes=False, erasure=True).model_copy(
        update={
            "findings": (
                Finding(
                    finding_id="f-1",
                    probe_id="gdpr-erasure-verification",
                    severity=Severity.HIGH,
                    confidence=1.0,
                    status=FindingStatus.CONFIRMED,
                    owner_tenant_id=uuid4(),
                    observed_in_tenant_id=uuid4(),
                    surface=Surface.VECTOR_DB,
                ),
            )
        }
    )
    ids = {i for m in control_mappings(run) for i in m.control_ids}
    assert "CC6.1" not in ids


def test_an_isolation_run_does_not_assert_the_deletion_controls() -> None:
    # The isolation probes cannot produce erasure evidence - that is the separate
    # `sectum-ai erasure` workflow - so a probe run must not assert GDPR Art. 17 or
    # CCPA 1798.105. Asserting a deletion control on the strength of a timing probe
    # is the over-claim the scorecard's Rule 1 forbids, in the output built for
    # compliance consumption.
    ids = {i for m in control_mappings(_run()) for i in m.control_ids}
    assert "Article 17" not in ids
    assert "1798.105" not in ids
    assert {"CC6.1", "Article 25", "1798.100"} <= ids  # isolation controls still asserted


def test_an_erasure_run_does_assert_the_deletion_controls() -> None:
    ids = {i for m in control_mappings(_run(erasure=True)) for i in m.control_ids}
    assert {"Article 17", "1798.105"} <= ids


def test_a_run_that_exercised_nothing_asserts_no_control() -> None:
    # No probes, no findings, no erasure coverage: the record establishes nothing,
    # so it must assert nothing rather than defaulting the table to satisfied.
    assert control_mappings(_run(probes=False)) == ()


def test_an_erasure_run_that_verified_nothing_asserts_no_deletion_control() -> None:
    # The coverage block names every erasure surface, so it is non-empty for a run
    # that scanned nothing: all NOT_COVERED (no baseline / no adapter / out of
    # scope) still signed GDPR Article 17 and CCPA 1798.105 as "verified", and the
    # OSCAL projection rendered them satisfied.
    from sectum_ai.spec import CoverageVerdict

    nothing = dict.fromkeys(("vector_db", "tracing"), CoverageVerdict.NOT_COVERED.value)
    caveat_only = {"vector_db": CoverageVerdict.ATTESTABLE_WITH_CAVEAT.value}
    for coverage in (nothing, caveat_only):
        run = _run(erasure_only=True).model_copy(
            update={"metrics": RunMetrics(erasure_coverage=coverage)}
        )
        assert control_mappings(run) == (), coverage
    residual = _run(erasure_only=True).model_copy(
        update={"metrics": RunMetrics(erasure_coverage={"vector_db": "RESIDUAL"})}
    )
    assert {i for m in control_mappings(residual) for i in m.control_ids} == {
        "Article 17",
        "1798.105",
    }


def test_a_mapping_needs_evidence_from_a_live_surface() -> None:
    # A verdict from the built-in fake describes nothing the operator runs, so a
    # run whose every surface was synthetic (or whose provenance is unrecorded)
    # asserts no control at all - the answer `verify` and `score` already gave it,
    # while the pack, the PDF appendix, and OSCAL still carried every framework.
    assert control_mappings(_run(provenance={"vector_db": "SYNTHETIC"})) == ()
    assert control_mappings(_run(provenance={})) == ()
    # and an erasure verdict counts only on a live surface
    live_elsewhere = _run(
        erasure_only=True, provenance={"tracing": "LIVE", "vector_db": "SYNTHETIC"}
    )
    assert control_mappings(live_elsewhere) == ()
    assert control_mappings(_run(erasure_only=True, provenance={"vector_db": "LIVE"}))


def test_a_row_about_specific_surfaces_needs_one_of_them_live() -> None:
    from sectum_ai.evidence.controls import asserted_surfaces

    mcp_only = _run(provenance={"vector_db": "SYNTHETIC", "mcp": "LIVE"})
    mappings = control_mappings(mcp_only)
    frameworks = {m.framework for m in mappings}
    assert "OWASP LLM Top 10" not in frameworks
    assert "SOC 2 (TSC)" in frameworks
    soc2 = next(m for m in mappings if m.framework == "SOC 2 (TSC)")
    assert soc2.assertion.endswith("Live surfaces: mcp.")
    assert asserted_surfaces(mcp_only, soc2) == ("mcp",)
    vector_live = _run(provenance={"vector_db": "LIVE", "mcp": "SYNTHETIC"})
    owasp = next(m for m in control_mappings(vector_live) if m.framework == "OWASP LLM Top 10")
    assert owasp.assertion.endswith("Live surfaces: vector_db.")


def test_isolation_controls_need_a_surface_an_isolation_probe_drove() -> None:
    # `live` was any live surface at all, so a run whose isolation probes every
    # one ran against a built-in fake, beside a single live surface that only the
    # ERASURE scan touched, asserted eight frameworks' worth of isolation testing
    # - SOC 2 CC6.1/6.6/6.7, EU AI Act 15, HIPAA - off a deletion check.
    moment = datetime(2026, 5, 18, 12, 30, tzinfo=UTC)

    def _mixed(vector: str) -> RunResult:
        return RunResult(
            run_id="run-1",
            scenario_hash="s",
            manifest_hash="m",
            started_at=moment,
            finished_at=moment,
            metrics=RunMetrics(erasure_coverage={"tracing": "ERASED"}),
            probe_versions={"tenant-boundary-fetch": "1", "gdpr-erasure-verification": "1"},
            surface_provenance={"vector_db": vector, "tracing": "LIVE"},
        )

    fake_isolation = {m.framework for m in control_mappings(_mixed("SYNTHETIC"))}
    assert "SOC 2 (TSC)" not in fake_isolation, fake_isolation
    assert "GDPR" in fake_isolation, "the erasure control it DID earn is still asserted"

    # The same run with the vector store live earns the isolation controls.
    assert "SOC 2 (TSC)" in {m.framework for m in control_mappings(_mixed("LIVE"))}
