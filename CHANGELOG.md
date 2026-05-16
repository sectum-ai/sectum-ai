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

### Notes

- Delivery sequencing: the public Apache-2.0 repositories are completed before
  any private repository is started.
- The 85% coverage gate (CLAUDE.md section 15) is configured but deferred until
  Phase 1, when there is source code to cover.

[Unreleased]: https://github.com/sectum-ai/sectum-ai/commits/main
