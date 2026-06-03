"""Named, sellable probe suites (the engineering spec, sections 10 and 19).

A *suite* fixes a probe set plus the compliance frameworks it speaks to, so an
operator runs a named, control-mapped subset for a specific SKU
(`sectum-ai probe --suite soc2-tenant-isolation`) instead of hand-picking probes.
The probe ids are validated against the live catalog by the test suite, so a
suite can never name a probe that does not exist. See ``docs/skus.md``.

The GDPR Article 17 erasure-attestation SKU is **not** a probe suite: it is the
standalone ``sectum-ai erasure`` workflow (Class 11). Continuous verification is the
default ``sectum-ai probe`` (every probe), so it needs no named suite.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Suite:
    """A named probe set bound to the compliance frameworks it provides evidence for."""

    name: str
    description: str
    probe_ids: tuple[str, ...]
    frameworks: tuple[str, ...]
    # Class 5 (KV-cache timing) is a separate statistical workflow, not a
    # plan/detect probe, so suites opt into it explicitly.
    include_kv_timing: bool = field(default=False)


SUITES: dict[str, Suite] = {
    "soc2-tenant-isolation": Suite(
        name="soc2-tenant-isolation",
        description=(
            "Curated cross-tenant isolation probes for a SOC 2 / ISO 27001 "
            "tenant-isolation evidence pack: the direct logical-separation, "
            "boundary, and segregation checks an auditor expects."
        ),
        probe_ids=(
            "tenant-boundary-fetch",
            "rag-entity-bleed",
            "rag-pipeline-bleed",
            "semantic-cache-contamination",
            "agent-tool-hijack",
            "agent-framework-hijack",
            "memory-contamination",
            "embedding-inversion",
            "lora-cross-tenant",
        ),
        frameworks=(
            "SOC 2 CC6.1",
            "SOC 2 CC6.6",
            "SOC 2 CC6.7",
            "ISO 27001 A.8.3",
            "ISO 27001 A.8.12",
        ),
        include_kv_timing=True,
    ),
    "owasp-llm08": Suite(
        name="owasp-llm08",
        description=(
            "Full OWASP LLM08:2025 (Vector & Embedding Weaknesses) coverage: every "
            "adversarial probe in the catalog - the continuous-verification set."
        ),
        probe_ids=(
            "tenant-boundary-fetch",
            "rag-entity-bleed",
            "rag-pipeline-bleed",
            "semantic-cache-contamination",
            "lora-cross-tenant",
            "agent-tool-hijack",
            "agent-framework-hijack",
            "memory-contamination",
            "embedding-inversion",
            "ikea-extraction",
            "rag-poisoning",
        ),
        frameworks=("OWASP LLM08:2025", "NIST AI RMF MEASURE 2.7"),
        include_kv_timing=True,
    ),
}
