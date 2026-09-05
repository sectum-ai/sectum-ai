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


def _run(*, probes: bool = True, erasure: bool = False, erasure_only: bool = False) -> RunResult:
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
            erasure_coverage={"vector_db": "erased"} if (erasure or erasure_only) else {}
        ),
        probe_versions=ran,
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
