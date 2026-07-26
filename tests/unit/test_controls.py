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


def _run(*, probes: bool = True, erasure: bool = False) -> RunResult:
    moment = datetime(2026, 5, 18, 12, 30, tzinfo=UTC)
    return RunResult(
        run_id="run-1",
        scenario_hash="s",
        manifest_hash="m",
        started_at=moment,
        finished_at=moment,
        metrics=RunMetrics(erasure_coverage={"vector_db": "erased"} if erasure else {}),
        probe_versions={"tenant-boundary-fetch": "0.7.1"} if probes else {},
    )


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
