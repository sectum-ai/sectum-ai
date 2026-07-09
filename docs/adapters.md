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
| Search index | Search and delete a tenant's entries in a derived full-text index (Class 11). |
| Eval set | Search and delete a tenant's golden eval-set fixtures (Class 11). |
| Backup | Search and delete a tenant's data in a backup / snapshot store; reports attestable-with-caveat when no per-tenant purge exists (Class 11, hiding place #7). |

## Fakes and live adapters

Every family ships a deterministic in-memory `fake` for offline runs and tests.
The fakes expose isolation knobs — a shared versus per-tenant index, model
weight bleed, a confused-deputy MCP — so a probe can be exercised against both a
leaky and an isolated stack and the contract suite can confirm a fake reports
its capabilities honestly.

Live adapters implement the same family interface. This section is the narrative
tour; for the full per-family reference — every `kind`, its fields, and how it
scopes and erases a tenant — see [configuration.md](configuration.md).

**Vector stores.** The pgvector, Chroma, Weaviate, Qdrant, OpenSearch, and Milvus
stores are tenant-isolated — each tenant gets its own table/collection/index — and
add a `fetch`-by-id primitive alongside similarity `query`; the Pinecone and Azure
AI Search stores give each tenant its own namespace/index on a hosted service and
are verified by an opt-in live test (no local backend). Qdrant (`kind: qdrant`,
`[qdrant]`) and OpenSearch (`kind: opensearch`, `[opensearch]`) are self-hosted, so
each ships a docker-compose service and a live integration test in CI. Milvus
(`kind: milvus`, `[milvus]`) is also self-hosted but heavier (it needs etcd and
minio), so its compose service is gated behind the `milvus` profile and its live
integration test runs locally (`docker compose --profile milvus up -d`) rather than
in CI. Azure AI Search uses `kind: azure-search`, `[azure-search]`.

**Cache.** The Redis cache prefixes its keys and tenant-scopes them by default;
`tenant_scoped=False` models the shared key space Class 4 is built to catch.

**Memory.** The Redis memory store (`kind: redis`, the `[redis]` extra) keeps each
tenant's long-term agent-memory entries in a prefixed per-tenant list and recalls by
keyword; it is tenant-scoped by default, so `shared_memory=True` models the single
shared memory space Class 8 (persistent memory contamination) is built to catch, and
`user_scoped=True` isolates users within a tenant (ADR-0006). `soft_delete=True`
acknowledges a delete but keeps the entries — the Class 11 erasure residue.

**Observability — and the erasure caveat.** Six trace backends are wired, and
they split into two groups that matter for the Class 11 erasure wedge.
*Erasable* backends expose a real per-tenant delete: Phoenix and LangSmith each
map a tenant to its own project and delete it on erasure, while Langfuse (its v3
SDK binds one project per key pair) instead scopes each tenant by trace `user_id`
within a single project and bulk-deletes that tenant's traces. *Read-only*
backends have no programmatic per-tenant erasure API: Helicone (queried by a
custom `Helicone-Property-Tenant`), Datadog (queried by a `@tenant` span tag,
deletion governed by retention policy), and the generic OpenTelemetry reader
(`otel` — a thin shim over Jaeger / Tempo / Grafana / a vendor backend, scoped by
the `tenant.id` resource attribute, treating a `405`/`501` from its scoped
`DELETE` as "no delete API"). For all three, `delete(tenant)` raises
`ErasureUnsupported`, so Class 11 records that surface as
**attestable-with-caveat** — the data is presumed retained until it ages out of
the retention window, a documented backend limitation, never a clean pass and
never counted as an erasure failure. Every observability adapter scans the
trace's own content (name plus attributes or body) for the marker, so a backend
that quietly ignores the tenant filter is itself caught.

**RAG.** The HTTP RAG pipeline reaches any retrieval backend that adopts its
small `{tenant, query}` → `{answer, retrieved}` JSON contract, no backend SDK
required; the LangChain pipeline wraps any LangChain `Runnable` (a composed LCEL
chain), so an existing RAG chain can be probed in place.

**Agents.** Alongside the HTTP agent (the same JSON-contract approach for any
framework), five framework-native agents are wired: LangGraph (a compiled
`StateGraph` invoked with a per-tenant `thread_id`), CrewAI (a `Crew` kicked off
per tenant), AutoGen (an assistant / user-proxy pair), OpenAI Assistants (one
`Thread` cached per tenant), and Anthropic tool-use (the native Messages tool-use
loop with per-tenant history). Each carries the tenant scope into the run — via a
`[tenant:<hex>]` message prefix or a templated input — so a tenant-aware tool
reads the scope from its own call arguments; losing that scope is the
cross-tenant tool-call hijack Class 7 examines.

**Model.** The HuggingFace LoRA model fine-tunes a per-tenant PEFT adapter on a
base causal LM and routes inference to the caller's adapter; its `adapter_bleed`
knob merges every tenant's LoRA into every inference — the Class 9 weight-bleed
leak. The vLLM model is **serving-only**: it reaches a vLLM server over its
OpenAI-compatible API to run inference and measure time-to-first-token (the
Class 5 KV-prefix-cache timing channel), but it trains no per-tenant adapter, so
it reports the `shared_prefix_cache` capability and not `per_tenant_adapter` —
`sectum-ai probe` skips Class 9 for it, and a Class 11 erasure leaves the model
surface `NOT_COVERED`. The TGI model is the same serving-only shape over
HuggingFace Text Generation Inference's native text-generation API.

**MCP.** The MCP client speaks the Model Context Protocol over either a stdio
subprocess or a streamable HTTP session; a generic MCP call carries no tenant
identity, which is the confused-deputy gap Class 7 examines.

**Extras and verification.** The framework- and SDK-backed adapters are optional
extras, imported lazily so the base install stays light:
`pip install sectum-ai-adapters[<name>]` for `huggingface`, `vllm`, `tgi`,
`rag-langchain`, `langgraph`, `crewai`, `autogen`, `openai-assistants`, or
`anthropic-tooluse`.
The Helicone, Datadog, and OpenTelemetry readers and the HTTP RAG / agent / MCP
adapters use only the standard library. The pgvector, Chroma, Weaviate, Qdrant,
OpenSearch, Redis, and Phoenix adapters run against docker-compose backends in CI
(the **Integration** job); Milvus runs against its profile-gated compose service
locally. The hosted and SDK-backed adapters are exercised by tests that mock their
transport, with any live tests gated behind credentials so CI never needs them.

Run `sectum-ai adapters` to list the installed adapters and their capabilities.
