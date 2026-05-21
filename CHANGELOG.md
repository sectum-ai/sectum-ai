# Changelog

All notable changes to Sectum AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
- ADR-0004 (acyclic package graph; the detection pipeline moved into
  `sectum-ai-probes`).
- ADR-0005 (examples are named for the attack class, not a metric value).
- The principal isolation model (ADR-0006): the spec gains `PrincipalKind`, a
  `Principal` value model (a tenant, or a user within a tenant),
  `SyntheticUserSpec`, `SyntheticTenantSpec.users`, `Marker.owner_user_id`, and
  `Substrate.principals()`. The substrate distributes a tenant's markers across
  its declared users; tenant-level behavior is unchanged (the new fields default
  to the tenant case). User-level detection and probing are a deferred phase.
- ADR-0006 (the isolation boundary is a principal - a tenant or a user within a
  tenant - generalizing the substrate without repositioning the tenant wedge).

### Notes

- Delivery sequencing: the public Apache-2.0 repositories are completed before
  any private repository is started.
- The 85% coverage gate (the engineering spec, section 15) is active as of Phase 1; the
  workspace currently reports 95% line coverage.

[Unreleased]: https://github.com/sectum-ai/sectum-ai/commits/main
