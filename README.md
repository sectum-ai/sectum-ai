# Sectum AI

**Multi-tenant AI verification.** Sectum AI provisions synthetic tenants on an AI
stack, seeds them with cryptographic canary markers, runs benign and adversarial
probes from each tenant's session, and detects cross-tenant data leakage across
every surface — producing tamper-evident, control-mapped evidence that an
auditor accepts.

> **Status: pre-alpha.** Phases 0–3 of the build plan are complete: the marker
> substrate, the leak-detection pipeline, the adapter SDK (with live pgvector
> and Chroma adapters), the probe interface, the Class 1/2/4/11 attack catalog,
> the tamper-evident evidence chain, and the `sectum` CLI. Phase 4 — the killer
> demo, the remaining probes, and the documentation site — is next.

## The problem

Multi-tenant AI systems universally claim "tenant A's data cannot reach tenant
B." That claim is rarely verified, and published research shows it fails
routinely:

- **OWASP LLM08:2025 — Vector and Embedding Weaknesses** names multi-tenant
  context leakage a top-10 LLM risk.
- **Retrieval Pivot Attacks in Hybrid RAG** (arXiv, 2026): 95.4% of *benign*
  queries triggered cross-tenant leakage via shared organic entities.
- **Silent Leaks** (arXiv 2505.15420): 91% extraction efficiency via benign
  queries, with no prompt injection required.

No product verifies multi-tenant isolation across the full AI surface.
Sectum AI does.

## What Sectum AI is not

Sectum AI is not a firewall, a runtime guardrail, a generalist LLM red-team tool, a
GRC platform, or a SOC 2 readiness tool. It does not remediate — it verifies and
attests.

## Open Sectum AI vs Sectum AI Cloud

|  | Open Sectum AI (this repo) | Sectum AI Cloud |
|---|---|---|
| License | Apache-2.0 | Commercial |
| Marker substrate, attack catalog, adapters | Yes | Yes |
| Evidence chain + independent `sectum verify` | Yes | Yes |
| Hosted attestation, registry, scheduled runs | — | Yes |
| Regression baselines, dashboard | — | Yes |
| Auditor-grade engagement + branded packs | — | Yes |

The evidence layer is fully open source — anyone can independently verify a
Sectum AI evidence pack. See
[ADR-0002](docs/adr/0002-evidence-layer-oss-boundary.md).

## Repository layout

A `uv` workspace of five publishable packages:

| Package (PyPI) | Import | Purpose |
|---|---|---|
| `sectum-ai` | `sectum` (+ `sectum.cli`) | Core substrate runner and the `sectum` CLI |
| `sectum-ai-spec` | `sectum.spec` | Pydantic data models and JSON Schema |
| `sectum-ai-probes` | `sectum.probes` | The multi-tenant leakage attack catalog |
| `sectum-ai-adapters` | `sectum.adapters` | Connectors to real systems |
| `sectum-ai-evidence` | `sectum.evidence` | Evidence chain, verification, audit packs |

## Quickstart

Run the flagship demo — the organic entity-bleed Retrieval Pivot — end to end
([`uv`](https://docs.astral.sh/uv/) is the only prerequisite):

```sh
git clone https://github.com/sectum-ai/sectum-ai
cd sectum-ai
./examples/retrieval-pivot/run.sh
```

It seeds a four-tenant marker substrate, probes a deliberately leaky shared
vector index, assembles a tamper-evident evidence pack, and independently
verifies it. See [`examples/`](examples/) for this and the GDPR Article 17
erasure-attestation walkthrough.

Or drive the `sectum` CLI directly:

```sh
uv run sectum seed   --workdir .sectum
uv run sectum probe  --workdir .sectum
uv run sectum report --workdir .sectum
uv run sectum verify .sectum/evidence.json
```

To work on the repository itself, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation, security, contributing

- Architecture decisions: [docs/adr/](docs/adr/)
- Security policy and private disclosure: [SECURITY.md](SECURITY.md)
- Contributing guide: [CONTRIBUTING.md](CONTRIBUTING.md)

## References

- OWASP LLM08:2025 — Vector and Embedding Weaknesses
- Retrieval Pivot Attacks in Hybrid RAG (arXiv, 2026)
- Silent Leaks (arXiv 2505.15420)

## License

Apache-2.0 — see [LICENSE](LICENSE).
