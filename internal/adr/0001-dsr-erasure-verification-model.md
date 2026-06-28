# ADR internal/0001: A3 DSR-connector erasure-verification model — hybrid, structural-first

- Status: Accepted — build deferred (gated on the first Cloud customer)
- Date: 2026-06-27
- Deciders: Dmitry Maranik
- Scope: internal/planning. Promote to the public `docs/adr/` sequence (next
  number, add to the mkdocs nav) if and when A3 ships.
- Spec: [internal/specs/a3-dsr-connector.md](../specs/a3-dsr-connector.md)

## Context

A3 (the DSR connector) returns a signed *proof of erasure* for a real data
subject as the completion step of a Data Subject Request. Sectum's Class 11
erasure probe already verifies erasure across the AI substrate (vector store,
semantic cache, agent memory, model adapter, search index, backups, traces) and
reports a tri-state `CoverageVerdict` (`ERASED` / `RESIDUAL` / `NOT_COVERED`) with
a signed evidence pack — but it proves erasure of Sectum's own **planted
canaries**. A real data subject has no canary, so A3 needs a way to verify a real
subject's data is gone. Three models were considered:

1. **Structural (id-keyed).** The organisation supplies the subject's record ids
   per surface; Sectum confirms each is gone by id (the Class 11 scan, keyed on
   real ids). Deterministic and PII-light, but only checks what it is told to look
   for — it misses records the organisation failed to enumerate and derived data
   unless explicitly mapped.
2. **Content-fingerprint (residual probe).** The organisation supplies the
   subject's content (or hashes); Sectum actively queries the substrate and checks
   for residual. This catches derived / forgotten residual the organisation didn't
   know about — the true "don't trust the delete" differentiator — but it handles
   subject PII and is probabilistic (a non-hit is evidence, not a guarantee).
3. **Hybrid.** Structural as the deterministic core plus fingerprint residual
   probing on the high-risk surfaces (vector / model). Best evidence, most work.

The forces: A3 must (a) be honest — its whole value is credible proof, so it must
not overclaim; (b) carry Sectum's differentiator — residual probing is what
separates it from a delete-API checkbox; (c) handle PII responsibly; (d) be
tractable enough to ship an MVP.

## Decision

Target the **hybrid** model, but ship the **structural (id-keyed) path first**.

- **MVP** is the structural verification: reuses Class 11 almost as-is (keyed on
  real ids instead of canaries), needs no subject *content* (ids only), and is
  deterministic — a clean, defensible proof for the records the organisation can
  enumerate.
- **Phase 2** adds the content-fingerprint residual probe on the high-risk
  surfaces — the differentiator — with data-minimised PII handling (hashes /
  fingerprints, ephemeral, never persisted in the attestation).

Either way the attestation states *"verified no residual across the covered
surfaces"* and lists every `NOT_COVERED` surface explicitly; it never implies
full erasure beyond what was checked.

## Consequences

- **Positive.** The MVP reuses shipped machinery (Class 11, the signed evidence
  pack), carries no subject content, and is deterministic — fast to build and easy
  to defend. The hybrid endpoint preserves Sectum's differentiator (residual
  probing) for when it matters. Honest-coverage framing reuses the existing
  erasure-caveat work and keeps the legal positioning safe.
- **Negative / accepted.** The structural MVP only verifies enumerated records —
  it cannot, on its own, catch residual the organisation didn't map; the connector
  must make the covered-surface set visible so this limit is explicit. Phase 2
  introduces PII handling, mitigated by data minimisation.
- **Reversible.** If fingerprint probing proves to be the only credible model in
  practice, the phasing can be re-ordered without changing the attestation format
  or the OSS/Cloud boundary; this ADR would be superseded rather than edited.
