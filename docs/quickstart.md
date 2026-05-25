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
uv run sectum seed   --workdir .sectum
uv run sectum probe  --workdir .sectum
uv run sectum report --workdir .sectum
uv run sectum verify .sectum/evidence.json
```

| Command | Purpose |
|---|---|
| `sectum init` | Scaffold a `sectum.yaml` configuration file. |
| `sectum seed` | Provision synthetic tenants, corpora, and canary markers. |
| `sectum probe` | Run the probe suite and record findings. |
| `sectum report` | Assemble a tamper-evident evidence pack (JSON and PDF). |
| `sectum verify` | Independently verify an evidence pack. |
| `sectum erasure` | Run the GDPR Article 17 erasure-verification workflow. |
| `sectum baseline` | Save a regression baseline, or compare a run against it. |
| `sectum adapters` | List installed adapters and their capabilities. |

Exit codes: `0` no confirmed leaks; `2` confirmed leaks present; `3` config or
adapter error; `4` evidence verification failure.

## Read the probe summary from CI

`sectum probe` defaults to a human-readable summary. Pass `--output json` to
emit a single JSON object on stdout instead — convenient for CI dashboards
that want to act on the headline metrics without scraping prose:

```sh
uv run sectum probe --workdir .sectum --output json | jq '.retrieval_pivot_rate'
```

The summary carries the `run_id`, the probe count, the confirmed-finding
count, the headline Retrieval-Pivot Rate (and per-embedding-model breakdown
when Class 2 swept models), the per-probe finding counts, and a `run_path`
pointer to the full `run.json` on disk. Errors still print to stderr and
exit codes are unchanged.
