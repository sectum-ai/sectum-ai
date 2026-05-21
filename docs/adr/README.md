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
