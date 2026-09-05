# Adapters

An adapter connects the substrate and probes to a real system. Every adapter
declares its family and a set of named capabilities, so a probe can state which
capabilities it needs and an adapter reports its isolation posture honestly.

## Families

| Family | Purpose |
|---|---|
| Vector store | Upsert, query, fetch a document by id, and delete a tenant's documents. |
| App | The application's own resource API, probed through the vector-store contract (it fills the vector slot, so `sectum-ai adapters` lists its fake under `vector_store`). `kind: fake` only. |
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
stores are tenant-isolated — pgvector scopes rows of one table by a `tenant`
column; the others give each tenant its own collection or index — and
add a `fetch`-by-id primitive alongside similarity `query`; the Pinecone and Azure
AI Search stores give each tenant its own namespace/index on a hosted service and
are verified by an opt-in live test (no local backend); both index asynchronously,
so their `upsert` and `delete` wait (bounded) for the write to be visible before
returning — an early read produced a missing baseline, or a not-yet-purged vector
reported as an erasure failure. Qdrant (`kind: qdrant`,
`[qdrant]`) and OpenSearch (`kind: opensearch`, `[opensearch]`) are self-hosted, so
each ships a docker-compose service and a live integration test in CI. Milvus
(`kind: milvus`, `[milvus]`) is also self-hosted but heavier (it needs etcd and
minio), so its compose service is gated behind the `milvus` profile and its live
integration test runs locally (`docker compose --profile milvus up -d`) rather than
in CI. Azure AI Search uses `kind: azure-search`, `[azure-search]`.

On six of the eight stores (Weaviate, Pinecone, Qdrant, Milvus, OpenSearch, Azure AI
Search) the user filter on a **by-id `fetch`** is applied by the adapter after the
backend has already returned the document; only pgvector and Chroma filter that
lookup server-side. A user-level verdict on the Class 1 fetch primitive therefore
describes the adapter's filter, not the store's, on those six. Tenant scoping is
server-side on all eight, as is the user filter on `query`. The Chroma adapter never
recreates a deleted tenant's collection on a read. Both OpenSearch adapters verify
TLS certificates by default (`verify_certs: false` for a self-signed dev cluster).

**Cache.** The Redis cache prefixes its keys and tenant-scopes them by default;
`tenant_scoped=False` models the shared key space Class 4 is built to catch.

**Memory.** Two long-term / agent-memory backends. The Redis memory store
(`kind: redis`, the `[redis]` extra) keeps each tenant's entries in a prefixed
per-tenant list and recalls by keyword; it is tenant-scoped by default, so
`shared_memory=True` models the single shared memory space Class 8 (persistent memory
contamination) is built to catch, and `user_scoped=True` isolates users within a
tenant (ADR-0006). `soft_delete=True` acknowledges a delete but keeps the entries —
the Class 11 erasure residue. The mem0 store (`kind: mem0`, the `[mem0]` extra) maps
each tenant to a mem0 `user_id` and stores entries verbatim (`infer=False`), so a
product that keeps per-user memory in mem0 can be probed for the same Class 8 leak
(`shared_memory=True` collapses every tenant to one shared `user_id`; in that mode a
Class 11 erasure `delete` reports *attestable-with-caveat* rather than wiping every
tenant's shared memory); it does not model `user_scoped` (mem0's flat `user_id` space
has no per-user erasure boundary — use the Redis store for that). Its `recall` lists
the scope (`get_all`, with an explicit 10 000-entry limit that is refused when hit
rather than silently truncated — the SDK's own default is 100) and keyword-filters
it, rather than a ranked `search` window a planted marker could fall out of. Redis runs against a
docker-compose backend in CI; mem0 needs an embedder (its default is OpenAI), so it
is opt-in live.

**Search index.** The OpenSearch search index (`kind: opensearch`, the `[opensearch]`
extra) indexes each tenant's derived full-text documents into its own OpenSearch index
(`{prefix}-{tenant}`) and searches with a `match` query — the tenth "hiding place",
distinct from the vector store. Class 11 erasure seeds it, then confirms a `delete`
purges the index; `soft_delete=True` leaves it in place — the erasure residue. A
search whose matches exceed the page it returns is refused rather than truncated.

**Eval set.** The LangSmith eval set (`kind: langsmith`, the `[langsmith]` extra) maps
each tenant to its own LangSmith **Dataset** (`{prefix}-{tenant}`) — a dataset *is* a
curated golden eval set, the fourth "hiding place". A fixture is a dataset example,
Class 11 erasure seeds them, and `delete` removes the tenant's dataset;
`soft_delete=True` leaves the fixtures in place.

**Backup.** The S3 backup (`kind: s3`, the `[boto3]` extra) keeps each tenant's
snapshots under the key prefix `{prefix}/{tenant}/` in one bucket (AWS S3 or any
S3-compatible store — MinIO, Ceph — via `endpoint_url`), the seventh "hiding place". A
search lists that prefix and `delete` purges it; `no_erasure=True` models an immutable /
object-lock (WORM) bucket that exposes no per-tenant purge, so `delete` raises
`ErasureUnsupported` and Class 11 records the surface as **attestable-with-caveat** (data
presumed retained) — the same erasure-caveat contract as the read-only trace backends.
On a **versioned** bucket (Object Lock implies versioning) the adapter lists and
deletes every object *version*, not the current view: a plain delete there inserts a
delete marker and keeps the data, and `list_objects_v2` hides the key, so the scan
would otherwise read a retained snapshot as gone. A `delete_objects` call that leaves
any key in place (a version under a retention lock, a denied key) is an error, with a
pointer to `no_erasure: true`. The GCS backup (`kind: gcs`, the `[gcs]` extra) is the
Google-cloud parallel with the same per-tenant-prefix scoping and `no_erasure` /
`soft_delete` contract: with object versioning it lists and deletes every generation,
and a bucket whose **soft-delete policy** keeps deleted objects restorable (the default
for buckets created since 2024, seven days) reports attestable-with-caveat rather than
an erasure — the data is retained until it ages out. Point it at a local
fake-gcs-server via `STORAGE_EMULATOR_HOST` for testing.

**Observability — and the erasure caveat.** Six trace backends are wired, and
they split into two groups that matter for the Class 11 erasure wedge.
*Erasable* backends expose a real per-tenant delete: Phoenix and LangSmith each
map a tenant to its own project and delete it on erasure, while Langfuse (its v3
SDK binds one project per key pair) instead scopes each tenant by trace `user_id`
within a single project and bulk-deletes that tenant's traces — so a trace of the
tenant's recorded *without* that `user_id` (or under an end-user's id) is invisible
to both the scan and the delete, and tagging every trace is a precondition of the
verdict. Langfuse's scan reads the trace-level `name` / `input` / `output` /
`metadata`; observation-level prompts and completions are not scanned (the delete
cascades to them). Its listing is paged to exhaustion and refused past a 1000-trace
budget rather than truncated, and a delete that Langfuse has not applied within the
settle window is an error, not a clean return. *Read-only*
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

For the A3 data-subject erasure check, five of the six also expose a **by-id**
`fetch_trace` — Langfuse, LangSmith, Phoenix, Helicone, and Datadog each look a
trace up by id within the tenant's own scope, so `erasure --subject` can verify a
named trace is gone. LangSmith, Phoenix, Helicone, and Datadog each read one page
of at most 1000 traces, and Langfuse pages to its 1000-trace budget; a miss on a
full page (or past the budget) is refused (an `AdapterError`) rather than read as
"erased", since a trace beyond it is indistinguishable from a deleted one. A search response that is
an error envelope (a 200 carrying `error`/`errors`, or no `data` list) is likewise an
error, not an empty tenant; the generic OpenTelemetry reader treats a `DELETE` that
answers `404` as a purge only when its query then shows no spans — it asks with an
empty marker, which a conforming query endpoint answers with every span of the
tenant — and as "no delete API" (attestable-with-caveat) otherwise. The OpenTelemetry reader queries by
content, not id, so it has no by-id lookup and that surface reads `NOT_COVERED`.

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
cross-tenant tool-call hijack Class 7 examines. Two limits of that design: the
tenant travels *in band*, in the same text the probe controls, so the adapter
cannot tell "the framework dropped the scope" from "the model was talked out of
it" (LangGraph's `configurable` is the out-of-band exception); and the observation
is the agent's final message, so a foreign canary a tool returned but the model
did not echo is not seen. The agent contract also carries no user identity, so
this end verifies the tenant boundary only. The OpenAI Assistants run loop gives
up after `run_timeout_s` (default 300 s) instead of polling a parked run forever.

**Model.** The HuggingFace LoRA model fine-tunes a per-tenant PEFT adapter on a
base causal LM and routes inference to the caller's adapter; its `adapter_bleed`
knob merges every tenant's LoRA into every inference — the Class 9 weight-bleed
leak. `soft_delete=True` acknowledges an erasure and leaves the LoRA on disk *and
serving*, so the memorized text still surfaces — the residue Class 11 catches
(it used to re-route inference to the base model, which hid the retained weights
from that very scan). A hard `delete(tenant)` removes every scope under the
tenant, the per-user `<tenant>/<user>` LoRAs included. The vLLM model is
**serving-only**: it reaches a vLLM server over its
OpenAI-compatible API to run inference and measure time-to-first-token (the
Class 5 KV-prefix-cache timing channel), but it trains no per-tenant adapter, so
it reports the `shared_prefix_cache` capability and not `per_tenant_adapter` —
`sectum-ai probe` skips Class 9 for it, and a Class 11 erasure leaves the model
surface `NOT_COVERED`. The TGI model is the same serving-only shape over
HuggingFace Text Generation Inference's native text-generation API.

**MCP.** The MCP client speaks the Model Context Protocol over either a stdio
subprocess or a streamable HTTP session; a generic MCP call carries no tenant
identity, which is the confused-deputy gap Class 7 examines. Nor does it carry a
*user* identity unless `user_argument` names the tool argument to put it in.

**Which boundary a run can claim.** Every adapter declares whether a call made as a
user reaches the backend *as that user* (`carries_user`). The RAG, agent, and
observability contracts carry no user at all, and the live MCP clients carry one
only with `user_argument`; the runner drops user-level steps for an adapter that
does not carry the user, so the run claims the tenant boundary alone there. Run as
the tenant and judged as the user, such a step confirmed cross-user leaks of a
session that never existed. The built-in fakes all carry the user.

**Extras and verification.** The framework- and SDK-backed adapters are optional
extras, imported lazily so the base install stays light:
`pip install sectum-ai-adapters[<name>]` for `huggingface`, `vllm`, `tgi`,
`rag-langchain`, `langgraph`, `crewai`, `autogen`, `openai-assistants`,
`anthropic-tooluse`, `mcp` (both MCP clients), `langsmith` (the eval-set adapter),
`boto3` (the S3 backup), or `mem0` (the mem0 memory store).
The Helicone, Datadog, and OpenTelemetry readers and the HTTP RAG / agent
adapters use only the standard library; both MCP clients need the `mcp` extra. The pgvector, Chroma, Weaviate, Qdrant,
OpenSearch, Redis, and Phoenix adapters run against docker-compose backends in CI
(the **Integration** job); Milvus runs against its profile-gated compose service
locally. The hosted and SDK-backed adapters — including the LangSmith eval set and
the S3 backup — are exercised by tests that mock their transport, with any live tests
gated behind credentials or an endpoint (the S3 backup against a local MinIO) so CI
never needs them.

Run `sectum-ai adapters` to list the adapter families and the capabilities each
built-in fake reports; it does not enumerate installed live backends.
