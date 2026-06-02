# Configuration

`sectum init` scaffolds a `sectum.yaml` configuration file; every CLI command
that runs a workflow (`seed`, `probe`, `report`, `erasure`, `baseline`) accepts
`--config sectum.yaml` to read its defaults from that
file. Explicit CLI flags — for example `--seed` or `--workdir` — always
override the values the config supplies.

## Top-level shape

A `sectum.yaml` is a single YAML mapping with four top-level sections, all
optional. Any omitted section uses its built-in defaults.

```yaml
scenario:
  seed: 2026
  corpus_profile: demo
workdir: .sectum
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
```

Unknown top-level keys, unknown `evidence.timestamper` values, and malformed
YAML are rejected with a `ConfigError` and the CLI exits with code 3.

## `scenario`

Settings that drive substrate generation.

| Field | Type | Default | Notes |
|---|---|---|---|
| `seed` | int | `2026` | Drives every deterministic generator. |
| `corpus_profile` | str | `demo` | Accepted and validated but not yet applied — the demo corpus is generated regardless of this value. Reserved for profile-driven corpora. |
| `corpus_size` | int | `24` | Documents generated per tenant. Threaded through `sectum seed`. |
| `embedding_models` | list[str] | `["fake-deterministic"]` | Two or more entries trigger the Class 2 per-model Retrieval-Pivot Rate sweep. Each is `st:<model>` (sentence-transformers, opt-in `sectum-ai[sentence-transformers]`, local/BYOC-safe), `openai:<model>` (opt-in `sectum-ai[openai]`, key in `OPENAI_API_KEY`), `hash-<dim>` (deterministic offline), or a legacy `fake-*` recall illustration. See the [Class 2 page](attack-catalog/class-02-rag-entity-bleed.md#embedding-model-sweep). |

## `workdir`

A filesystem path. The CLI writes the substrate, run record, evidence pack,
and audit pack here. Defaults to `.sectum`.

## `adapters`

A mapping from adapter-family name to that family's configuration. Each entry
takes a `kind` plus any backend-specific fields. A family that is omitted
defaults to a plain (non-leaky) fake.

The resolver reads eight families — `vector_store`, `cache`, `model`, `mcp`,
`memory`, `rag`, `observability`, and `agent` — and `sectum probe` drives all
of them through the runner. Other family names parse successfully but are not
consumed by the CLI.

### `vector_store`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `shared_index: bool = false`, `soft_delete: bool = false` | In-memory store. `shared_index: true` makes one index serve every tenant — the Class 2 retrieval-pivot leak. |
| `pgvector` | `dsn_env: str` *(or `dsn: str`)* | PostgreSQL with the pgvector extension. Prefer the env-var form. |
| `chroma` | `host: str = "localhost"`, `port: int = 8000` | ChromaDB server. Each tenant maps to its own collection. |
| `weaviate` | `host: str = "localhost"`, `port: int = 8080`, `grpc_port: int = 50051` | Weaviate server. Each tenant maps to its own collection. |
| `pinecone` | `api_key_env: str` *(or `api_key: str`)*, `index: str`, `host: str` *(optional)* | Pinecone index. Each tenant maps to its own namespace; the index must exist with dimension 64. |

### `cache`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `tenant_scoped: bool = true` | In-memory cache. `tenant_scoped: false` reproduces the Class 4 shared-key-space leak. |
| `redis` | `host: str = "localhost"`, `port: int = 6379`, `tenant_scoped: bool = true`, `prefix: str = "sectum"` | A Redis server. Keys are prefix-namespaced. |

### `model`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `adapter_bleed: bool = false`, `prefix_cache: bool = false` | In-memory model. `adapter_bleed` reproduces Class 9; `prefix_cache` reproduces Class 5. |
| `huggingface` | `base_model_id: str` *(required)*, `adapters_dir: str` *(required)*, `adapter_bleed: bool = false`, `user_scoped: bool = false`, `soft_delete: bool = false`, `lora_rank: int = 8`, `lora_alpha: int = 16`, `train_epochs: int = 1`, `device_map: str = "auto"` | `HuggingFaceLoraModel` — a HuggingFace causal LM with per-tenant PEFT LoRA adapters managed on disk. The `adapter_bleed` knob merges every tenant's LoRA into every inference (Class 9). Requires the optional `huggingface` extra: `pip install sectum-ai-adapters[huggingface]`. |

### `mcp`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `confused_deputy: bool = false`, `token_passthrough: bool = false` | In-memory MCP server; both knobs reproduce the Class 7 flaws. |
| `stdio` | `command: str` *(required)*, `args: list[str] = []`, `tenant_argument: str \| null = null` | Launches an MCP server as a subprocess and speaks MCP over stdio. |
| `http` | `url: str` *(required)*, `headers: dict[str, str] \| null = null`, `timeout: float = 30.0`, `tenant_argument: str \| null = null` | `HttpMCPClient` — opens a streamable HTTP session against a remote MCP server. |

### `memory`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `shared_memory: bool = false` | In-memory store. `shared_memory: true` reproduces the Class 8 cross-tenant memory leak. |

No live memory adapter is wired into the CLI resolver yet.

### `rag`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | — | `FakeRAGPipeline`; needs no fields. |
| `http` | `url: str` *(required)*, `headers: dict[str, str] \| null = null`, `timeout: float = 30.0` | `HttpRAGPipeline` — POSTs `{tenant, query}` to the URL and parses `{answer, retrieved}`. |
| `langchain` | (constructed in Python) | `LangChainRAGPipeline` — wraps any LangChain `Runnable` (a composed LCEL chain) and invokes it with `{"tenant": str(tenant), "query": query}`; accepts a string answer, `{"answer", "retrieved"}`, or the legacy `{"result", "source_documents"}` shape. The `sectum.yaml` block only flips the kind; the caller constructs the chain (typically via `LangChainRAGPipeline.connect(retriever, llm)`) and supplies it to the substrate runner. Requires the optional `rag-langchain` extra: `pip install sectum-ai-adapters[rag-langchain]`. |

### `observability`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | `soft_delete: bool = false`, `no_erasure: bool = false` | `FakeObservability`. `soft_delete: true` models a backend that acknowledges erasure but leaves traces — the Class 11 residue (an erasure *failure*). `no_erasure: true` models a backend with no per-tenant erasure API (it raises `ErasureUnsupported`, like Helicone / Datadog) — Class 11 reports its surface as *attestable-with-caveat*, distinct from a failure. |
| `phoenix` | `base_url: str` *(required)*, `prefix: str = "sectum"` | `PhoenixObservability` — each tenant maps to a Phoenix project named `{prefix}-{tenant.hex}`. `delete(tenant)` removes the tenant's project. |
| `langfuse` | `public_key_env: str` *(or `public_key: str`)*, `secret_key_env: str` *(or `secret_key: str`)*, `host: str` *(required)* | `LangfuseObservability` (Langfuse v3 SDK) — one project, each tenant scoped by trace `user_id`. `delete(tenant)` bulk-deletes the tenant's traces. |
| `langsmith` | `api_key_env: str` *(or `api_key: str`)*, `api_url: str` *(optional)*, `prefix: str = "sectum"` | `LangSmithObservability` — each tenant maps to a LangSmith project named `{prefix}-{tenant.hex}`. `delete(tenant)` deletes the project. |
| `otel` | `base_url_env: str` *(or `base_url: str`)*, `query_path: str = "/v1/traces/query"`, `headers: dict[str, str] \| null = null`, `timeout: float = 30.0`, `tenant_attribute: str = "tenant.id"` | `OtelObservability` — a generic OpenTelemetry reader over any endpoint that speaks the Sectum OTLP-JSON trace-query contract (a thin shim in front of Jaeger / Tempo / Grafana / a vendor backend). Scopes by the resource attribute `tenant_attribute` (= `tenant.hex`) and re-scans every span's name + attributes for the marker, so a backend that ignores the tenant filter is itself caught. `delete(tenant)` issues a scoped `DELETE`: a `404` (spans already absent) is an idempotent erasure no-op, while a `405`/`501` (no programmatic delete API) raises `ErasureUnsupported` so Class 11 records the surface as *attestable-with-caveat* (never a false erasure PASS), like Helicone / Datadog. Standard-library HTTP only — no optional extra. |
| `helicone` | `api_key_env: str` *(or `api_key: str`)*, `base_url: str = "https://api.helicone.ai"`, `tenant_property: str = "tenant"` | `HeliconeObservability` — reads the tenant's logged requests via the Helicone request-query API, scoped by a custom property (`Helicone-Property-Tenant` = `tenant.hex`), and scans request/response bodies for the marker. **Read-only**: Helicone exposes no programmatic per-tenant erasure API, so `delete(tenant)` raises `ErasureUnsupported` and Class 11 records the surface as *attestable-with-caveat* (never a false erasure PASS). Standard-library HTTP — no optional extra. |
| `datadog` | `api_key_env: str` *(or `api_key: str`)*, `application_key_env: str` *(or `application_key: str`)*, `base_url: str = "https://api.datadoghq.com"`, `tenant_tag: str = "tenant"` | `DatadogObservability` — reads the tenant's spans via the Datadog spans-search API, scoped by a span tag (`@tenant:<hex>`), and scans span attributes for the marker. **Read-only**: Datadog governs deletion through retention policies, not a per-tenant span-delete API, so `delete(tenant)` raises `ErasureUnsupported` and Class 11 records the surface as *attestable-with-caveat*. Standard-library HTTP — no optional extra. |

### `agent`

| `kind` | Fields | Notes |
|---|---|---|
| `fake` | — | `FakeAgent`; needs no fields. |
| `http` | `url: str` *(required)*, `headers: dict[str, str] \| null = null`, `timeout: float = 30.0` | `HttpAgent` — POSTs `{tenant, task}` to the URL and parses `{output, tool_calls}`. |
| `langgraph` | (constructed in Python) | `LangGraphAgent` — a compiled LangGraph `StateGraph` invoked with a per-tenant `thread_id`. The `sectum.yaml` block only flips the kind; the caller constructs the graph (typically via `LangGraphAgent.connect(model, tools)`) and supplies it to the substrate runner. Requires the optional `langgraph` extra: `pip install sectum-ai-adapters[langgraph]`. |
| `autogen` | (constructed in Python) | `AutoGenAgent` — an AutoGen `AssistantAgent` + `UserProxyAgent` pair driven by `UserProxyAgent.initiate_chat`, with each per-tenant message prefixed by a `[tenant:<hex>]` token so a tenant-aware tool reads the scope from its arguments. The `sectum.yaml` block only flips the kind; the caller constructs the pair (typically via `AutoGenAgent.connect(model, tools)`) and supplies it to the substrate runner. Requires the optional `autogen` extra: `pip install sectum-ai-adapters[autogen]`. |
| `crewai` | (constructed in Python) | `CrewAIAgent` — a CrewAI `Crew` of agents + tasks kicked off per tenant via `crew.kickoff(inputs={"tenant_id": tenant.hex, "task": task})`, so templated task descriptions interpolate the tenant id and tenant-aware tools read the scope from their call arguments. The `sectum.yaml` block only flips the kind; the caller constructs the crew (typically via `CrewAIAgent.connect(agents, tasks)`) and supplies it to the substrate runner. Requires the optional `crewai` extra: `pip install sectum-ai-adapters[crewai]`. |
| `openai-assistants` | (constructed in Python) | `OpenAIAssistantsAgent` — an OpenAI Assistant with one `Thread` cached per tenant, posted via `OpenAI().beta.threads.messages.create` + `runs.create`; each user message is prefixed with `[tenant:<hex>]` so a tenant-aware tool reads the scope from its call arguments. The `sectum.yaml` block only flips the kind; the caller constructs the client + assistant_id (typically via `OpenAIAssistantsAgent.connect(model, tools)`) and supplies them to the substrate runner. Requires the optional `openai-assistants` extra: `pip install sectum-ai-adapters[openai-assistants]`. |
| `anthropic-tooluse` | (constructed in Python) | `AnthropicToolUseAgent` — the Anthropic Messages API in native tool-use mode with one conversation history cached per tenant; each per-tenant user message is prefixed with `[tenant:<hex>]` and the tool-use loop runs to `stop_reason: end_turn` per turn, executing the python callable each registered tool spec carries on its `__sectum_callable__` sidecar. The `sectum.yaml` block only flips the kind; the caller constructs the client (typically via `AnthropicToolUseAgent.connect(model, tools)`) and supplies it to the substrate runner. Requires the optional `anthropic-tooluse` extra: `pip install sectum-ai-adapters[anthropic-tooluse]`. |

## `evidence`

| Field | Type | Default | Notes |
|---|---|---|---|
| `timestamper` | `local` \| `rfc3161` | `local` | `local` records a wall-clock time with no external anchor. `rfc3161` submits the run digest to a Time-Stamp Authority (requires the `sectum-ai-evidence[rfc3161]` extra). |
| `tsa_url` | str | — | (`rfc3161` only) URL of the Time-Stamp Authority; defaults to FreeTSA when unset. `sectum report --tsa <url>` overrides it. |
| `rekor` | bool | `false` | Also record the run digest in a Sigstore Rekor transparency log (requires the `sectum-ai-evidence[rekor]` extra). `sectum report --rekor` enables it for one run. |
| `rekor_url` | str | — | URL of the Sigstore Rekor instance; defaults to the public-good instance when unset. |

`sectum verify` checks an RFC 3161 token against a root pinned independently of
the pack: it ships the public FreeTSA leaf and root built in, and
`--tsa-cert`/`--tsa-root` (PEM files) override them for a customer-pinned TSA.
Likewise it checks a Rekor inclusion proof against log keys pinned built in, and
`--rekor-key <pem>` pins a private instance's key. See the
[evidence chain](evidence-chain.md#trusted-timestamping-rfc-3161).

## `security`

| Field | Type | Default | Notes |
|---|---|---|---|
| `manifest_key_env` | str | — | Name of the environment variable holding a base64-encoded 32-byte AES-256 key. When set, `sectum seed` seals the substrate (and its ground-truth manifest) at rest as `substrate.json.enc` (requires the `sectum-ai[encryption]` extra). |

The substrate holds the canary plaintexts, so sealing it at rest is recommended
for BYOC runs. Generate a key with
`python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
and export it under the configured name. The key is referenced from the
environment, never written into `sectum.yaml`.

## `detection`

The detection pipeline's semantic step is provider-agnostic. The defaults are
deterministic offline fakes; configure real providers for production detection.

| Field | Type | Default | Notes |
|---|---|---|---|
| `embedder.kind` | `fake` \| `openai` | `fake` | `openai` embeds over the OpenAI API. |
| `embedder.model` | str | provider default | e.g. `text-embedding-3-small`. |
| `embedder.api_key_env` | str | `OPENAI_API_KEY` | Env var holding the API key. |
| `judge.kind` | `fake` \| `openai` \| `anthropic` | `fake` | The LLM judge that adjudicates semantic candidates. |
| `judge.model` | str | provider default | e.g. `gpt-4o-mini`, `claude-3-5-haiku-latest`. |
| `judge.api_key_env` | str | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Env var holding the API key. |
| `semantic_threshold` | float | `0.62` | The similarity gate before the judge; raise it once a real embedding model is configured (a stronger model surfaces more — the engineering spec, section 7). |

Real providers reach their HTTP APIs with the standard library only; the API key
is read from the environment, never inlined.

## Secrets and environment variables

Credentials never appear inline in `sectum.yaml` (the engineering spec,
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
sectum probe --config sectum.yaml
```

A missing or empty environment variable produces a `ConfigError`
(`environment variable 'SECTUM_PGVECTOR_DSN' is unset or empty`) and the CLI
exits with code 3. An empty inline value (`dsn: ""`) or an empty env-var name
(`dsn_env: ""`) is rejected the same way at adapter-build time.

## Example: switching to live pgvector

```yaml
scenario:
  seed: 2026
workdir: .sectum
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
sectum seed --config sectum.yaml
sectum probe --config sectum.yaml
```

## Schema reference

The schema is implemented as pydantic models in `sectum.config` —
`SectumConfig`, `ScenarioConfig`, `AdapterConfig`, `EvidenceConfig` — and the
adapter resolver is `sectum.config.build_adapters`. `AdapterConfig` accepts
extra fields (the backend-specific `host`, `port`, `dsn_env`, leak knobs);
the per-family `build_*` functions validate them.
