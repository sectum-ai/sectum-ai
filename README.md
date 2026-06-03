# Sectum AI

**Multi-tenant AI verification.** Sectum AI provisions synthetic tenants on an AI
stack, seeds them with cryptographic canary markers, runs benign and adversarial
probes from each tenant's session, and detects cross-tenant data leakage across
every surface — producing tamper-evident, control-mapped evidence that an
auditor accepts.

> **Status: pre-alpha.** All six build-plan phases (the spec, §14) have met their
> acceptance criteria: the marker substrate, the leak-detection pipeline, the
> Class 1–11 attack catalog, the tamper-evident evidence chain (Class 12), the
> adapter SDK (live adapters for vector stores, caches, observability, RAG,
> agents, and MCP, exercised by a docker-compose integration-CI job), the probe
> interface, the regression-baseline engine, the `sectum` CLI, a mkdocs
> documentation site, and the threat model. [`PHASES.md`](PHASES.md) is the
> authoritative, per-phase gate record (with the test/example that enforces each
> criterion). Pre-alpha reflects API maturity, not missing phases.

## The problem

Multi-tenant AI systems universally claim "tenant A's data cannot reach tenant
B." That claim is rarely verified, and published research shows it fails
routinely:

- **OWASP LLM08:2025 — Vector and Embedding Weaknesses** names multi-tenant
  context leakage a top-10 LLM risk.
- **Retrieval Pivot Attacks in Hybrid RAG** ([arXiv:2602.08668](https://arxiv.org/abs/2602.08668), 2026): 95.4% of *benign*
  queries triggered cross-tenant leakage via shared organic entities.
- **Silent Leaks** (arXiv 2505.15420): 91% extraction efficiency via benign
  queries, with no prompt injection required.

Sectum AI verifies that isolation across these surfaces, using a marker
substrate and a manifest-grounded detection pipeline.

## Scope

Sectum AI verifies and attests; it does not remediate findings or provide
runtime protection. See the [threat model](docs/threat-model.md) for the trust
boundaries and non-goals.

## The evidence layer is fully open source

The marker substrate, attack catalog, adapters, evidence chain, and the
independent `sectum-ai verify` are Apache-2.0 — anyone can reproduce a run and
verify a Sectum AI evidence pack without the project. See
[ADR-0002](docs/adr/0002-evidence-layer-oss-boundary.md).

## Open Sectum vs Sectum Cloud

| | **Open Sectum** (this repo) | **Sectum Cloud** (private) |
|---|---|---|
| License | Apache-2.0 | Commercial |
| Marker substrate, attack catalog, adapters | ✓ | ✓ |
| Evidence chain + independent `sectum-ai verify` | ✓ | ✓ |
| `sectum` CLI (`init` / `seed` / `probe` / `report` / `verify` / `erasure` / `baseline` / `diff` / `adapters`) | ✓ | ✓ |
| Continuous scheduled runs against a customer stack | — | ✓ |
| Attestation hosting and managed audit-pack delivery | — | ✓ |
| Dashboard, alerting, and regression baselines across runs | — | ✓ |
| Auditor / DPO channel: pre-curated evidence packages | — | ✓ |

Both share the same evidence format. An evidence pack produced by Sectum Cloud
verifies under the open-source `sectum-ai verify`, by design — there is no
proprietary verification path.

## Repository layout

A `uv` workspace of five publishable packages:

| Package (PyPI) | Import | Purpose |
|---|---|---|
| `sectum-ai` | `sectum` (+ `sectum_ai.cli`) | Core substrate runner and the `sectum` CLI |
| `sectum-ai-spec` | `sectum_ai.spec` | Pydantic data models and JSON Schema |
| `sectum-ai-probes` | `sectum_ai.probes` | The multi-tenant leakage attack catalog |
| `sectum-ai-adapters` | `sectum_ai.adapters` | Connectors to real systems |
| `sectum-ai-evidence` | `sectum_ai.evidence` | Evidence chain, verification, audit packs |

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
uv run sectum-ai seed   --workdir .sectum-ai
uv run sectum-ai probe  --workdir .sectum-ai
uv run sectum-ai report --workdir .sectum-ai
uv run sectum-ai verify .sectum-ai/evidence.json
```

For richer configuration (live vector store, real embedder/judge, Rekor
signing, manifest-at-rest), copy
[`sectum-ai.yaml.example`](sectum-ai.yaml.example) to `sectum-ai.yaml` and pass
`--config sectum-ai.yaml` to each command.

To work on the repository itself, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation, security, contributing

- Architecture decisions: [docs/adr/](docs/adr/)
- Threat model: [docs/threat-model.md](docs/threat-model.md)
- Security policy and private disclosure: [SECURITY.md](SECURITY.md)
- Contributing guide: [CONTRIBUTING.md](CONTRIBUTING.md)

## References

- OWASP LLM08:2025 — Vector and Embedding Weaknesses
- Retrieval Pivot Attacks in Hybrid RAG ([arXiv:2602.08668](https://arxiv.org/abs/2602.08668), 2026)
- Silent Leaks (arXiv 2505.15420)

## Support

Sectum AI is independent and self-funded. If the work matters to you:

- **Sponsor on GitHub:** [github.com/sponsors/sectum-ai](https://github.com/sponsors/sectum-ai) keeps the OSS evidence layer fully open.
- **Commercial support:** for Sectum Cloud, custom adapters, or a DPO-grade
  GDPR Article 17 erasure-attestation engagement, get in touch via
  [security@sectum.ai](mailto:security@sectum.ai).

## License

Apache-2.0 — see [LICENSE](LICENSE).
