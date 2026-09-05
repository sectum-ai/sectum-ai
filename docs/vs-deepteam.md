# Sectum AI vs. DeepTeam

[DeepTeam](https://www.trydeepteam.com/docs/red-teaming-vulnerabilities-cross-context-retrieval)
(by Confident AI) is an open-source LLM red-teaming framework. Among its
vulnerability checks is `CrossContextRetrieval(types=["tenant", "user"])`, which
sends an attack prompt and uses an LLM judge to score, pass/fail, whether the
response revealed context from another tenant or user.

DeepTeam and Sectum AI are **different categories of tool**, not competing
implementations of the same one. This page states the difference precisely so
you can choose correctly. It is not a criticism of DeepTeam — a single-prompt
LLM-as-judge check is the right shape for a fast red-team eval loop. It is a
different thing from infrastructure verification.

## The difference in one line

DeepTeam asks a model *"did this one answer leak?"* and judges the text. Sectum
AI provisions a multi-tenant substrate, runs a catalog of probes across the
surfaces your adapters reach, and produces — with ground-truth markers and a
tamper-evident, control-mapped evidence pack — evidence of *which cross-tenant
leaks it found, and which checks it was able to perform*. The surfaces it could
not reach are recorded `NOT_COVERED`, never as a pass.

## Side by side

| Dimension | DeepTeam `CrossContextRetrieval` | Sectum AI |
|---|---|---|
| **Category** | LLM red-teaming vulnerability check | Multi-tenant AI *verification* |
| **Method** | A single adversarial prompt per attempt | A marker substrate: synthetic tenants (and users) seeded with cryptographic canaries, probed from each session |
| **Detection** | LLM-as-judge, binary score | Manifest-grounded exact → semantic → judge pipeline; every confirmed finding ties back to a planted marker, and a candidate that cannot be is recorded as *unverified* rather than confirmed (**manifest-grounded by construction**) |
| **Boundary** | Tenant or user, per the prompt | Principal boundary — tenant *and* user within a tenant — verified default-deny ([ADR-0006](adr/0006-principal-isolation-model.md)) |
| **Surfaces** | The model response | Vector DB, RAG, semantic & KV caches, agent memory, MCP tool calls, fine-tunes/adapters, tracing — across the catalog |
| **Catalog** | One retrieval check | 12 probe classes incl. side-channel (KV-cache timing), embedding inversion, MCP confused-deputy/token-passthrough, persistent-memory contamination, LoRA bleed, multi-modal RAG entity-bleed, and the GDPR Art. 17 erasure wedge |
| **Output** | A score in an eval report | A signed, timestamped (RFC 3161 + Sigstore Rekor), in-toto-wrapped evidence pack with control mappings (SOC 2, ISO 27001, ISO/IEC 42001, GDPR, CCPA/CPRA, EU AI Act, HIPAA, NIST AI RMF, OWASP LLM08), independently checkable via `sectum-ai verify` |
| **Reproducibility** | Prompt- and judge-dependent | Byte-identical from a seed ([ADR-0003](adr/0003-deterministic-substrate.md)); regression baselines flag drift |

## Why the substrate matters

The published evidence Sectum AI is built on — the Retrieval Pivot result
(95.4% of *benign* queries leaked cross-tenant via shared organic entities) and
the Silent Leaks / IKEA result (high-efficiency extraction with no prompt
injection) — shows that the dangerous leaks are **not** the ones a single
adversarial prompt provokes. They are organic: a benign question about a shared
person or vendor that retrieves a foreign tenant's document. Reproducing that
needs a populated multi-tenant corpus with known ground truth, not one prompt.
The substrate is the moat; a binary judge over one response cannot measure a
Retrieval-Pivot Rate.

## Why manifest-grounded detection matters

An LLM judge scoring free text will, at scale, both miss leaks and invent them.
Sectum AI's headline count is every-finding-traceable-to-a-marker: a confirmed
finding is an exact canary hit or a judge verdict on a candidate that is already
tied to a specific planted entity. Text that contains no manifest marker can
never become a confirmed finding (a tested invariant). That property is what
makes the output defensible to an auditor.

## When to use which

- **DeepTeam** — you want a fast, in-loop red-team signal that a prompt can pull
  cross-context data, alongside other LLM vulnerability checks. Lightweight,
  developer-facing, runs in an eval suite.
- **Sectum AI** — you need to *verify and attest* multi-tenant isolation across
  an AI system's surfaces and hand a DPO, CISO, or auditor evidence they accept:
  the erasure attestation, the SOC 2 tenant-isolation pack, or continuous
  regression-tracked verification.

They compose: run DeepTeam in CI for fast feedback; run Sectum AI to produce the
attestation.
