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
- Phase 3 (in progress) - the attack catalog: the scenario runner; the Class 1
  direct-tenant-boundary probe; the Class 2 flagship organic-entity-bleed RAG
  probe with the Retrieval-Pivot Rate metric; the Class 4
  semantic-cache-contamination probe; and the Class 11 GDPR Article 17
  erasure-verification wedge.
- Phase 3 (in progress) - the evidence chain: tamper-evident evidence packs
  (`build_evidence_pack`) and independent verification (`verify_pack`), with a
  pluggable timestamper; the compliance-control mappings (SOC 2, ISO 27001,
  GDPR, EU AI Act, HIPAA, NIST AI RMF, OWASP); and the audit-pack PDF renderer
  (`render_audit_pack`).
- Phase 3 (in progress) - the CLI: `sectum seed` provisions the substrate and
  `sectum probe` runs the probe suite, recording the findings and the
  Retrieval-Pivot Rate.
- ADR-0004 (acyclic package graph; the detection pipeline moved into
  `sectum-ai-probes`).

### Notes

- Delivery sequencing: the public Apache-2.0 repositories are completed before
  any private repository is started.
- The 85% coverage gate (the engineering spec, section 15) is active as of Phase 1; the
  workspace currently reports 95% line coverage.

[Unreleased]: https://github.com/sectum-ai/sectum-ai/commits/main
