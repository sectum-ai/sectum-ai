# Glossary

The vocabulary Sectum AI uses across its CLI, evidence packs, attack catalog,
and configuration. Each term is precise and is used consistently in the source
code, the CLI output, and the auditor-facing documents.

## Tenant
An isolated customer within a multi-tenant AI system. Sectum AI provisions
*synthetic* tenants for a verification run (the default scenario uses
Acme Robotics, Globex, Initech, Hooli) so that detection has zero ambiguity:
every observation can be traced back to the tenant whose canary surfaced it.

## Principal
The isolation boundary, generalized: either a tenant or a user within a
tenant ([ADR-0006](adr/0006-principal-isolation-model.md)). The detection
pipeline flags a marker owned by one principal surfacing in another
principal's session, so the same probes verify both tenant-level and
user-level isolation depending on how the substrate is seeded.

## Marker / canary
A planted, ground-truth-known artifact whose appearance in the wrong
principal's session proves a leak. Three types
([§6.3](https://github.com/sectum-ai/sectum-ai/blob/main/CLAUDE.md)):

- **HARD_CANARY** — high-entropy unique token (`SECTUM-CANARY-{base32(16 bytes)}`).
  Exact substring or regex match; zero false positives.
- **ENTITY_CANARY** — a unique synthetic entity (fabricated person,
  codename, account number) owned by exactly one principal. Tested by
  semantic similarity plus exact match.
- **SECRET_CANARY** — a branded high-entropy secret token
  (`SECTUM-SECRET-<base32>`). Exact substring or regex match, like HARD_CANARY.

## Ground-truth manifest
The authoritative record of which marker belongs to which principal:
`{marker_id, marker_type, owner_principal, plaintext, planted_locations[]}`.
Hashed into the evidence chain so the test conditions are provable after the
fact. Optionally encrypted at rest (see the security note below).

## Retrieval-Pivot Rate (RPR)
The fraction of benign cross-tenant queries that surfaced a foreign
marker — the headline metric for [Class 2](attack-catalog/class-02-rag-entity-bleed.md),
the flagship probe. Reproduces the *Retrieval Pivot Attacks in Hybrid RAG*
result ([arXiv:2602.08668](https://arxiv.org/abs/2602.08668); 95.4% of benign
queries leaked across tenants on a shared vector index).

## Surface
A place tenant data can live or leak. The catalog covers: API, vector DB,
RAG pipeline, prompt/completion logs, semantic cache, KV cache, agent
memory, MCP tool calls, fine-tunes / adapters, eval sets, backups, search
indexes, tracing pipelines.

## Probe
A pluggable attack class implementing the `Probe` protocol (a deterministic
`plan` method and a `detect` method that emits `Finding` objects). Each probe
declares its OWASP / ATLAS / NIST mappings and the surfaces it touches.
See the [attack catalog overview](attack-catalog/index.md).

## Finding
A single recorded leak: `{finding_id, probe_id, severity, confidence,
status, owner_principal, observed_in_principal, marker_id, evidence_span,
surface, owasp_llm, atlas[], nist[], remediation_pointer}`. **Confirmed**
findings are manifest-traceable (zero false positives); **unverified**
findings come from the semantic or judge step and are not tied to a
manifest marker.

## Evidence pack
The deliverable of a Sectum AI run: a tamper-evident bundle that an auditor
or DPO accepts. Contains the canonicalized run, the hashed ground-truth
manifest, an RFC 3161 timestamp token, a Sigstore Rekor inclusion proof
(when enabled), control mappings (SOC 2 / ISO 27001 / GDPR / EU AI Act /
HIPAA / NIST AI RMF / OWASP), a machine-readable `evidence.json`, and a
human-readable [audit-pack PDF](https://github.com/sectum-ai/sectum-ai/tree/main/docs/samples). The pack is
independently verifiable by `sectum verify`.

## BYOC (bring-your-own-cloud)
A deployment mode where the `sectum` CLI runs inside the customer's
environment and only the markers, the configuration, and the signed
evidence leave the box. The alternative is *hosted* mode, where Sectum
runs the synthetic tenants against the customer's reachable endpoints.

## Wedge
The standalone GDPR Article 17 "right-to-erasure" attestation SKU
([Class 11](attack-catalog/class-11-erasure.md)). Verifies that a churned
tenant's data has actually left every configured AI surface
post-erasure, itemizing residual markers per surface. Sold as a one-time
DPO-facing engagement.

## Related references

- The full [attack catalog](attack-catalog/index.md) (every probe, every
  surface, every mapped control).
- The [evidence chain](evidence-chain.md) (canonicalization, timestamping,
  Rekor, verify).
- The [compliance mappings](compliance-mappings.md) (per-framework control
  coverage).
- The [threat model](threat-model.md) (trust boundaries, non-goals,
  manifest-at-rest handling).
- Sample [evidence packs](https://github.com/sectum-ai/sectum-ai/tree/main/docs/samples)
  (real PDFs and attestation envelopes from the runnable examples).
