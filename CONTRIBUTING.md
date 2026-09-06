# Contributing to Sectum AI

Thanks for your interest in Sectum AI. This guide covers local development, our
conventions, and how changes reach `main`.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — the project's package and workspace
  manager. `uv` provisions the correct Python (3.12+) automatically.
- `git`, with commit signing configured (see below).

## Local setup

```sh
git clone https://github.com/sectum-ai/sectum-ai.git
cd sectum-ai
uv sync --all-packages      # creates .venv, installs all packages + dev tools
uv run pre-commit install   # enable git hooks
```

## Everyday commands

| Task | Command |
|---|---|
| Run the test suite | `uv run pytest` |
| Run the integration tests | `docker compose up -d --wait` then `uv run pytest -m integration` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type-check | `uv run mypy` |
| Run all pre-commit hooks | `uv run pre-commit run --all-files` |
| Run the example walkthroughs | `SECTUM_RUN_E2E=1 uv run pytest -m e2e` |
| Build the docs site | `uv run --group docs mkdocs build --strict` |
| Check the coverage floors | `uv run pytest --cov=sectum_ai` first (plain `pytest` writes no coverage data), then `uv run coverage report --include="packages/<pkg>/src/*" --fail-under=85` for core, probes and evidence |
| Run the CLI | `uv run sectum-ai --help` |
| Check the lockfile is current | `uv lock --check` (all three CI `uv sync` steps are `--locked`, so commit `uv.lock` with any dependency change) |
| Run the secret scan | `gitleaks dir .` on a clean checkout ([install](https://github.com/gitleaks/gitleaks)). The `Secret scan` CI job runs this; the pre-commit `detect-private-key` hook does **not** cover it, and a credential-shaped test fixture written as `api_key": "sk-..."` trips gitleaks' generic rule. Build such fixtures at runtime instead of committing the literal. |

The default `uv run pytest` stays fully offline: the integration tests in
`tests/integration/` skip themselves unless their backend is reachable. Bring the
local backends up with `docker compose up -d --wait` (pgvector, Chroma, Weaviate,
Qdrant, OpenSearch, Redis, Phoenix — see [`compose.yaml`](compose.yaml)) and they run against
the live adapters. Note that only pgvector and Redis define a healthcheck, so
`--wait` returns before the HTTP backends are ready; a fixture that cannot reach its
backend **skips** rather than fails, so give them a few seconds (CI polls each one's
readiness endpoint for up to 180 s before running the job). CI runs them too, in the dedicated **Integration** job. (Milvus is
heavier — it needs etcd and minio — so it lives behind a compose profile: run
`docker compose --profile milvus up -d` to exercise its test locally.)

## Conventions

- **Conventional Commits.** Commit messages follow
  [conventionalcommits.org](https://www.conventionalcommits.org/): `feat:`,
  `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, and so on.
- **One logical change per pull request.** Keep PRs small and reviewable.
- **Typed public APIs.** Every public function has type hints — `mypy` runs in
  strict mode and enforces that. A docstring on anything non-obvious is the house
  convention (Sphinx cross-references, not Google style); no linter checks it, so
  it is a review expectation rather than a gate.
- **Determinism.** Anything seeded must be reproducible; thread RNG explicitly,
  with no hidden global state.
- **Never commit secrets** or customer data. Secret scanning (gitleaks) runs in
  pre-commit and CI and will block the change.
- **The pre-commit hooks are a CI gate.** `uv run pre-commit run --all-files`
  runs in the `Lint, type-check, test` job, so a hook that is red on a clean
  checkout fails the build rather than surprising the next contributor. Two of
  them are commit-time only and check nothing under `--all-files`:
  `check-added-large-files` looks at newly *staged* files, and
  `check-merge-conflict` at a tree mid-merge. Secret scanning is covered by the
  standalone `Secret scan` job, which scans the whole tree. The
  checked-in evidence packs under `docs/samples/` and the captured TSA token are
  excluded from the whitespace hooks: they are artefacts of a run, and a
  formatting hook must not rewrite them.
- New runtime dependencies need a stated reason in the PR — what they enable that the
  standard library and existing dependencies cannot — and go behind an optional extra
  unless every install needs them.

## Commit signing

Commits on `main` must be signed. Configure one of:

- **Sigstore gitsign** (keyless, recommended) —
  see <https://docs.sigstore.dev/cosign/signing/gitsign/>; or
- **GPG or SSH signing** — `git config commit.gpgsign true` with a key
  registered on your GitHub account.

## Branch protection (target configuration)

`main` is a protected branch. The protection rules the repository targets — this
section is the source of truth for that configuration:

- Require a pull request before merging; **no direct pushes to `main`**.
- Require **1 approving review**; dismiss stale approvals on new commits.
- Require **CODEOWNERS** review.
- Require status checks to pass before merging. These are the context names
  GitHub reports, which is what branch protection matches on — the job's `name:`,
  not its key: `Lint, type-check, test`, `Integration (docker-compose backends)`,
  `Extras API contract`, `Secret scan`, `Analyze (Python)` (CodeQL), and
  `Build docs site` (`mkdocs build --strict`). The `Action self-test` workflow is **not**
  a required check: it is filtered to changes touching `action.yml`, and a
  workflow that does not run never reports, so requiring it would block every
  unrelated pull request on a check that cannot arrive.
  `tests/unit/test_action_cli_contract.py` and
  `tests/unit/test_action_version.py` are what run on every PR.
- Require branches to be **up to date** before merging.
- Require **signed commits**.
- Require **linear history** (squash or rebase merges only).
- Include administrators in these restrictions.

## Architecture decisions

Significant decisions are recorded as ADRs in [`docs/adr/`](docs/adr/). If a
change involves an architectural choice, add or update an ADR in the same PR.

## Trust policy: how releases are signed

Sectum AI ships its five packages with **OIDC end to end** — no static
publishing token lives in this repository:

- **PyPI** publishes via a Trusted Publisher (OIDC) bound to this repository's
  `release.yml` workflow.
- **Sigstore** signs every sdist, wheel, and CycloneDX SBOM with a short-lived
  Fulcio certificate issued against the workflow's OIDC identity, producing a
  `.sigstore` bundle that anchors to the public Rekor transparency log.
- The `.sigstore` bundles and SBOMs are attached to the matching **GitHub
  Release** so an auditor can verify a release without scraping PyPI.

A consumer verifies a downloaded artifact with `cosign verify-blob` against the
release workflow's identity. The exact recipe and the operator's release
procedure are in [`docs/RELEASING.md`](docs/RELEASING.md).

## Reporting security issues

Do not open public issues for vulnerabilities — see [SECURITY.md](SECURITY.md).
