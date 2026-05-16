# ADR-0001 - Monorepo packaging layout: five distributions, native namespace packages

## Status

Accepted (2026-05-16).

## Context

CLAUDE.md section 3 mandates that Sectum ships as five PyPI distributions that
share a single `sectum` import namespace. Section 12 sketches a package tree that
includes a separate `packages/cli/` directory and an `__init__.py` directly under
`core`'s `src/sectum/`.

Two parts of that sketch had to be resolved before the workspace could be
scaffolded:

1. A PyPI distribution is built from exactly one `pyproject.toml`. A separate
   `packages/cli/` would therefore be either a sixth distribution (contradicting
   "five PyPI packages") or an unpublished member folded into the `sectum-ai`
   distribution by build-time tricks that reach across directories.
2. Multiple distributions cannot each ship an `__init__.py` for the same
   top-level `sectum` package without colliding on install.

## Decision

- **Five package directories, five PyPI distributions:** `sectum-ai`
  (core + CLI), `sectum-ai-spec`, `sectum-ai-probes`, `sectum-ai-adapters`,
  `sectum-ai-evidence`.
- **The CLI is part of `core`.** It lives at `sectum/cli/` inside the
  `packages/core` source tree, and `core`'s `pyproject.toml` declares the console
  script `sectum = "sectum.cli.app:app"`. There is no `packages/cli/`.
- **PEP 420 native namespace packages.** No package ships
  `src/sectum/__init__.py`. Each distribution owns a distinct subtree under the
  shared `sectum` namespace.
- **Build backend: `hatchling`,** configured per package with
  `[tool.hatch.build.targets.wheel]` `only-include = ["src/sectum"]` and
  `sources = ["src"]`.
- **`uv` virtual workspace root.** The root `pyproject.toml` has a
  `[tool.uv.workspace]` table and shared tooling config but no `[project]` table;
  it is not itself published.

## Consequences

- This deviates from the file tree drawn in CLAUDE.md section 12 (no `cli/`
  directory; no top-level `sectum/__init__.py`). This ADR records that deviation
  per CLAUDE.md section 1.2.
- `import sectum` resolves to an empty namespace; all code lives under a
  subpackage (`sectum.cli`, `sectum.spec`, and so on).
- `core` and the CLI version and release together, which matches their intended
  cadence.
- `sectum/cli/` is kept as a self-contained subpackage, so it could be lifted out
  into its own distribution later if that ever becomes necessary.
