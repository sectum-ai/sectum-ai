# Examples

Runnable, end-to-end walkthroughs of the Sectum AI verification workflow. Each
example is a self-contained directory with a `run.sh` script and a `README.md`.

| Example | Attack class | What it shows |
|---|---|---|
| [`tenant-boundary-fetch/`](tenant-boundary-fetch/) | Class 1 | Negative-authorization check: from one tenant's session, attempts to fetch a foreign tenant's objects and canary doc IDs and expects denial. |
| [`retrieval-pivot/`](retrieval-pivot/) | Class 2 (flagship) | Benign cross-tenant leakage on a shared vector index, carried end to end into a verified evidence pack. |
| [`rag-poisoning/`](rag-poisoning/) | Class 3 | One tenant plants a poison document under a lure phrase; another tenant's query of the lure retrieves the planted canary across the boundary. |
| [`semantic-cache/`](semantic-cache/) | Class 4 | A semantic/prompt cache that is not tenant-scoped serves one tenant's cached answer (carrying a canary) to another tenant's similar query. |
| [`kv-cache-timing/`](kv-cache-timing/) | Class 5 | A shared KV prefix cache leaks a victim tenant's prompt prefix through a measurable TTFT timing gap (confirmed by a Welch t-test). |
| [`embedding-inversion/`](embedding-inversion/) | Class 6 | Recovering a foreign tenant's source content from cross-tenant-reachable embeddings. |
| [`agent-tool-hijack/`](agent-tool-hijack/) | Class 7 | The Class 7 probe framed from the agent-adapter side, with copy-pasteable `factories.py` callables for `langgraph` / `autogen` / `crewai` / `openai-assistants` / `anthropic-tooluse`. |
| [`mcp-tenant-boundary/`](mcp-tenant-boundary/) | Class 7 | Cross-tenant agent tool-call hijacking — the MCP confused-deputy and token-passthrough flaws. |
| [`agent-framework-hijack/`](agent-framework-hijack/) | Class 7 | The same hijack driven directly through an agent framework (not via MCP), surfacing a foreign canary through a tool call. |
| [`memory-contamination/`](memory-contamination/) | Class 8 | Persistent memory contamination (SpAIware-class) — a long-term memory store that has lost tenant scope. |
| [`lora-cross-tenant/`](lora-cross-tenant/) | Class 9 | A mis-routed per-tenant LoRA stack bleeds one tenant's memorized canary into another tenant's inference. |
| [`ikea-extraction/`](ikea-extraction/) | Class 10 | A fixed multi-turn benign query sequence surfaces a foreign tenant's canary from a shared vector index — no prompt injection. |
| [`erasure-attestation/`](erasure-attestation/) | Class 11 | A GDPR Article 17 erasure-verification run and its attestation pack. |
| [`open-webui-run/`](open-webui-run/) | Class 2 (flagship), 1, 11 | Sectum against a **self-hosted Open WebUI** (real product): seeds the substrate, uploads each tenant's corpus into Open WebUI Knowledge via its API, and measures the Retrieval-Pivot Rate through Open WebUI's chat-with-knowledge endpoint. Requires Docker; not part of the offline `SECTUM_RUN_E2E` suite. |
| [`byoc-runner/`](byoc-runner/) | — | A BYOC operator workflow: a Sectum CLI install reads a Cloud snapshot subscription. |

Each `run.sh` invokes the `sectum-ai` CLI from this repository through `uv` and
writes its artifacts to an `out/` directory inside the example. Those `out/`
directories are git-ignored.

**Prerequisites:** [`uv`](https://docs.astral.sh/uv/). The scripts run `sectum-ai`
via `uv run`, so no separate install step is needed.

```sh
cd examples/retrieval-pivot && ./run.sh
```
