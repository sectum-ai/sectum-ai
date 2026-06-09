"""Tests for the section 18 compliance-control mappings."""

from sectum_ai.evidence import COVERAGE_DISCLAIMER, control_mappings
from sectum_ai.spec import ControlMapping


def test_control_mappings_cover_the_expected_frameworks() -> None:
    mappings = control_mappings()
    frameworks = {mapping.framework for mapping in mappings}
    assert {"SOC 2 (TSC)", "GDPR", "EU AI Act", "OWASP LLM Top 10"} <= frameworks
    assert all(isinstance(mapping, ControlMapping) for mapping in mappings)
    assert all(mapping.control_ids and mapping.assertion for mapping in mappings)


def test_gdpr_mapping_names_the_erasure_article() -> None:
    gdpr = next(mapping for mapping in control_mappings() if mapping.framework == "GDPR")
    assert "Article 17" in gdpr.control_ids


def test_iso_42001_maps_the_ai_data_and_operation_controls() -> None:
    # ISO/IEC 42001:2023 is the AI-management-system standard; the run speaks to
    # its data-governance and operational-monitoring Annex A controls.
    iso = next(m for m in control_mappings() if m.framework == "ISO/IEC 42001:2023")
    assert "A.7.5" in iso.control_ids  # data provenance
    assert "A.6.2.6" in iso.control_ids  # AI system operation and monitoring


def test_ccpa_mapping_names_the_deletion_right() -> None:
    # The CCPA/CPRA deletion right (§1798.105) is the US parallel to the GDPR
    # Art. 17 erasure wedge.
    ccpa = next(m for m in control_mappings() if m.framework == "CCPA/CPRA")
    assert "1798.105" in ccpa.control_ids


def test_disclaimer_states_the_mappings_are_not_certification() -> None:
    assert "not a legal certification" in COVERAGE_DISCLAIMER
