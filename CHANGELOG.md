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
- Phase 5 (in progress) - the regression-baseline engine: `sectum baseline`
  saves a run's headline metrics, and `--compare` flags any later run whose
  metrics regressed (more confirmed findings, or a higher Retrieval-Pivot Rate).
- Phase 5 (in progress) - Class 8, the persistent memory contamination probe,
  over a new `MemoryAdapter` adapter family with a deterministic `FakeMemory`.
- Phase 5 (in progress) - Class 6, the embedding-inversion probe: a
  partial-fragment query reconstructs a foreign entity canary from a shared
  index.
- Phase 5 (in progress) - Class 10, the IKEA-style implicit benign extraction
  probe: a multi-turn sequence of benign queries that extracts foreign content.
- Phase 5 (in progress) - Class 3, the adversarial RAG poisoning probe: a
  planted lure document pivots a tenant's canary into others' retrieval; the
  runner gains a `vector.upsert` action.
- Phase 5 (in progress) - Class 5, the KV-cache timing side-channel probe: a
  statistical timing test (a Cohen's d effect size over many trials) that
  detects a shared KV prefix cache; the model adapter gains a `measure_latency`
  method, and the run metrics record per-pair side-channel effect sizes.
- ADR-0004 (acyclic package graph; the detection pipeline moved into
  `sectum-ai-probes`).
- ADR-0005 (examples are named for the attack class, not a metric value).

### Notes

- Delivery sequencing: the public Apache-2.0 repositories are completed before
  any private repository is started.
- The 85% coverage gate (the engineering spec, section 15) is active as of Phase 1; the
  workspace currently reports 95% line coverage.

[Unreleased]: https://github.com/sectum-ai/sectum-ai/commits/main
