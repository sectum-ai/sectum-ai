# sectum-ai

**Multi-tenant AI verification.** This is the core distribution of [Sectum AI](https://github.com/sectum-ai/sectum-ai):
the marker-substrate runner and the `sectum` command-line interface.

Sectum AI provisions synthetic tenants on an AI stack, seeds them with
cryptographic canary markers, runs benign and adversarial probes from each
tenant's session, and detects cross-tenant data leakage across every surface —
producing tamper-evident, control-mapped evidence that an auditor accepts.

## Install

```sh
pip install sectum-ai
```

This pulls the full family: `sectum-ai-spec` (data models), `sectum-ai-probes`
(the Class 1–11 attack catalog + leak-detection pipeline), `sectum-ai-adapters`
(connectors for vector stores, caches, observability, RAG, agents, and MCP), and
`sectum-ai-evidence` (the tamper-evident evidence chain + `sectum verify`).

## Quickstart

```sh
sectum seed      # provision synthetic tenants + plant canary markers
sectum probe     # run the attack catalog from each tenant's session
sectum report    # assemble a signed, control-mapped evidence pack (JSON + PDF)
sectum verify out/evidence.json   # independently re-verify the pack
```

## Links

- Documentation: <https://docs.sectum.ai>
- Source, full README, and attack catalog: <https://github.com/sectum-ai/sectum-ai>

Apache-2.0. The marker substrate, attack catalog, adapters, evidence chain, and
the independent `sectum verify` are fully open source.
