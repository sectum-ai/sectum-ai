# Attack catalog

Each probe is pluggable behind a common `Probe` interface and ships with unit
tests and a deterministic in-memory fake adapter. The catalog grows by phase;
the classes below are implemented today.

| Class | Probe | Surface |
|---|---|---|
| [1 — Direct tenant boundary fetch](class-01-tenant-boundary.md) | `tenant-boundary-fetch` | vector DB |
| [2 — Organic entity-bleed RAG](class-02-rag-entity-bleed.md) | `rag-entity-bleed` | vector DB |
| [3 — Adversarial RAG poisoning](class-03-rag-poisoning.md) | `rag-poisoning` | vector DB |
| [4 — Semantic-cache contamination](class-04-semantic-cache.md) | `semantic-cache-contamination` | semantic cache |
| [5 — KV-cache timing side channel](class-05-kv-cache-timing.md) | `kv-cache-timing` | KV cache |
| [6 — Embedding inversion across tenants](class-06-embedding-inversion.md) | `embedding-inversion` | vector DB |
| [7 — Agent tool-call hijacking](class-07-agent-tool-hijack.md) | `agent-tool-hijack` | MCP |
| [8 — Persistent memory contamination](class-08-memory-contamination.md) | `memory-contamination` | agent memory |
| [9 — LoRA cross-tenant influence](class-09-lora-cross-tenant.md) | `lora-cross-tenant` | model / adapter |
| [10 — IKEA-style benign extraction](class-10-ikea-extraction.md) | `ikea-extraction` | vector DB |
| [11 — GDPR Article 17 erasure](class-11-erasure.md) | `gdpr-erasure-verification` | vector DB |

Every class maps to **OWASP LLM08:2025 — Vector and Embedding Weaknesses**.

All eleven adversarial attack classes are implemented. Class 12 — the
tamper-evident audit chain — is the cross-cutting
[evidence chain](../evidence-chain.md).
