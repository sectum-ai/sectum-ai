# Attack catalog

Most probes are pluggable behind a common `Probe` interface (the Class 5, 11 and
A3 probes predate it and are driven directly by the CLI) and ships with unit
tests and a deterministic in-memory fake adapter. The catalog grows by phase;
the classes below are implemented today.

| Class | Probe | ATLAS | Surface |
|---|---|---|---|
| [1 — Direct tenant boundary fetch](class-01-tenant-boundary.md) | `tenant-boundary-fetch` | `AML.T0024` | vector DB |
| [2 — Organic entity-bleed RAG](class-02-rag-entity-bleed.md) | `rag-entity-bleed`, `rag-pipeline-bleed` | `AML.T0024`, `AML.T0057` | vector DB, RAG pipeline |
| [3 — Adversarial RAG poisoning](class-03-rag-poisoning.md) | `rag-poisoning` | `AML.T0020`, `AML.T0024` | vector DB |
| [4 — Semantic-cache contamination](class-04-semantic-cache.md) | `semantic-cache-contamination` | `AML.T0057` | semantic cache |
| [5 — KV-cache timing side channel](class-05-kv-cache-timing.md) | `kv-cache-timing` | — (timing channel) | KV cache |
| [6 — Embedding inversion across tenants](class-06-embedding-inversion.md) | `embedding-inversion` | `AML.T0024`, `AML.T0024.001` | vector DB |
| [7 — Agent tool-call hijacking](class-07-agent-tool-hijack.md) | `agent-tool-hijack`, `agent-framework-hijack` | `AML.T0024`, `AML.T0051.001`, `AML.T0053` | MCP, Agent framework |
| [8 — Persistent memory contamination](class-08-memory-contamination.md) | `memory-contamination` | `AML.T0057` | agent memory |
| [9 — LoRA cross-tenant influence](class-09-lora-cross-tenant.md) | `lora-cross-tenant` | `AML.T0024`, `AML.T0024.000`, `AML.T0057` | model / adapter |
| [10 — IKEA-style benign extraction](class-10-ikea-extraction.md) | `ikea-extraction` | `AML.T0024`, `AML.T0057` | vector DB |
| [11 — GDPR Article 17 erasure](class-11-erasure.md) | `gdpr-erasure-verification`, `gdpr-subject-erasure-verification` | — (control check) | the eight erasure surfaces, narrowed by `--scope` |
| [13 — Multi-modal RAG entity-bleed](class-13-multimodal-rag-bleed.md) | `multimodal-rag-bleed` | `AML.T0024`, `AML.T0057` | vector DB (multi-modal) |

Every class maps to **OWASP LLM08:2025 — Vector and Embedding Weaknesses** and
**NIST AI RMF MEASURE 2.7** (security/resilience measurement). The MITRE ATLAS
technique IDs vary by class — see each page for the rationale.

All twelve attack-catalog classes (1–11 and 13) are implemented (Class 11 is a
control check rather than an adversarial probe). Class 12 — the
tamper-evident audit chain — is the cross-cutting
[evidence chain](../evidence-chain.md), which is why the attack-class numbering skips
it.

The "vector DB" surface above is the *slot* those probes drive, and an application's
own resource API can fill it (the `app` adapter family, [configuration](../configuration.md)).
Against it, Classes 1, 2, 3, and 10 run unmodified with their findings recorded under the
`api` surface; Classes 6 and 13 are skipped and score `NOT_COVERED`, because both describe
a vector-space effect and an application's search is not an embedding space.
