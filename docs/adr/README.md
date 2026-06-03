# Architecture Decision Records

This directory records significant architectural decisions for Sectum AI.

Each ADR is a numbered Markdown file (`NNNN-short-title.md`) with the sections
**Status**, **Context**, **Decision**, and **Consequences**. Once accepted, an
ADR is immutable — supersede it with a new ADR rather than editing it.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-monorepo-packaging-layout.md) | Monorepo packaging layout | Accepted |
| [0002](0002-evidence-layer-oss-boundary.md) | The evidence layer is fully open source | Accepted |
| [0003](0003-deterministic-substrate.md) | Substrate artifacts are pure functions of the seed | Accepted |
| [0004](0004-detection-pipeline-placement.md) | Probe architecture: detection placement and the plan signature | Accepted |
| [0005](0005-examples-named-by-attack-class.md) | Examples are named for the attack class, not a metric value | Accepted |
| [0006](0006-principal-isolation-model.md) | The isolation boundary is a principal (tenant or user) | Accepted |
| [0007](0007-canonical-hashing-serializes-every-field.md) | Canonical hashing serializes every field | Accepted |
| [0008](0008-adapter-user-dimension.md) | The adapter SDK carries an optional user dimension | Accepted |
| [0009](0009-atlas-technique-review-process.md) | ATLAS technique IDs are validated against the live MITRE catalog before each release | Accepted |
| [0016](0016-anchor-the-whole-pack.md) | Anchor the whole evidence pack, not just the run | Accepted |
| [0017](0017-pdf-engine.md) | weasyprint is an optional audit-pack engine; reportlab stays the default | Accepted |
| [0018](0018-embedding-provider-sweep.md) | Real embedding providers are opt-in extras; a deterministic hashing model is the default | Accepted |
| [0019](0019-job-runner-abstraction.md) | A `JobRunner` interface with local runners; a distributed backend stays swappable | Accepted |
| [0020](0020-structured-logging.md) | Structured logging with redaction, to stderr, DEBUG off by default | Accepted |
| [0021](0021-canonical-float-determinism.md) | Canonical hashing relies on deterministic float repr, not rounding | Accepted |
| [0022](0022-marker-substrate-depth.md) | Substrate depth: model-scoped embedding refs, multi-field planting, realistic secret shapes + format detector | Accepted |
