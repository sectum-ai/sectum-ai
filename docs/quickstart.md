# Quickstart

Sectum AI ships a `uv` workspace and a `sectum` CLI.
[`uv`](https://docs.astral.sh/uv/) is the only prerequisite.

## Run the flagship demo

```sh
git clone https://github.com/sectum-ai/sectum-ai
cd sectum-ai
./examples/retrieval-pivot/run.sh
```

This seeds a four-tenant marker substrate, runs the probe suite against a
deliberately leaky shared vector index, assembles a tamper-evident evidence
pack, and verifies it.

## Drive the CLI directly

```sh
uv run sectum-ai seed   --workdir .sectum-ai
uv run sectum-ai probe  --workdir .sectum-ai
uv run sectum-ai report --workdir .sectum-ai
uv run sectum-ai verify .sectum-ai/evidence.json
```

| Command | Purpose |
|---|---|
| `sectum-ai init` | Scaffold a `sectum-ai.yaml` configuration file. |
| `sectum-ai seed` | Provision synthetic tenants, corpora, and canary markers. |
| `sectum-ai probe` | Run the probe suite and record findings. |
| `sectum-ai report` | Assemble a tamper-evident evidence pack (JSON and PDF). |
| `sectum-ai verify` | Independently verify an evidence pack. |
| `sectum-ai erasure` | Run the GDPR Article 17 erasure-verification workflow. |
| `sectum-ai baseline` | Save a regression baseline, or compare a run against it. |
| `sectum-ai diff` | Compare two runs (or evidence packs); flag new/resolved leaks. |
| `sectum-ai adapters` | List installed adapters and their capabilities. |

Exit codes: `0` no confirmed leaks; `2` a gating result — confirmed leaks
(`sectum-ai probe`), a regression (`sectum-ai diff` / `baseline --compare`), or
residual / attestable-with-caveat data on an erased surface (`sectum-ai erasure`,
where data is presumed retained); `3` config or adapter error; `4` evidence
verification failure.

## Read the probe summary from CI

`sectum-ai probe` defaults to a human-readable summary. Pass `--output json` to
emit a single JSON object on stdout instead — convenient for CI dashboards
that want to act on the headline metrics without scraping prose:

```sh
uv run sectum-ai probe --workdir .sectum-ai --output json | jq '.retrieval_pivot_rate'
```

For GitHub code scanning (or any SAST dashboard), pass `--output sarif` instead to
emit a SARIF 2.1.0 log of the findings — one rule per probe, one result per
finding. Upload it with `github/codeql-action/upload-sarif` and the cross-tenant
findings surface in the repository's **Security** tab. An unverified candidate is
capped at SARIF `note`, and the signed `evidence.json` stays the canonical record.

The summary carries the `run_id`, the probe count, the confirmed-finding
count, the headline Retrieval-Pivot Rate (and per-embedding-model breakdown
when Class 2 swept models), the per-probe finding counts, and a `run_path`
pointer to the full `run.json` on disk. Errors still print to stderr and
exit codes are unchanged.
