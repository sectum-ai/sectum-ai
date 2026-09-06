# Releasing Sectum AI

This is the operator's reference for cutting a signed Sectum AI release. The
pipeline is fully automated; this document is the human-facing checklist around
it.

A release ships **all five packages** (`sectum-ai`, `sectum-ai-spec`,
`sectum-ai-probes`, `sectum-ai-adapters`, `sectum-ai-evidence`) to PyPI at the
same version, with a CycloneDX SBOM and a Sigstore (keyless) bundle per
distribution, attached to a matching GitHub Release whose notes are taken
verbatim from `CHANGELOG.md`.

The credential story is **OIDC end to end**: PyPI publishes via Trusted
Publisher, and Sigstore signs against the workflow's short-lived OIDC identity.
This repository contains no static publishing token, by design.

## Prerequisites (one-time, done by the maintainer)

These steps configure the credential-less trust paths. They run once per
project and never need touching again.

> **Do all three steps below BEFORE you push your first `v*` tag.** The
> publish-pypi job runs *after* a maintainer approves the `pypi`
> environment, and if the Pending Publishers in step 1 are missing PyPI
> rejects the upload with `invalid-publisher: Publisher with matching
> claims was not found`. The build/SBOM/sign work already done is not
> lost — re-run the failed `publish-pypi` job once the publishers are
> registered and the same artefacts will publish — but cleaner to set
> up the prerequisites first.

### 1. Register the PyPI Trusted Publisher for every package

Each of the five distributions is registered separately. For a project that has
**never been published**, use PyPI's *Pending Publisher* form so the first
release can mint the distribution itself.

Go to <https://pypi.org/manage/account/publishing/> and add a pending
publisher for **each row** of the table below. The values below are the only
ones that change per package; every other field is identical.

| PyPI Project Name | Owner | Repository | Workflow name | Environment name |
|---|---|---|---|---|
| `sectum-ai` | `sectum-ai` | `sectum-ai` | `release.yml` | `pypi` |
| `sectum-ai-spec` | `sectum-ai` | `sectum-ai` | `release.yml` | `pypi` |
| `sectum-ai-probes` | `sectum-ai` | `sectum-ai` | `release.yml` | `pypi` |
| `sectum-ai-adapters` | `sectum-ai` | `sectum-ai` | `release.yml` | `pypi` |
| `sectum-ai-evidence` | `sectum-ai` | `sectum-ai` | `release.yml` | `pypi` |

After the first release each project converts from a *Pending* publisher to a
real Trusted Publisher; the form is the same.

PyPI's documentation:
<https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/>.

### 2. Create the `pypi` GitHub Environment

Repository → **Settings** → **Environments** → **New environment**, named
exactly `pypi` (the workflow's `environment.name`). Recommended protection:

- **Required reviewers**: the maintainer (the `publish-pypi` job pauses for
  an approval before it uploads anything to PyPI).
- **Deployment branches**: restrict to tags matching `v*`.

No secrets are stored in the environment. The OIDC identity the workflow
presents is enough.

### 3. Verify the workflow has the right permissions

The repository's default GitHub Actions permissions must allow `id-token:
write` and `contents: write` *on the workflow's own jobs* (the workflow
declares these per-job). At the repository level, **Settings → Actions →
General** should set "Workflow permissions" to either:

- "Read repository contents and packages permissions" (recommended), or
- "Read and write permissions".

The per-job `permissions:` block in `release.yml` narrows from there.

## The release procedure

Run from a clean working tree on `main`. Every step below maps to a file the
pipeline reads or to a check the pipeline performs.

### 1. Bump every package's version

Edit `[project] version` in each of:

- `packages/core/pyproject.toml`
- `packages/spec/pyproject.toml`
- `packages/probes/pyproject.toml`
- `packages/adapters/pyproject.toml`
- `packages/evidence/pyproject.toml`

All five must be the same string, and `uv lock` must be re-run after editing
them (the recipe stages `uv.lock`; all three CI `uv sync` steps are `--locked`, so
a stale lock fails the build rather than shipping unnoticed). The first release is `0.1.0`. Subsequent
releases follow [Semantic Versioning](https://semver.org/). For a pre-release the
two spellings differ: the tag is `v0.11.0-rc.1` and its CHANGELOG heading is
`## [0.11.0-rc.1]`, but `pyproject.toml` must carry the PEP 440 form `0.11.0rc1` —
`scripts/check_release_version.py` normalises the tag and compares against that.

Then bump the **same version** in these places — surfaces this list used to
omit, each of which shipped stale at least once:

- `action.yml` — the `version` input's `default`. (Its description's
  "(for example 1.2.3)" is deliberately a placeholder, not the shipped version,
  so nothing there goes stale; leave it alone.)
- `docs/github-action.md` — the `version` row of the inputs table, and the
  `sectum-ai/sectum-ai@vX.Y.Z` pin example
- `README.md` — the `> **Status: vX.Y.Z.**` line (it read v0.8.1 while the repo
  shipped 0.10.0)
- `docs/index.md` — the "Sectum AI is at vX.Y.Z" line
- `SECURITY.md` — the "Latest `0.x` minor (currently `0.Y.x`)" row of the
  supported-versions table

That default is passed straight to `pip install "sectum-ai==<version>"`, so a
caller who does not override it gets exactly this string. Leaving it behind means
every default run of the Action installs the *previous* release: v0.7.0 through
v0.8.3 all shipped while the Action kept installing 0.6.0, handing users a CLI
that predated the correctness fixes those releases existed to deliver.
`tests/unit/test_action_version.py` now fails the build if the Action default, the
docs table, the docs pin, the README status line, the `docs/index.md` version
line, or the `SECURITY.md` supported-minor row drifts from the package version,
so this step cannot be silently skipped again. (The `action.yml` prose is
unguarded — check it by hand.)

### 2. Re-validate the ATLAS technique catalog

[ADR-0009](adr/0009-atlas-technique-review-process.md) makes this a release
gate. Run the sweep against the
[MISP mirror](https://raw.githubusercontent.com/MISP/misp-galaxy/main/clusters/mitre-atlas-attack-pattern.json)
and note the ATLAS revision in the release PR description.

### 3. Update `CHANGELOG.md`

Rename the `## [Unreleased]` heading to `## [X.Y.Z]` (the version you bumped
to), and start a fresh empty `## [Unreleased]` block above it. Add the date in
the heading line if you like, but the script that extracts the section reads
the bracketed label only.

A final tag (`v0.1.0`) **requires** a matching section in CHANGELOG.md. A
pre-release tag (`v0.1.0-rc.1`) is allowed to fall back to `## [Unreleased]`
if its named section is absent — but an *empty* `[Unreleased]` is refused, so
the release notes must exist somewhere.

### 4. Commit and open the release PR

```sh
git checkout -b release/v0.1.0
git add packages/*/pyproject.toml action.yml docs/github-action.md docs/index.md README.md SECURITY.md CHANGELOG.md uv.lock
git commit -m "chore(release): v0.1.0"
git push -u origin release/v0.1.0
gh pr create --title "chore(release): v0.1.0" --body "ATLAS sweep: ..."
```

Merge after review.

### 5. Tag and push

After the merge lands on `main`:

```sh
git checkout main && git pull
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

Use an **annotated** tag (the `-a` flag) so it carries a tagger and a message —
by convention; the workflow triggers on any `v*` tag and does not check. Every shipped tag from `v0.5.0`
onward is annotated and unsigned, and the pipeline accepts them — the release's
authenticity comes from Sigstore signing the *artifacts* in the workflow (OIDC,
no long-lived key), not from a signature on the tag. Add `-s` as well if you
have a key configured.

### 6. Watch the pipeline

The `Release` workflow fires on the tag push. The job graph is:

```
build  ─┐
         ├── sign ── publish-pypi ── github-release
sbom  ─┘
```

The `publish-pypi` job pauses for the environment's required reviewers; an
approval there is the final human gate. After it succeeds, the GitHub Release
is created automatically with the CHANGELOG section as its body.

### Tag formats the workflow recognises

| Tag | Treated as | Notes |
|---|---|---|
| `v0.1.0`, `v1.2.3` | Final release | CHANGELOG must have `## [0.1.0]`. |
| `v0.1.0-rc.1` | Pre-release (`rc`) | Falls back to `## [Unreleased]`. |
| `v0.1.0-alpha.2` | Pre-release (`alpha`) | Falls back to `## [Unreleased]`. |
| `v0.1.0-beta.3` | Pre-release (`beta`) | Falls back to `## [Unreleased]`. |

Other tag forms never reach the workflow: the `push` trigger is `v*` tags only,
and `scripts/check_release_version.py` additionally rejects a `v*` tag that is not
`vX.Y.Z[-pre]` (such as `v0.1`).

**The workflow has a second trigger.** `workflow_dispatch` runs the staged
bootstrap: with `publish_package` set to one distribution it publishes exactly
that one, so the project exists and its pending Trusted Publisher activates;
with `none` it builds and signs without publishing. That path carries no tag, so
`check_release_version.py` does not run and nothing verifies the version being
shipped — the `pypi` environment's required reviewer is the only gate. Use it to
create a project, never to ship a release.

## Verifying a released artifact

A consumer can verify a Sectum AI release without trusting this repository or
PyPI - they only need to trust Sigstore's public-good Fulcio/Rekor instances
and the GitHub OIDC issuer that signed the bundle.

```sh
# 1. Download the wheel from PyPI and the matching .sigstore bundle from the
#    GitHub Release for the same tag.
pip download --no-deps -d ./verify sectum-ai==0.1.0
gh release download v0.1.0 --repo sectum-ai/sectum-ai \
  --pattern 'sectum_ai-0.1.0-*.whl.sigstore' --dir ./verify

# 2. Verify with cosign. The certificate identity below pins the workflow that
#    minted the signature; the OIDC issuer pins where the identity came from.
cosign verify-blob \
  --bundle ./verify/sectum_ai-0.1.0-py3-none-any.whl.sigstore \
  --certificate-identity-regexp \
    'https://github.com/sectum-ai/sectum-ai/.github/workflows/release.yml@refs/tags/v.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ./verify/sectum_ai-0.1.0-py3-none-any.whl
```

`cosign verify-blob` exits 0 on a good signature. The same recipe verifies
sdists and SBOMs - replace the filename and bundle on both sides.

The SBOM itself is plain CycloneDX 1.x JSON; any CycloneDX-aware tool
(`grype sbom:...`, `dependency-track`, `cyclonedx-cli`) reads it.

## Yanking or withdrawing a release

A released distribution that turns out to be broken or compromised can be
**yanked** on PyPI without deleting it (existing pins keep resolving; new
installs surface a warning). Use PyPI's web UI:

1. <https://pypi.org/manage/project/sectum-ai/releases/> (and the four sibling
   project URLs).
2. Open the release, click **Options** → **Yank**, enter a short reason that
   names the issue and links the advisory.

Yank every affected package at the same time; the five distributions ship as
a set, so a yank on one without the others is a partial release.

On the GitHub side, mark the matching Release as a "Pre-release" (so it stops
being the *latest*) and add a note at the top of its body pointing at the
follow-up release or advisory. Do not delete the tag - existing pins, signed
artifacts, and Sigstore log entries reference it.

Publish a follow-up release (`vX.Y.Z+1`) as soon as a fix is ready, and follow
the disclosure cadence in
[`SECURITY.md`](https://github.com/sectum-ai/sectum-ai/blob/main/SECURITY.md)
for the underlying
vulnerability.
