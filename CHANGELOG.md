# Changelog

All notable changes to Sectum AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A live AutoGen agent adapter (`packages/adapters/src/sectum/adapters/agent/autogen.py`):
  an `AutoGenAgent` that drives an AutoGen `AssistantAgent` + `UserProxyAgent`
  pair through `UserProxyAgent.initiate_chat`, prefixing every user message
  with a `[tenant:<hex>]` token so a tenant-aware tool reads the scope from
  its call arguments — the per-tenant isolation property Class 7 (agent
  tool-call hijack) verifies. The adapter walks the conversation's
  `chat_history` (with a `chat_messages` fallback for the v0.4+ shape) and
  surfaces every tool the assistant called during a run — including both the
  modern OpenAI `tool_calls` array and the legacy single `function_call`
  field — so the Class 7 probes can see *which* tool fired in each tenant's
  session. The `autogen` package is imported only on the live `connect`
  path, so the mock-backed contract test in `tests/unit/test_autogen_agent.py`
  runs against an in-memory stand-in with no extra dependency; the live path
  needs the optional extras group (`pip install sectum-ai-adapters[autogen]`)
  and is exercised by `tests/integration/test_autogen.py` (opt-in via the
  env-gated integration suite). The CLI resolver accepts `kind: autogen`
  under `agent` (via a `factory: module.path:callable` returning
  `(assistant, user_proxy)`); `docs/configuration.md` and
  `sectum.yaml.example` are updated to match.

## [0.1.0] - 2026-05-26

First public release. Sectum AI ships as a five-package `uv` workspace
(`sectum-ai`, `sectum-ai-spec`, `sectum-ai-probes`, `sectum-ai-adapters`,
`sectum-ai-evidence`), Apache-2.0 licensed, with a tamper-evident evidence
chain anyone can verify with `sectum verify` and no Sectum-side trust.
What landed in 0.1.0 is the work that closed the phase-0 through phase-5
build plan; the rest of this section is the per-feature log.

### Added

- A live LangGraph agent adapter (`packages/adapters/src/sectum/adapters/agent/langgraph.py`):
  a `LangGraphAgent` that drives a compiled LangGraph `StateGraph` with one
  `thread_id` per tenant (`config={"configurable": {"thread_id": tenant.hex}}`)
  so per-thread checkpoint or memory cannot bleed across tenants — the
  isolation property Class 7 (agent tool-call hijack) verifies. The adapter
  surfaces every tool the graph called during a run (not just the final
  state) so the Class 7 probes can see *which* tool fired and with what
  arguments. The `langgraph` package is imported only on the live `connect`
  path, so the mock-backed contract test in `tests/unit/test_langgraph_agent.py`
  runs against an in-memory stand-in with no extra dependency; the live path
  needs the optional extras group (`pip install sectum-ai-adapters[langgraph]`)
  and is exercised by `tests/integration/test_langgraph.py`
  (opt-in via the env-gated integration suite). The CLI resolver accepts
  `kind: langgraph` under `agent`; `docs/configuration.md` and
  `sectum.yaml.example` are updated to match.
- Live OpenAI and Anthropic providers for the Class 2 detection pipeline
  (`packages/probes/src/sectum/probes/providers.py`): `OpenAIEmbedder`
  (default `text-embedding-3-small`), `OpenAIJudge` (default `gpt-4o-mini`
  via JSON-mode structured output), and `AnthropicJudge` (default
  `claude-3-5-sonnet` via tool-use structured output). The judge prompt
  enforces the spec §6.4 guardrail — only the candidate entity descriptor
  is shown, never the ground-truth manifest verbatim. No
  `AnthropicEmbedder` ships because Anthropic does not expose an
  embeddings API as of 2026; the gap is documented inline in
  `providers.py`. The CLI resolver now accepts `kind: openai` and
  `kind: anthropic` under `embedder` / `judge` config blocks; mock-backed
  unit tests cover construction, retry, and structured-output parsing,
  and a pair of live-gated integration tests run against the real APIs
  when `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` are set.
- A second flavour of the Erasure Attestation sample in `docs/samples/`: the
  RESIDUAL DATA pack produced by `sectum erasure --soft-delete` against the
  `examples/erasure-attestation` substrate. Three new files
  (`erasure-attestation-residual-data-audit-pack.pdf`,
  `erasure-attestation-residual-data-evidence.json`,
  `erasure-attestation-residual-data-attestation.intoto.json`) sit next to the
  existing happy-path ERASED pack so a prospective DPO can see both the
  successful-erasure deliverable and the failure-mode artefact the pack is
  built to catch — without running anything locally. The samples README now
  describes both verdict flavours, lists the regeneration commands for both,
  and explains that either pack verifies under `sectum verify`; the verdict
  is data, not signal integrity.
- `examples/erasure-attestation/sectum.yaml.production`: a documented
  production-shape config for the engagement, with `evidence.timestamper:
  local` and `evidence.rekor: true` defaults and a comment explaining why
  real engagements should pin a customer-chosen TSA URL (FreeTSA, the OSS
  demo default, has been observed to be unreachable for hours at a time).
  Used by the sample regeneration in `docs/samples/README.md`.
- `sectum probe --output json` emits a single machine-parseable JSON object on
  stdout (the run id, the probe count, the confirmed-finding count, the
  Retrieval-Pivot Rate, the per-probe counts, and a `run_path` pointer) so CI
  pipelines and dashboards can act on the headline metrics without scraping
  the human-readable rendering. `--output text` is the unchanged default.
- The signed release pipeline (`.github/workflows/release.yml`): a `v*` tag
  push builds the five workspace distributions, generates a CycloneDX SBOM per
  distribution, signs every sdist, wheel, and SBOM with Sigstore (keyless,
  OIDC), publishes to PyPI via Trusted Publisher (OIDC), and creates a GitHub
  Release with the matching CHANGELOG section as its body and the SBOMs and
  `.sigstore` bundles as assets. A `pypi` environment fronts the publish step
  so the maintainer's approval is the final human gate; no static PyPI token
  lives in the repository. `scripts/check_release_version.py` blocks a release
  whose tag and `pyproject.toml` versions drift, and
  `scripts/extract_changelog.py` lifts the matching CHANGELOG section (with an
  `Unreleased` fallback for pre-release tags). `scripts/generate_package_sboms.sh`
  emits one SBOM per distribution. `docs/RELEASING.md` is the operator's
  reference (the PyPI Trusted Publisher setup, the per-release checklist, how
  to verify an artifact with `cosign verify-blob`, and the yank procedure);
  `SECURITY.md` and `CONTRIBUTING.md` cross-link the trust model.
- The live HTTP MCP client adapter (`HttpMCPClient`): a generic Model Context
  Protocol client over the SDK's streamable-HTTP transport, so a hosted MCP
  integration is reachable without a stdio subprocess. Like `StdioMCPClient`,
  a generic call carries no tenant identity unless a `tenant_argument` is
  configured; the adapter faithfully transmits tenant context under that key
  so the Class 7 confused-deputy probes can find a server that drops it. The
  CLI resolver now accepts `mcp.kind: http` with `url`, `headers`, `timeout`,
  and `tenant_argument`; verified offline against an in-memory FastMCP server
  and exercised live by `tests/integration/test_mcp_http.py` (opt-in via
  `SECTUM_MCP_HTTP_URL`).
- Phase 0 — repository foundation: a `uv` workspace with five packages
  (`sectum-ai`, `sectum-ai-spec`, `sectum-ai-probes`, `sectum-ai-adapters`,
  `sectum-ai-evidence`).
- Foundation documents: `LICENSE` (Apache-2.0), `SECURITY.md`, `README.md`,
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`.
- Continuous integration: lint (ruff), type-check (mypy), test (pytest),
  secret scan (gitleaks), and CodeQL workflows; pre-commit hooks; Dependabot;
  issue and pull-request templates.
- Architecture decision records: ADR-0001 (monorepo packaging layout) and
  ADR-0002 (the evidence layer is fully open source).
- Phase 1 - the marker substrate: `sectum-ai-spec` Pydantic models and JSON
  Schema export; the substrate (deterministic synthetic tenants, templated
  corpus generation, three canary marker types, hashed ground-truth manifest);
  and the exact/semantic/judge detection pipeline with deterministic fake
  embedding and judge providers.
- ADR-0003 (substrate artifacts are pure functions of the seed).
- Phase 2 - the adapter SDK and probe interface: six adapter family interfaces
  with a capability model and registry; the `Probe` protocol and registry;
  deterministic in-memory fake adapters for every family with a contract test
  suite; the `sectum adapters` CLI command; and live pgvector and Chroma
  vector-store adapters verified against docker-compose backends.
- Phase 3 - the attack catalog: the scenario runner; the Class 1
  direct-tenant-boundary probe; the Class 2 flagship organic-entity-bleed RAG
  probe, whose substrate plants every canary in a shared-entity pivot document
  so benign cross-tenant queries reproduce the Retrieval Pivot, with the
  Retrieval-Pivot Rate metric; the Class 4 semantic-cache-contamination probe;
  and the Class 11 GDPR Article 17 erasure-verification wedge.
- Phase 3 - the evidence chain: tamper-evident evidence packs
  (`build_evidence_pack`) and independent verification (`verify_pack`), with a
  pluggable timestamper; the compliance-control mappings (SOC 2, ISO 27001,
  GDPR, EU AI Act, HIPAA, NIST AI RMF, OWASP); and the audit-pack PDF renderer
  (`render_audit_pack`).
- Phase 3 - the CLI: `sectum seed` provisions the substrate, `sectum probe`
  runs the probe suite (recording findings and the Retrieval-Pivot Rate),
  `sectum report` assembles the evidence pack (JSON and PDF), `sectum verify`
  independently verifies it, `sectum erasure` runs the GDPR Article 17
  erasure-verification workflow into an attestation pack, and `sectum init`
  scaffolds a starter `sectum.yaml` config.
- Phase 3 - end-to-end examples: `examples/retrieval-pivot` (the flagship
  Class 2 walkthrough, from seeding through a verified evidence pack) and
  `examples/erasure-attestation` (the Class 11 erasure-verification wedge).
- Phase 4 - the model/adapter layer and the agent surface: a
  `ModelAdapter` adapter family with a deterministic `FakeModel`; the Class 9
  LoRA / adapter cross-tenant-influence probe; and the Class 7 cross-tenant
  agent tool-call hijacking probe (the MCP confused-deputy and token-passthrough
  sub-probes) over an extended `FakeMCP`. Both probes join the `sectum probe`
  suite.
- Phase 4 - the threat model: `docs/threat-model.md` records the
  trust boundaries, the assets (the ground-truth manifest, evidence packs), the
  deployment modes, and Sectum AI's explicit non-goals.
- Phase 4 - a mkdocs-material documentation site: a page per
  implemented attack class, plus the evidence chain, compliance mappings, the
  adapters, the ADRs, and the threat model, with a build-and-deploy workflow.
- Phase 4 - the `sectum probe --probe` filter to run a single
  probe, and the `examples/mcp-tenant-boundary` Class 7 walkthrough.
- Phase 5 - the regression-baseline engine: `sectum baseline`
  saves a run's headline metrics, and `--compare` flags any later run whose
  metrics regressed (more confirmed findings, or a higher Retrieval-Pivot Rate).
- Phase 5 - Class 8, the persistent memory contamination probe,
  over a new `MemoryAdapter` adapter family with a deterministic `FakeMemory`.
- Phase 5 - Class 6, the embedding-inversion probe: a
  partial-fragment query reconstructs a foreign entity canary from a shared
  index.
- Phase 5 - Class 10, the IKEA-style implicit benign extraction
  probe: a multi-turn sequence of benign queries that extracts foreign content.
- Phase 5 - Class 3, the adversarial RAG poisoning probe: a
  planted lure document pivots a tenant's canary into others' retrieval; the
  runner gains a `vector.upsert` action.
- Phase 5 - Class 5, the KV-cache timing side-channel probe: a
  statistical timing test (a Cohen's d effect size over many trials) that
  detects a shared KV prefix cache; the model adapter gains a `measure_latency`
  method, and the run metrics record per-pair side-channel effect sizes.
- Phase 5 - the live Redis cache adapter (`RedisCache`): a key-prefixed,
  tenant-scoped cache over a Redis server, verified against a docker-compose
  backend; it joins pgvector and Chroma as the third live adapter.
- Phase 5 - the live Weaviate vector-store adapter (`WeaviateVectorStore`):
  each tenant maps to its own Weaviate collection, created with self-provided
  vectors and deterministic object ids so an upsert stays idempotent; verified
  against a docker-compose backend.
- Phase 5 - the live HTTP RAG adapter (`HttpRAGPipeline`): a generic connector
  that answers a tenant's query over a JSON HTTP API, so a retrieval pipeline
  is reachable without a backend-specific SDK; standard-library only.
- Phase 5 - the live Phoenix observability adapter (`PhoenixObservability`):
  searches a tenant's traces for a marker over an Arize Phoenix server, with
  each tenant mapped to its own Phoenix project; verified against a
  docker-compose backend.
- Phase 5 - the live HTTP agent adapter (`HttpAgent`): a generic connector
  that runs a tenant's task over a JSON HTTP API and surfaces the agent's tool
  calls, so an agent framework is reachable without a framework-specific SDK;
  standard-library only.
- Phase 5 - the live MCP client adapter (`StdioMCPClient`): a generic Model
  Context Protocol client that launches a stdio MCP server, lists its tools,
  and invokes them; a generic MCP call carries no tenant identity unless a
  tenant-scoping argument is configured.
- The typed `SectumError` exception hierarchy (`ConfigError`, `AdapterError`,
  `EvidenceError`, `DetectionError`) in `sectum-ai-spec` (the engineering spec,
  section 16); the adapter, runner, and substrate error conditions now raise
  the typed errors instead of a bare `ValueError`.
- The CLI maps typed `SectumError`s to the engineering-spec section-10 exit
  codes: an `EvidenceError` exits 4, and other typed errors exit 3, replacing
  the traceback that used to surface from a `seed`, `probe`, `erasure`, or
  `report` invocation.
- A typed `sectum.yaml` configuration loader in `sectum.config`: pydantic
  models for the scenario, adapter, and evidence blocks, and a `load_config`
  function that raises `ConfigError` on a missing file, malformed YAML, or an
  invalid schema. `sectum seed` accepts `--config sectum.yaml` and reads its
  scenario seed and workdir from the file; explicit `--seed`/`--workdir` flags
  override the config.
- A config-driven adapter resolver in `sectum.config`: `build_adapters`
  dispatches each adapter family's `kind` to a concrete `Adapter`, defaulting
  missing families to plain fakes. `sectum probe` accepts `--config` and
  builds its adapter bundle from the file, so a tenant-isolated config (every
  leak knob off) records zero confirmed findings while the default leaky-demo
  config keeps reproducing them. The `sectum init` template now exposes every
  adapter family's leak knobs so the demo round-trips through the resolver.
- The CLI resolver now wires the live adapters: `kind: pgvector`, `chroma`,
  or `weaviate` for `adapters.vector_store`; `kind: redis` for `adapters.cache`;
  and `kind: stdio` for `adapters.mcp`. Secrets reference environment variables
  (`dsn_env: SECTUM_PGVECTOR_DSN`); vector adapters receive a deterministic
  hashing-trick embedder so a sectum-driven verification needs no
  embedding-model account.
- `sectum erasure`, `sectum report`, and `sectum baseline` accept
  `--config sectum.yaml` and use its workdir as a default, completing the
  per-command `--config` coverage for every workflow command.
- A `docs/configuration.md` reference page in the mkdocs nav: the `sectum.yaml`
  top-level shape, every adapter family's supported `kind`s with their fields
  and defaults, the env-var secret pattern, and a live-pgvector example.
- Extend the scenario runner with `rag.ask`, `observability.search`, and
  `agent.run` actions and pair them with new `rag`, `observability`, and
  `agent` fields on `AdapterBundle`; the CLI's `sectum probe` passes the
  three new adapters into the runner. Probes can now drive a RAG pipeline,
  search observability traces, or run an agent task directly through the
  runner; the config resolver wires the three new families to their fakes.
- The CLI resolver wires the live HTTP RAG, Phoenix observability, and HTTP
  agent adapters: `kind: http` in `adapters.rag` or `adapters.agent` selects
  `HttpRAGPipeline`/`HttpAgent`; `kind: phoenix` in `adapters.observability`
  selects `PhoenixObservability`. New `_float` and `_str_dict` helpers parse
  timeouts and header maps from the config.
- `sectum probe` accepts `--max-concurrency N` (default 1) to run probes in
  parallel via a thread pool. N > 1 requires both thread-safe adapters and
  that probe-order interactions don't matter; the demo's in-memory fakes
  share state across mutating and reading probes, so concurrent execution
  there yields nondeterministic findings (the exit code is still stable).
- Class 11 (`sectum erasure`) now checks the observability surface. The
  `ObservabilityAdapter` interface gains `delete(tenant)`; `FakeObservability`
  gets a `soft_delete` knob mirroring `FakeVectorStore`; `PhoenixObservability`
  removes the tenant's project on delete. `ErasureProbe` accepts an optional
  `observability` adapter and scans the tracing surface for residual markers,
  and `sectum erasure` seeds traces and passes a `FakeObservability` through
  so the workflow round-trips through both the vector and tracing surfaces.
- Class 11 (`sectum erasure`) now also checks the agent/long-term memory surface
  (a third of the spec's "ten hiding places"). The `MemoryAdapter` interface
  gains `delete(tenant)`; `FakeMemory` gets a `soft_delete` knob; `ErasureProbe`
  accepts an optional `memory` adapter and scans it (via `recall`) for residual
  markers, and `sectum erasure` seeds memory and passes a `FakeMemory` through
  so the workflow round-trips the vector, tracing, and memory surfaces.
- Class 11 (`sectum erasure`) now also checks the semantic/application cache
  surface. The `CacheAdapter` interface gains `delete(tenant)` and `values(tenant)`
  (the values a tenant can read - the tenant's own when scoped, all of them when
  not, which is itself the leak); `FakeCache` gets a `soft_delete` knob and
  `RedisCache` deletes/scans the tenant's prefixed keys. `ErasureProbe` accepts
  an optional `cache` adapter and scans its values for residual markers, and
  `sectum erasure` seeds the cache through, so the workflow now round-trips the
  vector, tracing, memory, and cache surfaces. An unscoped cache that cannot
  isolate a tenant's entries is itself an erasure failure.
- Class 11 (`sectum erasure`) now also checks the model / fine-tune-adapter
  surface. The `ModelAdapter` interface gains `delete(tenant)`; `FakeModel` gets
  a `soft_delete` knob; `ErasureProbe` accepts an optional `model` adapter and
  scans it by querying the model with the canary - a memorized canary surfaces
  only while the tenant's adapter exists - and `sectum erasure` trains and
  threads a `FakeModel` through, so the workflow now round-trips the vector,
  tracing, memory, cache, and model surfaces (five of the "ten hiding places").
- Class 11 (`sectum erasure`) now also checks the derived full-text search-index
  surface (the tenth "hiding place"). A new `SearchIndexAdapter` family
  (`search` + `delete`, capability `TEXT_SEARCH`) and its `FakeSearchIndex` (with
  a `soft_delete` knob) model a keyword index built from the corpus, distinct
  from the embedding vector store; `ErasureProbe` accepts an optional
  `search_index` adapter and scans it for residual markers, and `sectum erasure`
  indexes and threads a `FakeSearchIndex` through. The workflow now round-trips
  six of the "ten hiding places". There is no live search-index adapter yet, so
  the fake carries the behavior.
- Class 11 (`sectum erasure`) now also checks the evaluation / golden-set surface
  (the fourth "hiding place" - test fixtures and eval datasets that may copy
  tenant content). A new `EvalSetAdapter` family (`search` + `delete`, reusing
  the `TEXT_SEARCH` capability) and its `FakeEvalSet` (with a `soft_delete` knob)
  model an eval set; `ErasureProbe` accepts an optional `eval_set` adapter and
  scans it for residual markers, and `sectum erasure` seeds and threads a
  `FakeEvalSet` through. The workflow now round-trips seven of the "ten hiding
  places". There is no live eval-set adapter yet, so the fake carries the
  behavior.
- The live Pinecone vector-store adapter (`PineconeVectorStore`): each tenant
  maps to its own namespace within one index, so a query or fetch is
  tenant-scoped. Pinecone is a hosted service with no local backend, so it is
  verified by a mock-backed contract test plus an opt-in live test (the
  engineering spec, section 13); the CLI resolver wires `kind: pinecone` for
  `adapters.vector_store`.
- The live Langfuse observability adapter (`LangfuseObservability`): Langfuse's
  public SDK binds one project per key pair and cannot enumerate projects, so
  each tenant is scoped by trace `user_id` within a single project (unlike the
  per-project Phoenix adapter); a search matches the marker in the tenant's
  traces and erasure bulk-deletes them. Targets the Langfuse v3 SDK; verified by
  a mock-backed contract test plus an opt-in live test. The CLI resolver wires
  `kind: langfuse` for `adapters.observability`.
- The live LangSmith observability adapter (`LangSmithObservability`): each
  tenant maps to its own LangSmith tracing project (like Phoenix), so a search
  scans that project's runs and erasure deletes the project. Verified by a
  mock-backed contract test plus an opt-in live test; the CLI resolver wires
  `kind: langsmith` for `adapters.observability`.
- ADR-0004 (acyclic package graph; the detection pipeline moved into
  `sectum-ai-probes`).
- ADR-0005 (examples are named for the attack class, not a metric value).
- The principal isolation model: the spec gains `PrincipalKind`, a `Principal`
  value model (a tenant, or a user within a tenant), `SyntheticUserSpec`,
  `SyntheticTenantSpec.users`, `Marker.owner_user_id`, and
  `Substrate.principals()`. The substrate distributes a tenant's markers
  round-robin across its declared users; tenant-level behavior is unchanged (the
  new fields default to the tenant case). User-level detection and probing are a
  deferred phase.
- ADR-0006 (the isolation boundary is a principal - a tenant or a user within a
  tenant - generalizing the substrate without repositioning the tenant wedge).
- User-level (principal) leak detection (ADR-0006 update): the detection
  pipeline's predicate is now principal-aware - within a tenant, a marker owned
  by one user surfacing in another user's session is a leak (verified
  default-deny). `ProbeStep` gains `actor_user_id` and `Finding` gains
  `owner_user_id`/`observed_in_user_id` (optional, tenant-level default), and
  the flagship Class 2 probe (`rag-entity-bleed`) plans from every principal, so
  against a store that is not user-scoped a user's benign query surfaces another
  user's data. Tenant-level behavior is unchanged. Generalizing the remaining
  probes (and the user-aware adapters they need) and the intended-vs-actual
  access-policy model are the documented follow-ons.
- The Class 1 direct-tenant-boundary probe (`tenant-boundary-fetch`) is now
  principal-aware (ADR-0006): it plans a direct fetch of every hard-canary
  document from each principal to which the marker is foreign - cross-tenant as
  before, and cross-user within a tenant when users are declared - so negative
  authorization is verified at both granularities. The `is_cross_principal`
  predicate is now public so probe planning and detection share one definition
  of "foreign." With no users declared the plan is byte-identical to the prior
  per-tenant plan.
- The adapter SDK gains an optional user dimension (ADR-0008), starting with the
  vector family. `VectorStoreAdapter.query`/`fetch` take a keyword-only
  `user: UUID | None = None`; the runner threads `ProbeStep.actor_user_id` into
  them; and `CorpusDocument` gains `owner_user_id` (a pivot document inherits its
  marker's owner). `FakeVectorStore` gains a `user_scoped` knob and reports the
  new `USER_SCOPED` capability: scoped, it returns only a user's own documents
  plus the tenant-shared ones; unscoped, it ignores the user and surfaces another
  user's document. The Class 1 boundary probe now verifies user isolation end to
  end - a user-scoped store yields no cross-user leak, a tenant-only store does.
  `user=None` is the tenant-level scope and is unchanged; the live vector
  adapters accept `user` for conformance but do not yet report `USER_SCOPED`
  (per-backend user isolation is a follow-on).
- The user dimension reaches the cache family (ADR-0008). `CacheAdapter.get`/`set`
  take a keyword-only `user`; the runner threads it; and `FakeCache` gains a
  `user_scoped` knob that folds the user into the key (reporting `USER_SCOPED`),
  so one user never reads a sibling user's entry. The Class 4 semantic-cache
  probe (`semantic-cache-contamination`) is now principal-aware - it primes an
  entry as the owning principal and fetches it from every foreign principal - so
  it verifies cache-key tenancy at the user granularity too: a user-scoped cache
  yields no cross-user leak, a tenant-only cache serves one user another's
  answer. `user=None` is unchanged.
- The live `RedisCache` now *enforces* user scoping: with `user_scoped: true` it
  folds the user into the Redis key (and reports `USER_SCOPED`), so a sibling
  user cannot read another user's entry within the tenant; the tenant-level
  `values`/`delete` globs still capture the user-folded keys. The cache resolver
  exposes `user_scoped` for both the fake and Redis. Verified by an opt-in Redis
  integration test (the key folding is correct by construction). This is the
  exemplar for bringing the remaining live adapters (pgvector, Chroma, Weaviate,
  Pinecone) to per-backend `USER_SCOPED` enforcement.
- The live `PgVectorStore` now *enforces* user scoping: with `user_scoped: true`
  it records each document's `owner_user` (an idempotent `ADD COLUMN` migration)
  and filters `query`/`fetch` to the caller's own rows plus tenant-shared ones
  (reporting `USER_SCOPED`), so one user cannot retrieve a sibling user's
  document within the tenant. The tenant-level `delete`/`list_namespaces` are
  unchanged. The vector resolver exposes `user_scoped` for the fake and pgvector.
  Verified against a live PostgreSQL + pgvector backend by the integration tests.
- The live `ChromaVectorStore` now *enforces* user scoping: with
  `user_scoped: true` it records each document's owning user in Chroma metadata
  (an empty sentinel marks tenant-level documents) and filters `query`/`fetch`
  with a metadata `where` clause to the caller's own documents plus the
  tenant-shared ones (reporting `USER_SCOPED`). `user=None` is the tenant-level
  scope and is unchanged. The vector resolver exposes `user_scoped` for Chroma.
  Verified against a live ChromaDB backend by the integration tests.
- The live `WeaviateVectorStore` now *enforces* user scoping: with
  `user_scoped: true` it records each document's owning user in a FIELD-tokenized
  `owner_user` property and filters `query` (server-side) and `fetch`
  (post-lookup) to the caller's own documents plus tenant-shared ones (reporting
  `USER_SCOPED`). A non-empty sentinel marks tenant-level documents (Weaviate
  rejects an `equal("")` filter). `user=None` is the tenant-level scope and is
  unchanged. The vector resolver exposes `user_scoped` for Weaviate. Verified
  against a live Weaviate backend by the integration tests.
- The live `PineconeVectorStore` now *enforces* user scoping: with
  `user_scoped: true` it records each document's owning user in metadata (an
  empty sentinel marks tenant-level documents) and filters `query` (a Pinecone
  metadata filter) and `fetch` (post-lookup) to the caller's own documents plus
  tenant-shared ones (reporting `USER_SCOPED`). `user=None` is the tenant-level
  scope and is unchanged. `connect` and the vector resolver expose `user_scoped`.
  A non-empty `owner_user` sentinel marks tenant-level documents (avoiding the
  empty-string `$in` edge that bit Weaviate, since Pinecone is not live-verified
  here). Verified by the mock-backed contract tests - Pinecone's established
  level ("mock + opt-in live"). With this, **every live adapter** enforces user
  isolation and reports `USER_SCOPED`: Redis, pgvector, Chroma, and Weaviate each
  verified against a live backend, and Pinecone mock-verified (the live opt-in
  test runs when credentials are set). This completes the ADR-0008 live-adapter
  follow-on.
- Per-finding control mappings (the engineering spec, sections 9 and 18). Every
  probe now populates `atlas_techniques` (MITRE ATLAS) and `nist_rmf` (NIST AI
  RMF), and the detection pipeline stamps each `Finding` with the probe's
  `owasp_llm`/`atlas`/`nist`, so the evidence pack carries per-finding control
  IDs (it previously had only the run-level `controls.py` table). NIST is
  `MEASURE 2.7` (security/resilience measurement) across the catalog; ATLAS uses
  conservative, verified techniques - `AML.T0024` (Exfiltration via AI Inference
  API) for the exfiltration probes, `AML.T0024.001` (Invert AI Model) for
  embedding inversion, `AML.T0057` (LLM Data Leakage) for the data-leakage
  probes - and is intentionally empty where no clean ATLAS technique applies
  (KV-cache timing, erasure verification). A manual `pipeline.detect()` call is
  unchanged (the defaults are the multi-tenant OWASP class and no ATLAS/NIST).
  The per-class ATLAS assignments were then validated against the current MITRE
  ATLAS catalog: rag-poisoning also carries `AML.T0020` (Poison Training Data),
  agent-tool-hijack `AML.T0053` (LLM Plugin Compromise), and lora-cross-tenant
  `AML.T0024.000` (Infer Training Data Membership).
- The audit-pack PDF now renders each finding's mapped control IDs inline
  (`OWASP ...; ATLAS ...; NIST ...`), so an auditor reads per-finding control
  coverage from the findings table rather than only the run-level mapping
  section. Empty frameworks are omitted (an erasure finding shows no ATLAS, an
  unclassified finding shows no suffix). This surfaces the per-finding IDs the
  `Finding` model and `evidence.json` already carried.
- The audit-pack PDF now renders each finding's `remediation_pointer` (as an
  italic line beneath the finding) and a "Scope and methodology" section, so the
  pack covers the full spec section 8.3 layout. The methodology narrative states
  the detection method (synthetic-tenant substrate; exact/semantic/judge;
  manifest-grounded zero false positives) and the limits (Sectum does not
  remediate; the pack asserts test coverage, not legal certification).
- Parallelized the CI test run with `pytest-xdist` (`pytest -n auto`); the test
  step now clocks ~2x faster wall-clock (locally 282s -> 113s on the full
  suite) without weakening the gate. Coverage shards are combined automatically
  (`[tool.coverage.run] parallel = true`). The serial path still works, so a
  developer can run `pytest` without `-n auto` for clearer single-test output.
- The per-class attack-catalog docs (`docs/attack-catalog/class-*.md`) now show
  each probe's MITRE ATLAS and NIST AI RMF technique IDs in the header line, and
  the catalog overview (`index.md`) gains an ATLAS column - so the docs match the
  IDs the source code carries. Also fixes the Class 11 erasure page (and the
  index table) to list all seven configured erasure surfaces (vector DB,
  tracing, agent memory, semantic cache, model/fine-tune, search index, eval
  set) instead of the original five.
- A self-documenting `sectum.yaml.example` at the repo root: every block the
  config schema accepts (scenario, workdir, all eight adapter families with
  per-`kind` placeholders for the live backends, evidence chain, security/
  manifest-at-rest, detection providers and semantic threshold) with copy-and-
  edit annotations. Validated to load cleanly under `sectum.config.load_config`.
  The README quickstart now points at it.
- README now carries the spec section 20 storefront elements: an "Open Sectum
  vs Sectum Cloud" two-column comparison (both share the same evidence format,
  Cloud is hosted/managed) and a Support section linking to GitHub Sponsors
  and a commercial-support contact.
- The audit-pack PDF now renders each finding's `evidence_span` as a quoted
  italic line beneath the finding - the captured leak text from the detection
  pipeline (the engineering spec, section 6.4) IS the auditor's proof. Order
  per finding: summary (with controls), evidence (proof), remediation (action).
  Empty spans are guarded so a pipeline finding without a captured span renders
  nothing extra.
- ADR-0009 records the release-time ATLAS technique-review process:
  re-validate every probe's MITRE ATLAS IDs against the MISP-galaxy mirror of
  the catalog, restate fit, and update the per-probe source comment and
  per-class doc together. The May 2026 ad-hoc sweep that produced PR #8
  (adding T0020 / T0053 / T0024.000) becomes a per-release gate.
- `docs/samples/` now ships real outputs of the runnable examples - the
  retrieval-pivot audit-pack PDF (264 findings, all per-finding control IDs
  and remediation pointers rendered) and the GDPR Article 17 erasure
  attestation pack (per-surface ERASED/RESIDUAL DATA verdicts) - so a
  prospective auditor or DPO can see what they get without installing
  anything. Each pack ships its in-toto attestation envelope; `sectum verify
  docs/samples/erasure-attestation-evidence.json` demonstrates the
  tamper-evident chain end to end.
- `docs/glossary.md` mirrors the spec section 23 vocabulary - tenant, principal,
  marker types, ground-truth manifest, Retrieval-Pivot Rate, surface, probe,
  finding, evidence pack, BYOC, wedge - with cross-links into the attack
  catalog, evidence chain, compliance mappings, threat model, and sample
  packs. Standard buyer/auditor reference; wired into the mkdocs nav.
- The user dimension reaches the memory family (ADR-0008). `MemoryAdapter.remember`/
  `recall` take a keyword-only `user`; the runner threads it; and `FakeMemory`
  tags each entry with its writer and gains a `user_scoped` knob (reporting
  `USER_SCOPED`) so a recall returns only the caller's own and tenant-shared
  notes. The Class 8 memory-contamination probe (`memory-contamination`) is now
  principal-aware - it writes a note as the owning principal and recalls it from
  every foreign principal - so a user-scoped store yields no cross-user
  contamination while a tenant-only store surfaces a sibling user's note.
  `user=None` is the tenant-level scope and is unchanged.
- The remaining retrieval probes are now principal-aware (ADR-0006), riding on
  the user-aware vector adapter: Class 2 (`rag-entity-bleed`, the flagship),
  Class 3 (`rag-poisoning`), Class 6 (`embedding-inversion`), and Class 10
  (`ikea-extraction`) all plan from `substrate.principals()` and pass the
  observing user to detection, so a benign query - or a planted poison - that
  surfaces a sibling user's content is flagged. The runner stamps a planted
  document's `owner_user_id` with the acting principal so a user-scoped store
  filters it. End to end: against a store scoped by tenant alone these probes
  report a cross-user leak; against a user-scoped store they report none. With
  no users declared every plan is unchanged.
- The user dimension reaches the MCP family (ADR-0008). `MCPAdapter.invoke` takes
  a keyword-only `user`; the runner threads it; and `FakeMCP` records each
  resource's owning user and gains a `user_scoped` knob (reporting `USER_SCOPED`)
  so a `lookup` resolves only the caller's own resources within the tenant - a
  tenant-scoped server resolves a sibling user's resource (the leak). The Class 7
  agent-tool-hijack probe (`agent-tool-hijack`) is now principal-aware: it issues
  the confused-deputy and token-passthrough lookups from every foreign principal,
  so it catches cross-user tool-call hijacking as well as cross-tenant.
  `user=None` is unchanged; the live `StdioMCPClient` accepts `user` for
  conformance but does not yet report `USER_SCOPED`.
- The user dimension reaches the model family (ADR-0008), completing the
  generalization. `ModelAdapter.train_adapter`/`infer` take a keyword-only
  `user`; the runner threads it; and `FakeModel` tags each adapter text with its
  trainer and gains a `user_scoped` knob (reporting `USER_SCOPED`) so inference
  recalls only the caller user's own adapter within the tenant - a tenant-scoped
  model surfaces a sibling user's memorized canary (the cross-user bleed). The
  Class 9 lora-cross-tenant probe (`lora-cross-tenant`) is now principal-aware:
  it trains the adapter as the owning principal and infers from every foreign
  principal. `measure_latency` stays tenant-level (the KV-cache side channel is
  shared infrastructure, not a per-principal scope). `user=None` is unchanged.
- ADR-0007 (canonical hashing serializes every field; reject
  exclude_none/exclude_defaults to keep the evidence digest total and
  unambiguous).
- Hypothesis property tests for marker generation and canonical hashing,
  generalizing the fixed-seed reproducibility and uniqueness invariants to
  arbitrary seeds (the engineering spec, section 15).
- The Class 2 embedding-model sweep (`sectum.sweep.embedding_model_sweep`): runs
  the flagship organic-entity-bleed probe once per configured embedding model
  and records a per-model Retrieval-Pivot Rate
  (`RunMetrics.retrieval_pivot_rate_by_model`), reproducing the "stronger
  embeddings leak more" effect (the engineering spec, section 7). `FakeVectorStore`
  gains a `recall` knob that models embedding strength as how much cross-tenant
  content a query surfaces. The sweep is a fake-substrate illustration: `sectum
  probe` records the per-model rates only for in-memory-store runs whose scenario
  lists more than one embedding model (a live vector adapter records none).
- An end-to-end test suite (`tests/e2e/`) that runs each example walkthrough
  (retrieval-pivot, erasure-attestation, mcp-tenant-boundary) through the CLI to
  a verified evidence pack - the section-14 "reproduce the demo" acceptance,
  gated opt-in by `SECTUM_RUN_E2E` and run on a dedicated CI step. Plus unit
  tests closing the reported coverage gaps (the JSON Schema export, the probe
  registry, the runner's per-action adapter guards, the config-resolver
  helpers), raising line coverage from ~95% to ~97%.
- A real RFC 3161 trusted-timestamping path (`sectum.evidence.Rfc3161Timestamper`,
  `verify_rfc3161_token`): `sectum report --tsa <url>` (or `evidence.timestamper:
  rfc3161` in the config) submits the run digest to a Time-Stamp Authority and
  stores the returned token, and `sectum verify` checks that token against the
  recomputed digest. Trust is pinned independently of the pack: the verifier
  ships the public FreeTSA leaf and root built in, and `sectum verify
  --tsa-cert/--tsa-root` override them for a customer-pinned TSA. Backed by the
  `rfc3161-client` library behind a `sectum-ai-evidence[rfc3161]` extra (pinned
  `>=1.0.3` for CVE-2025-52556); a committed FreeTSA token fixture verifies
  offline in CI, and a live round-trip is opt-in via `SECTUM_RUN_LIVE_TSA`
  (the engineering spec, section 8.2).
- Configurable real embedding and judge providers for the detection pipeline
  (`sectum.probes.providers`): `OpenAIEmbeddingProvider` and an `OpenAIJudge` /
  `AnthropicJudge`, reached over their HTTP APIs (standard library only). A
  `detection` config block selects the embedder and judge (`fake` by default),
  their models, the API-key env var, and the `semantic_threshold`; the resolver
  builds a `DetectionProviders` bundle that `sectum probe` threads through every
  probe's detection. Detection stays provider-agnostic and deterministic-by-
  default; a real embedding model strengthens the Retrieval Pivot and a
  calibrated judge adjudicates candidates (the engineering spec, sections 6.4,
  13). The judge is asked a narrow structured question and never sees the
  ground-truth manifest. Verified with mocked HTTP plus opt-in live tests
  (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`).
- Release supply-chain integrity (the engineering spec, section 17): the release
  workflow now generates a CycloneDX SBOM of the locked third-party dependencies
  (`scripts/generate_sbom.sh`, from `uv export` through `cyclonedx-py`) and signs
  the built wheels, sdists, and the SBOM with Sigstore keyless signing (the
  workflow's OIDC identity, no stored key), uploading the `.sigstore.json`
  bundles. The SBOM script is reusable locally.
- A job-runner abstraction (`sectum.jobs`): a small `JobRunner` interface
  (`map(func, items) -> list`, results in input order) with two local
  implementations - `SerialJobRunner` and a bounded `ThreadJobRunner` -
  selected by `build_job_runner(max_concurrency)`. `sectum probe` now executes
  its suite through this interface instead of an inline thread pool, so
  `--max-concurrency` is unchanged while the orchestration layer becomes the
  documented seam where a distributed backend (Temporal, Prefect) can drop in
  later without touching call sites (the engineering spec, sections 13 and 21,
  the open job-runner decision).
- At-rest encryption of the seeded substrate (`sectum.crypto`): set
  `security.manifest_key_env` to the name of an environment variable holding a
  base64 32-byte key, and `sectum seed` seals the substrate - which holds the
  ground-truth manifest and the planted canary plaintexts - with AES-256-GCM
  before it touches disk (`substrate.json.enc`); `sectum probe`/`report`/
  `erasure` open it with the same key. A wrong key or any tampering fails
  authentication. The key is referenced from the environment, never inlined
  (the engineering spec, section 17). Backed by `cryptography` behind a
  `sectum-ai[encryption]` extra; the unencrypted path needs nothing extra.
- An in-toto attestation wrapping (`sectum.evidence.to_in_toto_statement`,
  `verify_in_toto_statement`): `sectum report` and `sectum erasure` also emit
  `attestation.intoto.json`, the evidence re-expressed as an in-toto Statement
  (v1) - subject = the run bound by its canonical digest, predicate = the
  verification result (scenario/manifest hashes, metrics, control mappings, and
  which integrity anchors are present). It is a derived, interoperable view of
  the pack and adds no new trust; standard-library only (the engineering spec,
  section 13).
- A Sigstore Rekor transparency-log anchor (`sectum.evidence.RekorTransparencyLog`,
  `verify_rekor_proof`): `sectum report --rekor` (or `evidence.rekor: true`)
  signs the run digest and records a `hashedrekord` entry in a public,
  append-only log, storing the inclusion proof in the pack; `sectum verify`
  recomputes the RFC 6962 Merkle root and checks the signed checkpoint that
  commits to it. As with the TSA, the checkpoint key is pinned independently of
  the pack: the public-good instance's log keys (ECDSA and Ed25519) are shipped
  built in and selected by log id, and `sectum verify --rekor-key <pem>` pins a
  private instance's key. Verification is fully offline (no network, no current
  tree head); a committed real inclusion-proof fixture verifies in CI, and a
  live round-trip is opt-in via `SECTUM_RUN_LIVE_REKOR`. Backed by `cryptography`
  behind a `sectum-ai-evidence[rekor]` extra (the engineering spec, section 8.2).

### Changed

- Trim the README and ADR-0006 to engineering content only: drop the
  commercial Open-vs-Cloud comparison, the competitive positioning, and the
  go-to-market/buyer rationale, so the repository documents the technical
  project only.

### Notes

- Delivery sequencing: the public Apache-2.0 repositories are completed before
  any private repository is started.
- The 85% coverage gate (the engineering spec, section 15) is active as of Phase 1; the
  workspace currently reports 95% line coverage.

[Unreleased]: https://github.com/sectum-ai/sectum-ai/commits/main
