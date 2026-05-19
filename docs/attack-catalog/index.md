# Attack catalog

Each probe is pluggable behind a common `Probe` interface and ships with unit
tests and a deterministic in-memory fake adapter. The catalog grows by phase;
the classes below are implemented today.

| Class | Probe | Surface |
|---|---|---|
| [1 — Direct tenant boundary fetch](class-01-tenant-boundary.md) | `tenant-boundary-fetch` | vector DB |
| [2 — Organic entity-bleed RAG](class-02-rag-entity-bleed.md) | `rag-entity-bleed` | vector DB |
| [4 — Semantic-cache contamination](class-04-semantic-cache.md) | `semantic-cache-contamination` | semantic cache |
| [7 — Agent tool-call hijacking](class-07-agent-tool-hijack.md) | `agent-tool-hijack` | MCP |
| [8 — Persistent memory contamination](class-08-memory-contamination.md) | `memory-contamination` | agent memory |
| [9 — LoRA cross-tenant influence](class-09-lora-cross-tenant.md) | `lora-cross-tenant` | model / adapter |
| [11 — GDPR Article 17 erasure](class-11-erasure.md) | `gdpr-erasure-verification` | vector DB |

Every class maps to **OWASP LLM08:2025 — Vector and Embedding Weaknesses**.

Classes 3, 5, 6, and 10 are on the roadmap. Class 12 — the tamper-evident audit
chain — is the cross-cutting [evidence chain](../evidence-chain.md).
