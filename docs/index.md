# Sectum AI

**Multi-tenant AI verification.** Sectum AI provisions synthetic tenants on an
AI stack, seeds them with cryptographic canary markers, runs benign and
adversarial probes from each tenant's session, and probes for cross-tenant data
leakage on every surface it can reach — recording exactly which ones it was able
to run, and producing tamper-evident, control-mapped evidence that an auditor
accepts.

## The question Sectum AI answers

Multi-tenant AI systems claim "tenant A's data cannot reach tenant B." That
claim is rarely verified, and published research shows it fails routinely.
Sectum AI verifies it.

## How it works

Sectum AI is built in three layers, each shippable on its own:

| Layer | What it does |
|---|---|
| **Marker substrate** | Deterministic synthetic tenants, templated corpora, and three canary marker types, recorded in a hashed ground-truth manifest. |
| **Attack catalog** | Pluggable probes that run benign and adversarial scenarios across the tenant boundary. |
| **Evidence chain** | Tamper-evident, control-mapped evidence packs that a third party verifies independently. |

## Next

- [Quickstart](quickstart.md) — run the flagship demo end to end.
- [Attack catalog](attack-catalog/index.md) — the implemented probe classes.
- [Evidence chain](evidence-chain.md) — how a run becomes auditor-ready evidence.
- [Threat model](threat-model.md) — boundaries, assets, and explicit non-goals.

Sectum AI is at v0.11.0; every build-plan phase has met its acceptance criteria
(see [`PHASES.md`](https://github.com/sectum-ai/sectum-ai/blob/main/PHASES.md)),
and `CHANGELOG.md` records what each release changed.
