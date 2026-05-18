# ADR-0004 - Probe architecture: detection placement and the plan signature

## Status

Accepted (2026-05-17).

## Context

Phase 3 introduces the probes and the runner. Two facts collide:

- The CLI lives in the `sectum-ai` (core) distribution (ADR-0001) and must run
  probes from `sectum-ai-probes`.
- A probe's `detect()` applies the leak-detection pipeline, which the engineering
  spec (sections 5 and 12) places in the substrate layer - that is, in `core`.

If detection stays in `core`, then `core` depends on `sectum-ai-probes` (the CLI
runs probes) and `sectum-ai-probes` depends on `core` (probes use detection): a
dependency cycle between two published packages.

Separately, the spec's `Probe.plan(scenario)` signature (section 7.0) gives a
probe only the `Scenario`. Manifest-grounded probes - Class 1 enumerates canary
document IDs from the ground-truth manifest - need the seeded `Substrate`.

## Decision

- **The leak-detection pipeline moves into `sectum-ai-probes`**
  (`sectum.probes.detection`). It depends only on `sectum.spec` data models,
  never on the substrate generators, so `sectum-ai-probes` becomes
  self-contained (it depends on `sectum-ai-spec` only). The package dependency
  graph is then acyclic: `core` depends on `spec`, `adapters`, `probes`, and
  `evidence`; each of `probes`, `adapters`, and `evidence` depends only on
  `spec`.
- **`Probe.plan` takes the full `Substrate`** - `plan(self, substrate: Substrate)`
  rather than `plan(self, scenario)`. `Substrate` carries `scenario`, so nothing
  is lost.

## Consequences

- This deviates from engineering-spec sections 5 and 12, which draw the
  detectors inside the substrate layer; recorded here per section 1.2. The
  detection pipeline is genuinely "what a probe does with the substrate," not
  substrate provisioning, so co-locating it with the probes is the cleaner
  design and the only one that is acyclic, keeps five packages, and keeps the
  CLI in core.
- `DetectionPipeline`, the embedding and judge providers, and
  `confirmed_findings` are imported from `sectum.probes`, not `sectum.substrate`.
- The CLI in `core` can depend on `sectum-ai-probes` with no cycle.
