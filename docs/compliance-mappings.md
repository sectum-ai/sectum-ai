# Compliance mappings

Each finding carries its OWASP, ATLAS, and NIST AI RMF identifiers; the framework
control mappings below are pack-level, and the audit pack
renders a control-by-control coverage appendix. Mappings are **assertions of
test coverage, not legal certification** — the reports say so explicitly.

| Framework | Controls | What the evidence asserts |
|---|---|---|
| SOC 2 (TSC) | CC6.1, CC6.6, CC6.7 | Tenant logical separation tested by benign and adversarial probing across the AI surfaces. |
| ISO/IEC 27001:2022 | A.5.15, A.8.3, A.8.12 | Cross-tenant information leakage tested; residual leakage itemized. |
| ISO/IEC 42001:2023 | A.6.2.6, A.7.2, A.7.5 | Per-tenant data management and provenance in the AI system tested; isolation verified under operation and monitoring. |
| GDPR | Art. 17, Art. 32, Art. 25 | Erasure across AI surfaces verified; tenant isolation tested. |
| CCPA/CPRA | §1798.105, §1798.100, §1798.150 | Deletion of a consumer's personal information across the AI surfaces verified; consumer-data segregation tested. |
| EU AI Act | Art. 15 | Robustness of tenant isolation under benign and adversarial conditions. |
| HIPAA | §164.312(a)(1), (c)(1), (e)(1) | PHI tenant segregation verified. |
| NIST AI RMF | MEASURE 2.7, MANAGE 2.x | Documented measurement of multi-tenant security risk. |
| OWASP LLM Top 10 | LLM08:2025 | Direct test coverage of vector and embedding multi-tenant weaknesses. |

A pack carries only the mappings its run supports, and only evidence from a
**live** surface counts: a verdict from the built-in fake describes nothing the
operator runs, so a run whose every surface was synthetic (or whose provenance
is unrecorded) asserts no control at all — the same answer `verify` and `score`
give it. The isolation rows need at least one isolation probe to have run (the
two erasure probes do not count) against a live surface; a row about specific
surfaces — OWASP LLM08:2025, "vector and embedding weaknesses", is about the
vector store, an application API in that slot, and the RAG pipeline — needs one of
*those* live, so it is not asserted on a run whose only live surface was MCP. The
GDPR Art. 17 and CCPA §1798.105 rows need a live erasure surface scanned to an
`ERASED` or `RESIDUAL` verdict — a run whose coverage block is all `NOT_COVERED`
or attestable-with-caveat verified no erasure and asserts neither. Every mapping
in a pack ends with the live surfaces it rests on ("Live surfaces: mcp."), so
"across the AI surfaces" never reads as all of them. The demo and the shipped
sample packs, which run against the fakes, therefore carry no mappings.

The control identifiers are applied by `sectum-ai-evidence` (`controls.py`); the
`ControlMapping` model that records them in a pack lives in `sectum-ai-spec` and
is versioned by the shared `SCHEMA_VERSION` that every evidence pack stamps.
