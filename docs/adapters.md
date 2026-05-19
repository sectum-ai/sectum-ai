# Adapters

An adapter connects the substrate and probes to a real system. Every adapter
declares its family and a set of named capabilities, so a probe can state which
capabilities it needs and an adapter reports its isolation posture honestly.

## Families

| Family | Purpose |
|---|---|
| Vector store | Upsert, query, fetch a document by id, and delete a tenant's documents. |
| RAG pipeline | Answer a query from a tenant's session. |
| Observability | Search a tenant's traces for a marker. |
| Agent | Run a task as a tenant. |
| MCP | Enumerate and invoke Model Context Protocol tools within a tenant scope. |
| Cache | Read and write cache entries; report key tenancy. |
| Model | Train per-tenant adapters, run inference, and measure inference latency. |
| Memory | Write and recall long-term agent-memory entries for a tenant. |

## Fakes and live adapters

Every family ships a deterministic in-memory `fake` for offline runs and tests.
The fakes expose isolation knobs — a shared versus per-tenant index, model
weight bleed, a confused-deputy MCP — so a probe can be exercised against both a
leaky and an isolated stack and the contract suite can confirm a fake reports
its capabilities honestly.

Live adapters implement the same family interface. The pgvector, Chroma, and
Weaviate vector stores are tenant-isolated and add a `fetch`-by-id primitive
alongside similarity `query`. The Redis cache prefixes its keys and
tenant-scopes them by default; `tenant_scoped=False` models the shared key
space Class 4 is built to catch. The Phoenix observability adapter maps each
tenant to its own project, so a trace search is scoped to that tenant. The
HTTP RAG and HTTP agent adapters reach a retrieval pipeline or an agent
framework over a small JSON API, so any backend that adopts their
request/response contract works without a backend-specific SDK. The vector,
cache, and observability adapters are verified against docker-compose backends.

Run `sectum adapters` to list the installed adapters and their capabilities.
