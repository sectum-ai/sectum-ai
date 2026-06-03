# Compliance mappings

Each finding carries the control identifiers it speaks to, and the audit pack
renders a control-by-control coverage appendix. Mappings are **assertions of
test coverage, not legal certification** — the reports say so explicitly.

| Framework | Controls | What the evidence asserts |
|---|---|---|
| SOC 2 (TSC) | CC6.1, CC6.6, CC6.7 | Tenant logical separation verified by adversarial and benign probing across surfaces. |
| ISO/IEC 27001:2022 | A.5.15, A.8.3, A.8.12 | Cross-tenant leakage tested; residual leakage itemized. |
| GDPR | Art. 17, Art. 32, Art. 25 | Erasure across AI surfaces verified; tenant isolation tested. |
| EU AI Act | Art. 15 | Robustness of tenant isolation under benign and adversarial conditions. |
| HIPAA | §164.312(a)(1), (c)(1), (e)(1) | PHI tenant segregation verified. |
| NIST AI RMF | MEASURE 2.7, MANAGE 2.x | Documented measurement of multi-tenant security risk. |
| OWASP LLM Top 10 | LLM08:2025 | Direct test coverage of vector and embedding multi-tenant weaknesses. |

The control identifiers are applied by `sectum-ai-evidence` (`controls.py`); the
`ControlMapping` model that records them in a pack lives in `sectum-ai-spec` and
is versioned by the shared `SCHEMA_VERSION` that every evidence pack stamps.
