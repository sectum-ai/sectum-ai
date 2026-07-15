# sectum-ai

**Multi-tenant AI verification.** This is the core distribution of [Sectum AI](https://github.com/sectum-ai/sectum-ai):
the marker-substrate runner and the `sectum-ai` command-line interface.

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
(connectors for vector stores, caches, memory, observability, RAG, agents, MCP,
and the search-index / eval-set / backup erasure surfaces), and
`sectum-ai-evidence` (the tamper-evident evidence chain + `sectum-ai verify`).

## Quickstart

```sh
sectum-ai seed      # provision synthetic tenants + plant canary markers
sectum-ai probe     # run the attack catalog from each tenant's session
sectum-ai report    # assemble a signed, control-mapped evidence pack (JSON + PDF)
sectum-ai verify .sectum-ai/evidence.json   # independently re-verify the pack
```

## Links

- Documentation: <https://docs.sectum.ai>
- Source, full README, and attack catalog: <https://github.com/sectum-ai/sectum-ai>

Apache-2.0. The marker substrate, attack catalog, adapters, evidence chain, and
the independent `sectum-ai verify` are fully open source.
