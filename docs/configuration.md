# Configuration

`sectum-ai init` scaffolds a `sectum-ai.yaml` configuration file; every CLI command
that runs a workflow (`seed`, `probe`, `report`, `erasure`, `baseline`,
`calibrate`) accepts `--config sectum-ai.yaml` to read its defaults from that
file. Explicit CLI flags — for example `--seed` or `--workdir` — always
override the values the config supplies.

## Top-level shape

A `sectum-ai.yaml` is a single YAML mapping with six top-level sections, all
optional. Any omitted section uses its built-in defaults.

```yaml
scenario:
  seed: 2026
  corpus_profile: demo
workdir: .sectum-ai
adapters:
  vector_store: ...
  cache: ...
  model: ...
  mcp: ...
  memory: ...
  rag: ...
  observability: ...
  agent: ...
evidence:
  timestamper: local
security:
  manifest_key_env: SECTUM_MANIFEST_KEY   # optional: seal the substrate at rest
detection:
  embedder: { kind: fake }
  judge: { kind: fake }
  semantic_threshold: 0.62                 # 0.62 | <float> | auto
  mode: hosted                             # hosted | local
```

Unknown top-level keys, unknown `evidence.timestamper` values, and malformed
YAML are rejected with a `ConfigError` and the CLI exits with code 3.

## `scenario`

Settings that drive substrate generation.

| Field | Type | Default | Notes |
|---|---|---|---|
| `seed` | int | `2026` | Drives every deterministic generator. |
| `corpus_profile` | str | `demo` | Accepted and validated but not yet applied — the demo corpus is generated regardless of this value. Reserved for profile-driven corpora. |
| `corpus_size` | int | `500` | Documents generated per tenant (the demo default, spec §6.2). Threaded through `sectum-ai seed`; lower it for a faster run. |
| `embedding_models` | list[str] | `["fake-deterministic"]` | Two or more entries trigger the Class 2 per-model Retrieval-Pivot Rate sweep. Each is `st:<model>` (sentence-transformers, opt-in `sectum-ai[sentence-transformers]`, local/BYOC-safe), `openai:<model>` (opt-in `sectum-ai[openai]`, key in `OPENAI_API_KEY`), `cohere:<model>` (opt-in `sectum-ai[cohere]`, key in `COHERE_API_KEY`), `voyage:<model>` (opt-in `sectum-ai[voyage]`, key in `VOYAGE_API_KEY`), `bedrock:<model>` (Amazon Bedrock Titan, opt-in `sectum-ai[bedrock]`, AWS creds + `AWS_REGION`), `hash-<dim>` (deterministic offline), or a legacy `fake-*` recall illustration. The hosted providers send the synthetic corpus to their API (not BYOC-safe). See the [Class 2 page](attack-catalog/class-02-rag-entity-bleed.md#embedding-model-sweep). |

## `workdir`

A filesystem path. The CLI writes the substrate, run record, evidence pack,
and audit pack here. Defaults to `.sectum-ai`.

## `adapters`

A mapping from adapter-family name to that family's configuration. Each entry
takes a `kind` plus any backend-specific fields. A family that is omitted
defaults to a plain (non-leaky) fake.

The resolver reads eight families — `vector_store`, `cache`, `model`, `mcp`,
`memory`, `rag`, `observability`, and `agent` — and `sectum-ai probe` drives all
of them through the runner. `sectum-ai erasure` additionally consumes the three
Class 11 erasure surfaces `search_index`, `eval_set`, and `backup` (documented
below). Any other family name parses successfully but is not consumed.

Two cross-cutting boolean knobs apply to every `fake` adapter (and the live ones
that support them), beyond the per-family fields the tables below highlight:
`user_scoped: bool = false` switches isolation from tenant-level to per-user
within a tenant (ADR-0006), and `soft_delete: bool = false` makes an erasure a
no-op that the surface still acknowledges — the Class 11 residue. The tables list
them on the rows where they are the load-bearing knob; both are accepted on the
fakes generally.

### `vector_store`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `shared_index: bool = false`, `soft_delete: bool = false` | In-memory store. `shared_index: true` makes one index serve every tenant — the Class 2 retrieval-pivot leak. |
| `pgvector` | `dsn_env: str` *(or `dsn: str`)* | PostgreSQL with the pgvector extension. Prefer the env-var form. |
| `chroma` | `host: str = "localhost"`, `port: int = 8000` | ChromaDB server. Each tenant maps to its own collection. |
| `weaviate` | `host: str = "localhost"`, `port: int = 8080`, `grpc_port: int = 50051` | Weaviate server. Each tenant maps to its own collection. |
| `pinecone` | `api_key_env: str` *(or `api_key: str`)*, `index: str`, `host: str` *(optional)* | Pinecone index. Each tenant maps to its own namespace; the index must exist with dimension 64. |
| `qdrant` | `host: str = "localhost"`, `port: int = 6333`, `grpc_port: int = 6334`, `api_key_env: str` *(or `api_key: str`, optional)*, `user_scoped: bool = false` | Qdrant server. Each tenant maps to its own collection; `user_scoped: true` adds a per-user payload filter. A local/self-hosted Qdrant usually needs no `api_key`. |
| `milvus` | `uri: str = "http://localhost:19530"`, `token_env: str` *(or `token: str`, optional)*, `user_scoped: bool = false` | Milvus server. Each tenant maps to its own collection (strong consistency); `user_scoped: true` adds a per-user filter expression. A local/self-hosted Milvus usually needs no `token`. Requires the `milvus` extra. |
| `opensearch` | `host: str = "localhost"`, `port: int = 9200`, `user: str` *(optional)*, `password_env: str` *(or `password: str`, optional)*, `use_ssl: bool = false`, `verify_certs: bool = false`, `user_scoped: bool = false` | OpenSearch cluster. Each tenant maps to its own `knn_vector` index (Lucene engine, cosine); `user_scoped: true` adds a k-NN pre-filter. A local cluster with the security plugin disabled needs no auth. Requires the `opensearch` extra. |
| `azure-search` | `endpoint: str` *(required)*, `api_key_env: str` *(or `api_key: str`)*, `user_scoped: bool = false` | Azure AI Search service. Each tenant maps to its own index (HNSW, cosine); `user_scoped: true` adds an OData filter. Hosted (no local backend); requires the `azure-search` extra. |

### `cache`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `tenant_scoped: bool = true` | In-memory cache. `tenant_scoped: false` reproduces the Class 4 shared-key-space leak. |
| `redis` | `host: str = "localhost"`, `port: int = 6379`, `tenant_scoped: bool = true`, `prefix: str = "sectum-ai"` | A Redis server. Keys are prefix-namespaced. |

### `model`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `adapter_bleed: bool = false`, `prefix_cache: bool = false` | In-memory model. `adapter_bleed` reproduces Class 9; `prefix_cache` reproduces Class 5. |
| `huggingface` | `base_model_id: str` *(required)*, `adapters_dir: str` *(required)*, `adapter_bleed: bool = false`, `user_scoped: bool = false`, `soft_delete: bool = false`, `lora_rank: int = 8`, `lora_alpha: int = 16`, `train_epochs: int = 1`, `device_map: str = "auto"` | `HuggingFaceLoraModel` — a HuggingFace causal LM with per-tenant PEFT LoRA adapters managed on disk. The `adapter_bleed` knob merges every tenant's LoRA into every inference (Class 9). Requires the optional `huggingface` extra: `pip install sectum-ai-adapters[huggingface]`. |
| `vllm` | `base_url: str` *(required)*, `model: str` *(required)*, `api_key` / `api_key_env` *(optional; defaults to a placeholder)*, `timeout: float = 30.0`, `max_tokens: int = 16` | `VLLMModel` — a **serving-only** vLLM server reached over its OpenAI-compatible API. It runs inference and measures time-to-first-token (Class 5 KV-cache timing) but trains no per-tenant adapter, so `sectum-ai probe` **skips Class 9** for it and the model surface of a Class 11 erasure reads `NOT_COVERED`. Requires the optional `vllm` extra: `pip install sectum-ai-adapters[vllm]`. |
| `tgi` | `base_url: str` *(required)*, `api_key` / `api_key_env` *(optional)*, `timeout: float = 30.0`, `max_tokens: int = 16` | `TGIModel` — a **serving-only** HuggingFace Text Generation Inference server, reached over its native text-generation API (TGI serves one model per endpoint, so there is no `model` field). Same Class-5-only / Class-9-skipped / Class-11-`NOT_COVERED` behavior as `vllm`. Requires the optional `tgi` extra: `pip install sectum-ai-adapters[tgi]`. |

### `mcp`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `confused_deputy: bool = false`, `token_passthrough: bool = false` | In-memory MCP server; both knobs reproduce the Class 7 flaws. |
| `stdio` | `command: str` *(required)*, `args: list[str] = []`, `tenant_argument: str \| null = null` | Launches an MCP server as a subprocess and speaks MCP over stdio. |
| `http` | `url: str` *(required)*, `headers: dict[str, str] \| null = null`, `timeout: float = 30.0`, `tenant_argument: str \| null = null` | `HttpMCPClient` — opens a streamable HTTP session against a remote MCP server. |

### `memory`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `shared_memory: bool = false`, `user_scoped: bool = false`, `soft_delete: bool = false` | In-memory store. `shared_memory: true` reproduces the Class 8 cross-tenant memory leak; `user_scoped: true` isolates users within a tenant (ADR-0006); `soft_delete: true` acknowledges a delete but keeps the entries (the Class 11 residue). |
| `redis` | `host: str = "localhost"`, `port: int = 6379`, `shared_memory: bool = false`, `user_scoped: bool = false`, `soft_delete: bool = false`, `prefix: str = "sectum-ai-mem"` | `RedisMemory` — each tenant's long-term agent-memory entries live in a prefixed per-tenant list, recalled by keyword. Same isolation knobs as the fake. Requires the `redis` extra. |
| `mem0` | `shared_memory: bool = false`, `soft_delete: bool = false`, `config: dict` *(optional; mem0's own llm/embedder/vector_store config)* | `Mem0Memory` — each tenant maps to a mem0 `user_id`; entries are stored verbatim (`infer=False`), so a planted marker is found by its own text. `shared_memory: true` collapses every tenant to one shared `user_id` (the Class 8 leak); in that mode a Class 11 `delete` raises `ErasureUnsupported` → *attestable-with-caveat* (no per-tenant erasure boundary — it would wipe every tenant), never a global wipe. **Does not support `user_scoped`** (mem0's flat `user_id` space has no per-user erasure boundary — the resolver rejects it; use `redis` for that). Requires the `mem0` extra. |

### `search_index`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `soft_delete: bool = false` | In-memory full-text index (the tenth "hiding place"). `soft_delete: true` acknowledges a delete but leaves the documents searchable — the Class 11 residue. |
| `opensearch` | `host: str = "localhost"`, `port: int = 9200`, `user: str` *(optional)*, `password_env: str` *(or `password: str`, optional)*, `use_ssl: bool = false`, `verify_certs: bool = false`, `prefix: str = "sectum-ai-search"`, `soft_delete: bool = false` | `OpenSearchSearchIndex` — each tenant's derived full-text documents live in their own index (`{prefix}-{tenant.hex}`), searched with a `match` query; `delete` drops the index (`soft_delete: true` leaves the residue). A local cluster with the security plugin disabled needs no auth. Requires the `opensearch` extra. |

### `eval_set`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `soft_delete: bool = false` | In-memory golden eval set (the fourth "hiding place"). `soft_delete: true` acknowledges a delete but keeps the fixtures — the Class 11 residue. |
| `langsmith` | `api_key_env: str` *(or `api_key: str`)*, `api_url: str` *(optional)*, `prefix: str = "sectum-ai-eval"`, `soft_delete: bool = false` | `LangSmithEvalSet` — each tenant maps to its own LangSmith **Dataset** (`{prefix}-{tenant.hex}`); a fixture is a dataset example, a search scans the dataset's examples, and `delete` removes the dataset (`soft_delete: true` leaves the fixtures — the residue). Requires the `langsmith` extra. |

### `backup`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `soft_delete: bool = false`, `no_erasure: bool = false` | In-memory backup / snapshot store (the seventh "hiding place"). `soft_delete: true` acknowledges a delete but keeps the snapshot (residue); `no_erasure: true` raises `ErasureUnsupported` so Class 11 records the surface as *attestable-with-caveat* (an immutable backup, presumed retained). |
| `s3` | `bucket: str` *(required)*, `endpoint_url: str` *(optional; set for MinIO/Ceph)*, `region_name: str` *(optional)*, `access_key_id_env: str` *(or `access_key_id: str`, optional)*, `secret_access_key_env: str` *(or `secret_access_key: str`, optional)*, `prefix: str = "sectum-ai-backup"`, `no_erasure: bool = false`, `soft_delete: bool = false` | `S3Backup` — each tenant's snapshots live under the key prefix `{prefix}/{tenant.hex}/` in one bucket; a search lists that prefix and `delete` purges it. `no_erasure: true` models an immutable / object-lock (WORM) bucket with no per-tenant purge (attestable-with-caveat). Credentials fall back to boto3's own chain (env / profile / instance role). Works against AWS S3 or any S3-compatible store. Requires the `boto3` extra. |

### `rag`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `shared_index: bool = false` | `FakeRAGPipeline`. `shared_index: true` makes one retriever serve every tenant — the Class 2 retrieval-pivot leak at the RAG-pipeline end (the `rag-pipeline-bleed` probe). |
| `http` | `url: str` *(required)*, `headers: dict[str, str] \| null = null`, `timeout: float = 30.0` | `HttpRAGPipeline` — POSTs `{tenant, query}` to the URL and parses `{answer, retrieved}`. |
| `langchain` | (constructed in Python) | `LangChainRAGPipeline` — wraps any LangChain `Runnable` (a composed LCEL chain) and invokes it with `{"tenant": str(tenant), "query": query}`; accepts a string answer, `{"answer", "retrieved"}`, or the legacy `{"result", "source_documents"}` shape. The `sectum-ai.yaml` block only flips the kind; the caller constructs the chain (typically via `LangChainRAGPipeline.connect(retriever, llm)`) and supplies it to the substrate runner. Requires the optional `rag-langchain` extra: `pip install sectum-ai-adapters[rag-langchain]`. |

### `observability`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `soft_delete: bool = false`, `no_erasure: bool = false` | `FakeObservability`. `soft_delete: true` models a backend that acknowledges erasure but leaves traces — the Class 11 residue (an erasure *failure*). `no_erasure: true` models a backend with no per-tenant erasure API (it raises `ErasureUnsupported`, like Helicone / Datadog) — Class 11 reports its surface as *attestable-with-caveat*, distinct from a failure. |
| `phoenix` | `base_url: str` *(required)*, `prefix: str = "sectum-ai"` | `PhoenixObservability` — each tenant maps to a Phoenix project named `{prefix}-{tenant.hex}`. `delete(tenant)` removes the tenant's project. |
| `langfuse` | `public_key_env: str` *(or `public_key: str`)*, `secret_key_env: str` *(or `secret_key: str`)*, `host: str` *(required)* | `LangfuseObservability` (Langfuse v3 SDK) — one project, each tenant scoped by trace `user_id`. `delete(tenant)` bulk-deletes the tenant's traces. |
| `langsmith` | `api_key_env: str` *(or `api_key: str`)*, `api_url: str` *(optional)*, `prefix: str = "sectum-ai"` | `LangSmithObservability` — each tenant maps to a LangSmith project named `{prefix}-{tenant.hex}`. `delete(tenant)` deletes the project. |
| `otel` | `base_url_env: str` *(or `base_url: str`)*, `query_path: str = "/v1/traces/query"`, `headers: dict[str, str] \| null = null`, `timeout: float = 30.0`, `tenant_attribute: str = "tenant.id"` | `OtelObservability` — a generic OpenTelemetry reader over any endpoint that speaks the Sectum OTLP-JSON trace-query contract (a thin shim in front of Jaeger / Tempo / Grafana / a vendor backend). Scopes by the resource attribute `tenant_attribute` (= `tenant.hex`) and re-scans every span's name + attributes for the marker, so a backend that ignores the tenant filter is itself caught. `delete(tenant)` issues a scoped `DELETE`: a `404` (spans already absent) is an idempotent erasure no-op, while a `405`/`501` (no programmatic delete API) raises `ErasureUnsupported` so Class 11 records the surface as *attestable-with-caveat* (never a false erasure PASS), like Helicone / Datadog. Standard-library HTTP only — no optional extra. |
| `helicone` | `api_key_env: str` *(or `api_key: str`)*, `base_url: str = "https://api.helicone.ai"`, `tenant_property: str = "tenant"` | `HeliconeObservability` — reads the tenant's logged requests via the Helicone request-query API, scoped by a custom property (`Helicone-Property-Tenant` = `tenant.hex`), and scans request/response bodies for the marker. **Read-only**: Helicone exposes no programmatic per-tenant erasure API, so `delete(tenant)` raises `ErasureUnsupported` and Class 11 records the surface as *attestable-with-caveat* (never a false erasure PASS). Standard-library HTTP — no optional extra. |
| `datadog` | `api_key_env: str` *(or `api_key: str`)*, `application_key_env: str` *(or `application_key: str`)*, `base_url: str = "https://api.datadoghq.com"`, `tenant_tag: str = "tenant"` | `DatadogObservability` — reads the tenant's spans via the Datadog spans-search API, scoped by a span tag (`@tenant:<hex>`), and scans span attributes for the marker. **Read-only**: Datadog governs deletion through retention policies, not a per-tenant span-delete API, so `delete(tenant)` raises `ErasureUnsupported` and Class 11 records the surface as *attestable-with-caveat*. Standard-library HTTP — no optional extra. |

### `agent`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `confused_deputy: bool = false`, `tool_call_passthrough: bool = false` | `FakeAgent`. Both knobs reproduce the Class 7 flaws — a tool that lost tenant scope (confused deputy) and a server that trusts a caller-supplied token (token passthrough). |
| `http` | `url: str` *(required)*, `headers: dict[str, str] \| null = null`, `timeout: float = 30.0` | `HttpAgent` — POSTs `{tenant, task}` to the URL and parses `{output, tool_calls}`. |
| `langgraph` | (constructed in Python) | `LangGraphAgent` — a compiled LangGraph `StateGraph` invoked with a per-tenant `thread_id`. The `sectum-ai.yaml` block only flips the kind; the caller constructs the graph (typically via `LangGraphAgent.connect(model, tools)`) and supplies it to the substrate runner. Requires the optional `langgraph` extra: `pip install sectum-ai-adapters[langgraph]`. |
| `autogen` | (constructed in Python) | `AutoGenAgent` — an AutoGen `AssistantAgent` + `UserProxyAgent` pair driven by `UserProxyAgent.initiate_chat`, with each per-tenant message prefixed by a `[tenant:<hex>]` token so a tenant-aware tool reads the scope from its arguments. The `sectum-ai.yaml` block only flips the kind; the caller constructs the pair (typically via `AutoGenAgent.connect(model, tools)`) and supplies it to the substrate runner. Requires the optional `autogen` extra: `pip install sectum-ai-adapters[autogen]`. |
| `crewai` | (constructed in Python) | `CrewAIAgent` — a CrewAI `Crew` of agents + tasks kicked off per tenant via `crew.kickoff(inputs={"tenant_id": tenant.hex, "task": task})`, so templated task descriptions interpolate the tenant id and tenant-aware tools read the scope from their call arguments. The `sectum-ai.yaml` block only flips the kind; the caller constructs the crew (typically via `CrewAIAgent.connect(agents, tasks)`) and supplies it to the substrate runner. Requires the optional `crewai` extra: `pip install sectum-ai-adapters[crewai]`. |
| `openai-assistants` | (constructed in Python) | `OpenAIAssistantsAgent` — an OpenAI Assistant with one `Thread` cached per tenant, posted via `OpenAI().beta.threads.messages.create` + `runs.create`; each user message is prefixed with `[tenant:<hex>]` so a tenant-aware tool reads the scope from its call arguments. The `sectum-ai.yaml` block only flips the kind; the caller constructs the client + assistant_id (typically via `OpenAIAssistantsAgent.connect(model, tools)`) and supplies them to the substrate runner. Requires the optional `openai-assistants` extra: `pip install sectum-ai-adapters[openai-assistants]`. |
| `anthropic-tooluse` | (constructed in Python) | `AnthropicToolUseAgent` — the Anthropic Messages API in native tool-use mode with one conversation history cached per tenant; each per-tenant user message is prefixed with `[tenant:<hex>]` and the tool-use loop runs to `stop_reason: end_turn` per turn, executing the python callable each registered tool spec carries on its `__sectum_callable__` sidecar. The `sectum-ai.yaml` block only flips the kind; the caller constructs the client (typically via `AnthropicToolUseAgent.connect(model, tools)`) and supplies it to the substrate runner. Requires the optional `anthropic-tooluse` extra: `pip install sectum-ai-adapters[anthropic-tooluse]`. |

## `evidence`

| Field | Type | Default | Notes |
|---|---|---|---|
| `timestamper` | `local` \| `rfc3161` | `local` | `local` records a wall-clock time with no external anchor. `rfc3161` submits the attested (whole-pack) digest to a Time-Stamp Authority (requires the `sectum-ai-evidence[rfc3161]` extra). |
| `tsa_url` | str | — | (`rfc3161` only) URL of the Time-Stamp Authority; defaults to FreeTSA when unset. `sectum-ai report --tsa <url>` overrides it. |
| `rekor` | bool | `false` | Also record the attested digest in a Sigstore Rekor transparency log (requires the `sectum-ai-evidence[rekor]` extra). `sectum-ai report --rekor` enables it for one run. |
| `rekor_url` | str | — | URL of the Sigstore Rekor instance; defaults to the public-good instance when unset. |

`sectum-ai verify` checks an RFC 3161 token against a root pinned independently of
the pack: it ships the public FreeTSA leaf and root built in, and
`--tsa-cert`/`--tsa-root` (PEM files) override them for a customer-pinned TSA.
Likewise it checks a Rekor inclusion proof against log keys pinned built in, and
`--rekor-key <pem>` pins a private instance's key. See the
[evidence chain](evidence-chain.md#trusted-timestamping-rfc-3161).

## `security`

| Field | Type | Default | Notes |
|---|---|---|---|
| `manifest_key_env` | str | — | Name of the environment variable holding a base64-encoded 32-byte AES-256 key. When set, `sectum-ai seed` seals the substrate (and its ground-truth manifest) at rest as `substrate.json.enc` (requires the `sectum-ai[encryption]` extra). |

The substrate holds the canary plaintexts, so sealing it at rest is recommended
for BYOC runs. Generate a key with
`python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
and export it under the configured name. The key is referenced from the
environment, never written into `sectum-ai.yaml`.

## `detection`

The detection pipeline's semantic step is provider-agnostic. The defaults are
deterministic offline fakes; configure real providers for production detection.

| Field | Type | Default | Notes |
|---|---|---|---|
| `embedder.kind` | `fake` \| `openai` | `fake` | `openai` embeds over the OpenAI API (or any OpenAI-compatible endpoint via `base_url`). |
| `embedder.model` | str | provider default | e.g. `text-embedding-3-small`, or `nomic-embed-text` for Ollama. |
| `embedder.api_key_env` | str | `OPENAI_API_KEY` | Env var holding the API key. Optional when `base_url` is a local endpoint. |
| `embedder.base_url` | str | OpenAI API | OpenAI-compatible base URL — point at a local **Ollama** (`http://localhost:11434/v1`), vLLM, or LM Studio to run the semantic step with no OpenAI account. |
| `judge.kind` | `fake` \| `openai` \| `anthropic` | `fake` | The LLM judge that adjudicates semantic candidates. |
| `judge.model` | str | provider default | e.g. `gpt-4o-mini`, `claude-3-5-haiku-latest`, or `qwen2.5` for Ollama. |
| `judge.api_key_env` | str | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Env var holding the API key. Optional when `base_url` is a local endpoint. |
| `judge.base_url` | str | provider API | OpenAI-/Anthropic-compatible base URL; `kind: openai` + a local Ollama runs the judge with no account. |
| `semantic_threshold` | float \| `auto` | `0.62` | The similarity gate before the judge. A number is used verbatim. `auto` resolves to the calibrated per-model preset for the embedder above (see below), falling back to `0.62` with a logged warning for an unknown model. Raise it (or use `auto`) once a real embedding model is configured — a stronger model surfaces more (the engineering spec, section 7). |
| `mode` | `hosted` \| `local` | `hosted` | `local` is the BYOC "no data leaves the box" guarantee: the config **fails fast** if any embedder or judge would call a default hosted AI API. Only `fake` providers, or providers with a `base_url` pointed at an operator-controlled local/in-VPC endpoint, are allowed. `hosted` (the default) places no egress restriction. |

Real providers reach their HTTP APIs with the standard library only; the API key
is read from the environment, never inlined. A local OpenAI-compatible server —
**Ollama** (`http://localhost:11434/v1`), vLLM, or LM Studio — is a fully offline,
BYOC-safe option: set `base_url` and the key becomes optional (these endpoints
ignore it), so the semantic embedder + judge run with no external account.

Set `detection.mode: local` to **enforce** that offline posture. Detection is the
only stage that embeds or judges tenant content, so in `local` mode Sectum
fails fast on any embedder or judge that would reach a default hosted API
(`openai`/`anthropic` without a `base_url`) — guaranteeing it makes no call to a
third-party AI service. A `base_url` you set is trusted to point at an endpoint
inside your own boundary; that target is your trust boundary, not Sectum's (see
the [threat model](threat-model.md)).

### Calibrating the semantic threshold

The semantic threshold is **per embedding model**: a stronger model packs
unrelated text closer together, so a gate tuned for the offline fake floods the
judge with candidates on a real model (on one real run `text-embedding-3-small`
needed ≈ 0.80, not the 0.62 default). `sectum-ai calibrate` derives a principled
value instead of hand-picking one:

```sh
sectum-ai calibrate --embedder openai:text-embedding-3-small
```

It builds a labeled set from a seeded substrate — **positives** are a foreign
tenant's entity genuinely surfaced into another tenant's session, **negatives**
are same-tenant and unrelated text that must not trip the gate — scores each with
the chosen embedder, and recommends the threshold that **maximises F1 subject to
zero false positives** among the negatives (the zero-false-positive property is
non-negotiable; a threshold that admits any negative is never recommended). It
prints a precision/recall/F1 table and the value to paste into
`detection.semantic_threshold`. Flags: `--embedder <kind:model>` (default: the
configured `detection.embedder`; `st:…`, `openai:…`, `hash-…`, or `fake`),
`--seed`, `--workdir`, `--config`, and `--output {text,json}`. The run is
deterministic from the seed.

`semantic_threshold: auto` skips the per-run calibration and uses a built-in
preset for the configured embedder model. The shipped presets:

| Embedder model | Preset |
|---|---|
| `st:all-MiniLM-L6-v2` | 0.55 |
| `st:all-mpnet-base-v2` | 0.60 |
| `openai:text-embedding-3-small` | 0.80 |
| `openai:text-embedding-3-large` | 0.78 |
| (any other / fake) | 0.62 (the conservative default) |

## Secrets and environment variables

Credentials never appear inline in `sectum-ai.yaml` (the engineering spec,
section 17: *adapters never embed credentials*). Adapter blocks reference an
environment variable by name; the resolver reads its value at run time:

```yaml
adapters:
  vector_store:
    kind: pgvector
    dsn_env: SECTUM_PGVECTOR_DSN
```

```sh
export SECTUM_PGVECTOR_DSN=postgresql://user:pass@host/db
sectum-ai probe --config sectum-ai.yaml
```

A missing or empty environment variable produces a `ConfigError`
(`environment variable 'SECTUM_PGVECTOR_DSN' is unset or empty`) and the CLI
exits with code 3. An empty inline value (`dsn: ""`) or an empty env-var name
(`dsn_env: ""`) is rejected the same way at adapter-build time.

## Example: switching to live pgvector

```yaml
scenario:
  seed: 2026
workdir: .sectum-ai
adapters:
  vector_store:
    kind: pgvector
    dsn_env: SECTUM_PGVECTOR_DSN
  cache:
    kind: redis
    host: localhost
    port: 6379
  # model, mcp, memory default to plain fakes
```

```sh
export SECTUM_PGVECTOR_DSN=postgresql://...
docker compose up -d pgvector redis
sectum-ai seed --config sectum-ai.yaml
sectum-ai probe --config sectum-ai.yaml
```

## Schema reference

The schema is implemented as pydantic models in `sectum_ai.config` —
`SectumConfig`, `ScenarioConfig`, `AdapterConfig`, `EvidenceConfig` — and the
adapter resolver is `sectum_ai.config.build_adapters`. `AdapterConfig` accepts
extra fields (the backend-specific `host`, `port`, `dsn_env`, leak knobs);
the per-family `build_*` functions read and *type-check* the keys they consume.
Because `AdapterConfig` is `extra="allow"`, an unrecognised or misspelled key —
for example a mistyped leak knob like `confusedeputy` — is accepted and silently
ignored (the knob stays at its non-leaky default), not rejected; double-check
adapter field names against the tables above.
