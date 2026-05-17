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
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type-check | `uv run mypy` |
| Run all pre-commit hooks | `uv run pre-commit run --all-files` |
| Run the CLI | `uv run sectum --help` |

## Conventions

- **Conventional Commits.** Commit messages follow
  [conventionalcommits.org](https://www.conventionalcommits.org/): `feat:`,
  `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, and so on.
- **One logical change per pull request.** Keep PRs small and reviewable.
- **Typed public APIs.** Every public function has type hints and a docstring
  (Google style). `mypy` runs in strict mode.
- **Determinism.** Anything seeded must be reproducible; thread RNG explicitly,
  with no hidden global state.
- **Never commit secrets** or customer data. Secret scanning (gitleaks) runs in
  pre-commit and CI and will block the change.
- New runtime dependencies must be justified against the engineering spec, section 13.

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
- Require status checks to pass before merging: the `CI` workflow
  (lint, type-check, test), the `secret-scan` job, and `CodeQL`.
- Require branches to be **up to date** before merging.
- Require **signed commits**.
- Require **linear history** (squash or rebase merges only).
- Include administrators in these restrictions.

## Architecture decisions

Significant decisions are recorded as ADRs in [`docs/adr/`](docs/adr/). If a
change involves an architectural choice, add or update an ADR in the same PR.

## Reporting security issues

Do not open public issues for vulnerabilities — see [SECURITY.md](SECURITY.md).
