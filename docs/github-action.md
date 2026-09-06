# GitHub Action

Run Sectum AI in CI to verify multi-tenant isolation on every change: it seeds a
marker substrate, probes your stack for cross-tenant leaks, and **fails the build
on a confirmed leak**. It wraps the published `sectum-ai` CLI, so it does the same
thing as `sectum-ai seed` + `sectum-ai probe` locally.

## Quickstart

```yaml
# .github/workflows/sectum-ai.yml
name: Multi-tenant leak check
on: [push, pull_request]

jobs:
  sectum-ai:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: sectum-ai/sectum-ai@main   # pin to a release tag or SHA for production
        with:
          config: sectum-ai.yaml         # your adapters; omit to run the demo fixture
```

The action checks out nothing on its own — add `actions/checkout` if your
`config` (and any local adapter wiring) lives in the repo. With **no `config`**
it runs the bundled demo substrate, which is deliberately leaky and therefore
exits with a confirmed leak — handy for trying the action out, not a real test.

> The action ships from `v0.1.2` onward. Pin to a release tag
> (`sectum-ai/sectum-ai@v0.11.0`) or a commit SHA for reproducible runs; `@main`
> tracks the latest.

## Inputs

| Input | Default | Description |
|---|---|---|
| `version` | `0.11.0` | `sectum-ai` version to install from PyPI. Pin for reproducibility; leave empty for the latest release; set `skip` to use a `sectum-ai` already on `PATH` (how this repo's own self-test runs the CLI it just built). |
| `config` | _(none)_ | Path to your `sectum-ai.yaml`. If omitted, the built-in demo substrate is used. |
| `workdir` | `.sectum-ai` | Directory for the seeded substrate and run artifacts. |
| `output` | `json` | Report format written to `output-file`: `text` / `json` / `sarif` / `oscal`. |
| `output-file` | `sectum-results.json` | Where to write the report. |
| `python-version` | `3.12` | Python to set up (`sectum-ai` requires ≥ 3.12). |
| `fail-on-leak` | `true` | Fail the step when the probe confirms a finding — cross-tenant or cross-user, on any surface, the built-in fakes included (probe exit code 2). Must be exactly `true` or `false`: any other value is refused with an error when a finding is found, rather than silently downgrading the gate to a warning. |

## Outputs

| Output | Description |
|---|---|
| `exit-code` | The raw probe exit code: `0` no confirmed findings; `2` a confirmed finding (cross-tenant or cross-user, on any surface — check `confirmed-on-live-surfaces` for the ones that describe your stack) **or a CLI usage error, which shares exit 2**; `3` config/adapter error. The gate step tells the two apart: exit 2 with an empty `results-file` means the probe never ran, and always fails the step. |
| `results-file` | Path to the written report (the `output-file`). |
| `run-path` | Path to the `run.json` the probe wrote in the workdir. |
| `confirmed-findings` | Number of confirmed findings of any kind — cross-tenant or cross-user — on every surface, the built-in fakes included (populated when `output: json`). The Action runs `seed` and `probe` only, so residual-data findings, which come from `sectum-ai erasure`, never appear in this count. |
| `confirmed-on-live-surfaces` | Of those, the confirmed findings on surfaces that ran against a live backend — the ones that describe your stack (populated when `output: json`). |
| `retrieval-pivot-rate` | Headline Retrieval-Pivot Rate (populated when `output: json` and Class 2 ran). |

## Send findings to the Security tab (SARIF)

Set `output: sarif` and upload the file with the standard code-scanning action.
The cross-tenant findings then show up in the repository's **Security → Code
scanning** view (unverified candidates are capped at SARIF `note`, and so are
confirmed findings whose backing surface ran against a built-in fake — a demo run
raises no error-level alert).

```yaml
jobs:
  sectum-ai:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write   # required to upload SARIF
    steps:
      - uses: actions/checkout@v4
      - uses: sectum-ai/sectum-ai@main
        with:
          config: sectum-ai.yaml
          output: sarif
          output-file: sectum-ai.sarif
          fail-on-leak: false    # let the Security tab report; don't block the build
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: sectum-ai.sarif
```

## Keep the signed evidence pack

The probe's `run.json` lands in `workdir`; run `sectum-ai report` afterwards (or a
follow-up step) to assemble a tamper-evident evidence pack and upload it as a
build artifact. The example uses the default workdir `.sectum-ai` — if you set a
custom `workdir`, match it in both the `report --workdir` and the upload `path`:

```yaml
      - run: sectum-ai report --workdir .sectum-ai --config sectum-ai.yaml
      - uses: actions/upload-artifact@v4
        with:
          name: sectum-ai-evidence
          path: .sectum-ai/evidence.json
```

## Notes

- **Exit codes** mirror the CLI: `0` (no confirmed findings), `2` (a confirmed
  finding — cross-tenant or cross-user, on any surface, the built-in fakes
  included — fails the step unless `fail-on-leak: false`), `3` (config/adapter
  error — always fails). See [quickstart.md](quickstart.md).
- The action seeds **before** it probes, using the same `config`, so the marker
  substrate it looks for is the one it planted.
- For live backends (a real vector store, model, or agent framework), put the
  credentials in the job's `env`/secrets and reference them from your
  `sectum-ai.yaml` exactly as you would locally — see
  [configuration.md](configuration.md) and [adapters.md](adapters.md).
