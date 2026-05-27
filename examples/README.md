# Examples

Runnable, end-to-end walkthroughs of the Sectum AI verification workflow. Each
example is a self-contained directory with a `run.sh` script and a `README.md`.

| Example | Attack class | What it shows |
|---|---|---|
| [`retrieval-pivot/`](retrieval-pivot/) | Class 2 (flagship) | Benign cross-tenant leakage on a shared vector index, carried end to end into a verified evidence pack. |
| [`erasure-attestation/`](erasure-attestation/) | Class 11 | A GDPR Article 17 erasure-verification run and its attestation pack. |
| [`mcp-tenant-boundary/`](mcp-tenant-boundary/) | Class 7 | Cross-tenant agent tool-call hijacking — the MCP confused-deputy and token-passthrough flaws. |
| [`agent-tool-hijack/`](agent-tool-hijack/) | Class 7 | The same Class 7 probe framed from the agent-adapter side, with copy-pasteable `factories.py` callables for `langgraph` / `autogen` / `crewai` / `http`. |
| [`memory-contamination/`](memory-contamination/) | Class 8 | Persistent memory contamination (SpAIware-class) — a long-term memory store that has lost tenant scope. |
| [`byoc-runner/`](byoc-runner/) | — | A BYOC operator workflow: a Sectum CLI install reads a Cloud snapshot subscription. |

Each `run.sh` invokes the `sectum` CLI from this repository through `uv` and
writes its artifacts to an `out/` directory inside the example. Those `out/`
directories are git-ignored.

**Prerequisites:** [`uv`](https://docs.astral.sh/uv/). The scripts run `sectum`
via `uv run`, so no separate install step is needed.

```sh
cd examples/retrieval-pivot && ./run.sh
```
