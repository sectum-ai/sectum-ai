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
| `sectum adapters` | List installed adapters and their capabilities. |

Exit codes: `0` no confirmed leaks; `2` confirmed leaks present; `3` config or
adapter error; `4` evidence verification failure.
