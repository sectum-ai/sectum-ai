"""Compliance control mappings for Sectum AI evidence (the engineering spec, section 18).

These map a Sectum AI verification run to the specific framework controls its
evidence speaks to. They are assertions of test coverage, not a legal
certification of compliance - see ``COVERAGE_DISCLAIMER``.
"""

from sectum_ai.spec import ControlMapping

COVERAGE_DISCLAIMER = (
    "These control mappings assert that Sectum AI produced test-coverage "
    "evidence for the named controls. They are not a legal certification of "
    "compliance and do not substitute for an audit or a Data Protection Impact "
    "Assessment."
)

# Framework -> control IDs -> what a Sectum AI verification run asserts about
# them (the engineering spec, section 18).
_CONTROL_TABLE: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "SOC 2 (TSC)",
        ("CC6.1", "CC6.6", "CC6.7"),
        "Tenant logical separation tested by benign and adversarial probing "
        "across the AI surfaces.",
    ),
    (
        "ISO/IEC 27001:2022",
        ("A.5.15", "A.8.3", "A.8.12"),
        "Cross-tenant information leakage tested; residual leakage itemized.",
    ),
    (
        "ISO/IEC 42001:2023",
        ("A.6.2.6", "A.7.2", "A.7.5"),
        "Per-tenant data management and provenance in the AI system tested; "
        "isolation verified under AI system operation and monitoring.",
    ),
    (
        "GDPR",
        ("Article 17", "Article 25", "Article 32"),
        "Erasure across the AI surfaces verified; tenant isolation tested.",
    ),
    (
        "CCPA/CPRA",
        ("1798.105", "1798.100", "1798.150"),
        "Deletion of a consumer's personal information across the AI surfaces "
        "verified; segregation of consumer data tested.",
    ),
    (
        "EU AI Act",
        ("Article 15",),
        "Robustness of tenant isolation tested under benign and adversarial conditions.",
    ),
    (
        "HIPAA",
        ("164.312(a)(1)", "164.312(c)(1)", "164.312(e)(1)"),
        "Segregation of regulated tenant data verified across the AI surfaces.",
    ),
    (
        "NIST AI RMF",
        ("MEASURE 2.7", "MANAGE 2.x"),
        "Documented measurement of multi-tenant security risk.",
    ),
    (
        "OWASP LLM Top 10",
        ("LLM08:2025",),
        "Direct test coverage of vector and embedding multi-tenant weaknesses.",
    ),
)


def control_mappings() -> tuple[ControlMapping, ...]:
    """Return the framework control mappings a Sectum AI verification run speaks to."""
    return tuple(
        ControlMapping(framework=framework, control_ids=control_ids, assertion=assertion)
        for framework, control_ids, assertion in _CONTROL_TABLE
    )
