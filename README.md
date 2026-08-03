# Sectum AI

**AI data-isolation verification.** Sectum AI proves that no user can read
another user's data — and no customer another customer's — through your vector
DB, RAG pipeline, agent framework, semantic cache, fine-tunes, or MCP servers.
It provisions synthetic tenants on a live stack, seeds them with cryptographic
canary markers, runs an 11-class attack catalog across 13 surfaces, and produces
a tamper-evident PDF plus a machine-readable evidence pack that auditors,
customer security teams, and DPOs accept — and that anyone can verify
independently, without trusting us.

> **Status: pre-alpha.** All six build-plan phases (the spec, §14) have met their
> acceptance criteria: the marker substrate, the leak-detection pipeline, the
> Class 1–11 and 13 attack catalog, the tamper-evident evidence chain (Class 12), the
> adapter SDK (live adapters for vector stores, caches, memory, observability,
> RAG, agents, MCP, and the search-index / eval-set / backup erasure surfaces,
> exercised by a docker-compose integration-CI job), the probe
> interface, the regression-baseline engine, the `sectum-ai` CLI, a mkdocs
> documentation site, and the threat model. [`PHASES.md`](PHASES.md) is the
> authoritative, per-phase gate record (with the test/example that enforces each
> criterion). Pre-alpha reflects API maturity, not missing phases.

## The problem

AI systems universally claim "tenant A's data cannot reach tenant B." That claim
is rarely verified, and published research shows it fails routinely:

- **OWASP LLM08:2025 — Vector and Embedding Weaknesses** names multi-tenant
  context leakage a top-10 LLM risk.
- **Retrieval Pivot Attacks in Hybrid RAG** ([arXiv:2602.08668](https://arxiv.org/abs/2602.08668), 2026): 95.4% of *benign*
  queries triggered cross-tenant leakage via shared organic entities — and
  **stronger embedding models leaked more**.
- **Silent Leaks** (arXiv 2505.15420): 91% extraction efficiency via benign
  queries, with no prompt injection required.

Sectum AI verifies that isolation across these surfaces, using a marker
substrate and a manifest-grounded detection pipeline.

## What Sectum AI does

**Marker substrate.** Synthetic tenants seeded with three classes of
cryptographic canary markers and a hashed ground-truth manifest. Deterministic,
reproducible, manifest-grounded — zero false positives.

**13 surfaces.** Vector DB, RAG pipeline, semantic cache, KV cache, agent
memory, MCP tool calls, fine-tunes / adapters, eval sets, backups, search
indexes, tracing pipelines, prompt/completion logs, API. Live adapters for the
common backends.

**11 attack classes.** Direct tenant-boundary fetch, organic entity-bleed RAG
(the flagship), semantic-cache contamination, KV-cache timing side channel,
embedding inversion, MCP confused-deputy + token passthrough, persistent memory
contamination, LoRA cross-tenant influence, IKEA benign extraction, RAG
poisoning, GDPR Article 17 erasure verification.

**Tamper-evident evidence.** Every run is canonicalized, hashed, RFC 3161
timestamped, Sigstore Rekor logged, wrapped in an in-toto attestation envelope,
and rendered to an auditor PDF. `sectum-ai verify` validates the chain
end-to-end, with no Sectum AI installation required.

## Use it for

| | |
|---|---|
| **Vendor security questionnaires** | Drop a tamper-evident AI tenant-isolation attestation into your data room. Unblock the enterprise prospect whose security team is asking how you isolate tenant data in your AI features. |
| **SOC 2 audit evidence** | Plug a control-mapped AI isolation attestation into your Type II audit — CC6.1, CC6.6, CC6.7 evidence the auditor accepts as testing coverage of your AI features. |
| **Pre-launch verification** | Run the probe suite against a new AI feature before launch. Catch the cross-tenant retrieval pivot, the cache contamination, the MCP confused-deputy bug while there's still time to fix it. |
| **CI regression baselines** | Save a baseline, re-run on every prompt / embedding / model change. Sectum AI flags the regression when a stronger embedding model accidentally raises your Retrieval-Pivot Rate. |
| **GDPR Article 17 erasure** | A churned tenant invoked their right to be forgotten. Prove their data has actually left every AI surface, in a DPO-ready cryptographically-timestamped attestation pack. |
| **EU AI Act Article 15** | Documented cybersecurity and robustness measurements for high-risk AI systems. Tamper-evident, control-mapped, and independently verifiable. |

## Scope

Sectum AI verifies and attests; it does not remediate findings or provide
runtime protection. See the [threat model](docs/threat-model.md) for the trust
boundaries and non-goals.

Adjacent tools — LLM red-team frameworks, runtime guardrails, GRC platforms,
DSR / DSPM — test model behavior, govern how staff use AI, or track controls on
a dashboard. None of them provision real tenants to measure cross-tenant
leakage, and none produce evidence you can verify without trusting the vendor.
Sectum AI sits alongside those tools rather than replacing them.

## The evidence layer is fully open source

The marker substrate, attack catalog, adapters, evidence chain, and the
independent `sectum-ai verify` are Apache-2.0 — anyone can reproduce a run and
verify a Sectum AI evidence pack without the project. That independence is what
makes the attestation worth anything. See
[ADR-0002](docs/adr/0002-evidence-layer-oss-boundary.md).

## Open Sectum vs Sectum Cloud

| | **Open Sectum** (this repo) | **Sectum Cloud** (private) |
|---|---|---|
| License | Apache-2.0 | Commercial |
| Marker substrate, attack catalog, adapters | ✓ | ✓ |
| Evidence chain + independent `sectum-ai verify` | ✓ | ✓ |
| `sectum-ai` CLI (`init` / `seed` / `probe` / `report` / `pack` / `verify` / `erasure` / `score` / `baseline` / `calibrate` / `diff` / `adapters`) | ✓ | ✓ |
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
| `sectum-ai` | `sectum_ai` (+ `sectum_ai.cli`) | Core substrate runner and the `sectum-ai` CLI |
| `sectum-ai-spec` | `sectum_ai.spec` | Pydantic data models and JSON Schema |
| `sectum-ai-probes` | `sectum_ai.probes` | The data-isolation attack catalog |
| `sectum-ai-adapters` | `sectum_ai.adapters` | Connectors to real systems |
| `sectum-ai-evidence` | `sectum_ai.evidence` | Evidence chain, verification, audit packs |

## Quickstart

Install from PyPI ([`pip`](https://pip.pypa.io/) or [`uv`](https://docs.astral.sh/uv/)):

```sh
pip install sectum-ai          # or: uv pip install sectum-ai  (or: uv tool install sectum-ai)
```

Then drive the `sectum-ai` CLI:

```sh
sectum-ai init                 # scaffold a sectum-ai.yaml (optional)
sectum-ai seed   --workdir .sectum-ai
sectum-ai probe  --workdir .sectum-ai
sectum-ai report --workdir .sectum-ai
sectum-ai verify .sectum-ai/evidence.json --allow-unanchored
```

Optional backends (live vector stores, model/agent frameworks) are extras, e.g.
`pip install "sectum-ai-adapters[qdrant]"` — see [docs/adapters.md](docs/adapters.md).

### Run the flagship demo

The bundled examples live in the repo, so clone it to run the organic
entity-bleed Retrieval Pivot end to end ([`uv`](https://docs.astral.sh/uv/) is the
only prerequisite):

```sh
git clone https://github.com/sectum-ai/sectum-ai
cd sectum-ai
./examples/retrieval-pivot/run.sh
```

It seeds a four-tenant marker substrate, probes a deliberately leaky shared
vector index, assembles a tamper-evident evidence pack, and independently
verifies it. See [`examples/`](examples/) for this and the GDPR Article 17
erasure-attestation walkthrough.

For richer configuration (live vector store, real embedder/judge, Rekor
signing, manifest-at-rest), copy
[`sectum-ai.yaml.example`](sectum-ai.yaml.example) to `sectum-ai.yaml` and pass
`--config sectum-ai.yaml` to each command.

### Run it in CI

A GitHub Action seeds, probes, and fails the build on a confirmed cross-tenant
leak (and can emit SARIF for the Security tab):

```yaml
- uses: sectum-ai/sectum-ai@main   # pin to a release tag or SHA for production
  with:
    config: sectum-ai.yaml
```

See [docs/github-action.md](docs/github-action.md) for inputs, outputs, and the
SARIF integration.

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

- **Start an engagement:** [sectum.ai](https://sectum.ai) — or reach us directly at
  [security@sectum.ai](mailto:security@sectum.ai).
- **Audit firms and compliance partners:** white-label Sectum AI's isolation
  evidence into your SOC 2, ISO 27001, and GDPR engagements. We produce the
  signed, independently-verifiable pack; you deliver it under your brand.
- **Sponsor on GitHub:** [github.com/sponsors/sectum-ai](https://github.com/sponsors/sectum-ai) keeps the OSS evidence layer fully open.

## License

Apache-2.0 — see [LICENSE](LICENSE).
