# Spec: A3 — DSR Connector

- Status: **Phase 0 shipped (OSS); Phases 1+ on hold** — the Cloud layers are gated
  on the first Cloud customer. Phase 0 (`sectum-ai erasure --subject`, by-id
  verification for the vector store + semantic cache) shipped 2026-06-29.
- Owner: Dmitry Maranik
- Last updated: 2026-06-29
- Related: [ADR internal/0001 — DSR erasure-verification model](../adr/0001-dsr-erasure-verification-model.md),
  [docs/adr/0002 — evidence-layer OSS boundary](../../docs/adr/0002-evidence-layer-oss-boundary.md),
  E1 control mappings (ISO/IEC 42001, CCPA/CPRA), A1 erasure `--scope`

## Summary

A3 turns Sectum's **Class 11 erasure verification** into the *proof-of-completion*
step of a real **Data Subject Request (DSR)** workflow. When an organisation
receives a "delete my data" request under GDPR Art. 17 or CCPA/CPRA §1798.105,
A3 verifies the deletion actually propagated across the organisation's AI
substrate and returns a **signed erasure attestation** that closes the DSR with
cryptographic evidence instead of a checkbox.

## Problem

A privacy team handling a right-to-erasure request deletes the subject's records
and *asserts* completion. They have no way to prove the subject's data is gone
from the **derived** AI surfaces — embeddings in the vector store, semantic-cache
entries, fine-tune / adapter memorisation, search indices, agent memory, backups,
traces. Regulators and enterprise buyers increasingly expect *demonstrable*
erasure, not a delete-API `200 OK`.

This is exactly the surface set Sectum's Class 11 already enumerates, each with a
tri-state `CoverageVerdict` (`ERASED` / `RESIDUAL` / `NOT_COVERED`) and a signed
evidence pack. The capability exists; what's missing is the bridge from a *real
subject* inside a *real DSR process* to that capability.

## Users

- **Primary buyer / user:** privacy or compliance lead (DPO) at an organisation
  running multi-tenant or user-data-trained AI.
- **Operator:** the engineer who configures which substrate surfaces map to a
  subject and wires the DSR system to A3.
- **Indirect beneficiary:** the data subject (gets a real, verifiable deletion)
  and the auditor (gets an attestation chain).

The wedge is Sectum's standing one: *verify the deletion actually happened — don't
trust the pipeline's or vendor's claim.*

## Goals

1. Receive a DSR completion signal and verify erasure across the configured AI
   surfaces for that specific subject.
2. Emit a per-subject, Sigstore-signed erasure attestation referencing the DSR id
   and a per-surface verdict, and return it into the DSR record.
3. Be honest about coverage: every `NOT_COVERED` surface is explicit; the
   attestation never implies more than it verified.

## Non-goals

- A3 does **not** perform the deletion — the organisation's own systems do; A3
  verifies and attests.
- A3 is **not** a DSR intake portal — it connects to the existing one
  (OneTrust / Transcend / custom).
- A3 does **not** give legal advice on DSR compliance.

## Flow

1. A DSR is filed in the organisation's intake system.
2. A3 receives the event (subject identifier + scope) via connector or webhook.
3. The organisation's systems perform the deletion (outside A3).
4. A3 runs erasure verification scoped to that subject across the configured
   surfaces.
5. A3 emits a per-subject erasure attestation (DSSE / in-toto, Sigstore-signed) —
   DSR id, subject id, per-surface verdict, timestamp — and posts it back into the
   DSR record.

## Verification model (the central decision)

Class 11 today proves erasure of Sectum's own planted canaries. A real subject has
no canary, so "how do you verify a *real* subject's erasure" is the core fork.
**Decision: hybrid, structural-first** — see
[ADR internal/0001](../adr/0001-dsr-erasure-verification-model.md). In short:

- **MVP = structural (id-keyed):** the organisation supplies the subject's record
  ids per surface; Sectum confirms each is gone by id (the existing Class 11
  scan mechanism, keyed on real ids rather than canaries). Deterministic, PII-light
  (ids only), reuses Class 11 almost as-is.
- **Phase 2 = + content-fingerprint residual probing:** the organisation supplies
  the subject's content (or hashes); Sectum actively queries the vector store /
  cache / model and checks for residual. This is the differentiator — it catches
  derived or forgotten residual the organisation didn't know to enumerate — at the
  cost of (data-minimised) PII handling and probabilistic results.

## OSS vs Cloud boundary

- **Could be OSS (Phase 0):** the id-keyed erasure-verification *primitive* — a
  natural extension of A1's erasure `--scope`. Shippable now, no paying customer
  required, and it de-risks A3.
- **Cloud / paid (A3 proper):** the connector and orchestration — webhook /
  OneTrust / Transcend intake, per-subject job orchestration, data-minimised PII
  handling, attestation-back-into-the-DSR-record, and the hosted audit trail.

## Phasing

| Phase | Where | Scope |
|---|---|---|
| **0** ✅ | OSS | **Shipped.** By-id erasure verify + per-subject attestation; `sectum-ai erasure --subject <manifest.yaml>`. Verifies the vector store (`fetch`) and semantic cache (`get`); other surfaces read `NOT_COVERED` until their adapters gain a by-id accessor. |
| **1** | Cloud (MVP) | Generic inbound **webhook** intake + outbound signed attestation; structural verification; works with any DSR system |
| **2** ◐ | OSS + Cloud | **Content-fingerprint residual probing shipped (OSS, vector store):** `fingerprints` in the manifest → semantic query for the subject's content, hashed in the attestation. Remaining: model-surface fingerprinting; native **OneTrust + Transcend** connectors (Cloud). |
| **3** | Cloud | Scheduled re-attestation, multi-subject batch, dashboard tie-in (overlaps E3) |

## Attestation artifact

Extends the existing signed evidence pack. A per-subject **erasure-completion
attestation** (DSSE / in-toto, Sigstore-signed), reusing the content-agnostic
`build_bundle` / `verify_bundle` path so `sectum-ai verify` works on it. Fields:
DSR id, subject id (or opaque ref), per-surface `CoverageVerdict`, verification
model used, timestamp, and the covered-surface set (so coverage gaps are explicit).
The repo already carries a `residual-data` erasure-attestation sample shape in
`docs/samples/`, so the output format is largely defined.

## Data / PII handling

- **Structural mode:** ids only — no subject content leaves the organisation.
- **Fingerprint mode:** data-minimise — use hashes / fingerprints where possible,
  keep subject content ephemeral, and **never** persist it in the attestation
  (the attestation records verdicts and references, not raw PII).

## Risks

- **Epistemic ("proof of absence"):** a non-hit is evidence, not a guarantee. The
  attestation must read *"verified no residual across the covered surfaces"* and
  surface every `NOT_COVERED` explicitly. Overclaiming "fully erased" is a legal
  and credibility landmine — this ties to the existing erasure-caveat work.
- **Coverage enumeration (structural mode):** only checks what it is told to look
  for; the connector should make the covered-surface set and any unmapped surfaces
  visible to the operator.
- **PII (fingerprint mode):** mitigated by data minimisation above.

## Open questions (resolve at greenlight)

- First native DSR-platform target — OneTrust vs Transcend (webhook-first MVP
  defers this).
- Subject-identity model — single opaque id vs per-surface id map supplied by the
  organisation.
- Whether Phase 0 (OSS id-keyed verify) ships ahead of any Cloud commitment as a
  standalone credibility piece.

## Success metrics

- Time-to-attested-DSR (intake → signed attestation) within an agreed SLA.
- Number of surfaces verified per DSR (coverage breadth).
- Residual-catch rate in fingerprint mode (residual found that the structural pass
  missed) — the differentiator's proof.

## Dependencies

- Class 11 erasure probe + `CoverageVerdict` tri-state (shipped).
- Signed evidence pack / `build_bundle` / `verify_bundle` (shipped).
- E1 control mappings — CCPA/CPRA §1798.105, ISO/IEC 42001 A.7.x (shipped).
- Cloud platform (hosted runner, auth, audit) for Phases 1+ — overlaps E2/E3.
