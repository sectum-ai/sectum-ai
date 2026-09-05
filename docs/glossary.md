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
user-level isolation depending on how the substrate is seeded — and, for the
user boundary, on whether the adapter carries the user to its backend (see
[the threat model](threat-model.md)).

## Marker / canary
A planted, ground-truth-known artifact whose appearance in the wrong
principal's session proves a leak. Three types
(see [the marker substrate](substrate.md)):

- **HARD_CANARY** — high-entropy unique token (`SECTUM-CANARY-{base32(16 bytes)}`).
  Exact substring match (case-, width-, and zero-width-insensitive); zero false positives.
- **ENTITY_CANARY** — a unique synthetic project codename
  (`Project <codename><base32>-<serial>`) owned by exactly one principal.
  Tested by semantic similarity plus exact match.
- **SECRET_CANARY** — a fake but plausibly shaped secret: an OpenAI-style `sk-`
  key, an AWS `AKIA` access-key id, or a non-issuable `9xx` US SSN. Matched by
  exact substring **plus** a credential-format detector (the shape is recovered
  even from surrounding bytes), and redacted in the finding's evidence span so a
  pack never reproduces the credential verbatim. Tests PII/secret surfacing and
  redaction.

## Ground-truth manifest
The authoritative record of which marker belongs to which principal:
`{marker_id, marker_type, owner_tenant_id, owner_user_id?, plaintext, embedding_ref?, planted_locations[]}`.
Hashed into the evidence chain so the test conditions are provable after the
fact. Optionally encrypted at rest (see the security note below).

## Retrieval-Pivot Rate (RPR)
The fraction of benign cross-tenant queries that surfaced a foreign
marker — the headline metric for [Class 2](attack-catalog/class-02-rag-entity-bleed.md),
the flagship probe. Reproduces the *Retrieval Pivot Attacks in Hybrid RAG*
result ([arXiv:2602.08668](https://arxiv.org/abs/2602.08668); 95.4% of benign
queries leaked across tenants on a shared vector index). Its denominator pools
both Class 2 probes' steps, and on a run with **any** live surface only the live
surfaces' steps are pooled — a leaking fake beside a clean live backend is not
the configured stack's rate.

## Surface
A place tenant data can live or leak. The catalog covers: API, vector DB,
RAG pipeline, semantic cache, KV cache, agent memory, MCP tool calls, agent
frameworks, fine-tunes / adapters, eval sets, backups, search indexes, tracing
pipelines. (`prompt_logs` exists in the `Surface` enum but no probe emits it;
logs are reached through the tracing surface.)

## Probe
A pluggable attack class implementing the `Probe` protocol (a deterministic
`plan` method and a `detect` method that emits `Finding` objects). Each probe
declares its OWASP / ATLAS / NIST mappings and the surfaces it touches.
See the [attack catalog overview](attack-catalog/index.md).

## Finding
A single recorded leak: `{finding_id, probe_id, severity, confidence,
status, owner_tenant_id, owner_user_id?, observed_in_tenant_id,
observed_in_user_id?, marker_id, evidence_span, surface, owasp_llm,
owasp_secondary[], atlas[], nist[], remediation_pointer}`. **Confirmed**
findings trace back to a specific manifest marker; **unverified** findings
are candidates the detector could not tie to one, recorded as evidence
rather than asserted as leaks. The distinction is traceability, not which
detection step fired — a semantic match that traces to a marker confirms,
and an exact match is decided by the observation alone.

## Evidence pack
The deliverable of a Sectum AI run: a tamper-evident bundle that an auditor
or DPO accepts. Contains the canonicalized run, the hashed ground-truth
manifest, a timestamp token (the reproducible local-dev token by default; an
RFC 3161 token when a TSA is configured), a Sigstore Rekor inclusion proof
(when enabled), control mappings (SOC 2 / ISO 27001 / ISO/IEC 42001 / GDPR /
CCPA/CPRA / EU AI Act / HIPAA / NIST AI RMF / OWASP) — each earned only where a
live surface was exercised, so an all-synthetic run carries none — a
machine-readable
`evidence.json`, and a
human-readable [audit-pack PDF](https://github.com/sectum-ai/sectum-ai/tree/main/docs/samples). The pack is
independently verifiable by `sectum-ai verify`.

## BYOC (bring-your-own-cloud)
A deployment mode where the `sectum-ai` CLI runs inside the customer's
environment and only the markers, the configuration, the judge-cited
evidence spans (including a judge rationale, which may restate observed content),
and the timestamped evidence pack leave the box. The alternative is *hosted* mode, where Sectum
runs the synthetic tenants against the customer's reachable endpoints.

## Wedge
The standalone GDPR Article 17 "right-to-erasure" attestation SKU
([Class 11](attack-catalog/class-11-erasure.md)). Checks that none of a churned
tenant's markers is still retrievable through the scanned AI surfaces
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
