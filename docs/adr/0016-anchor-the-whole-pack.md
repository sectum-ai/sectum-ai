# ADR-0016: Anchor the whole evidence pack, not just the run

- Status: Accepted
- Date: 2026-05-29
- Extends [ADR-0007](0007-canonical-hashing-serializes-every-field.md) (canonical hashing)

## Context

The evidence chain originally anchored the **run digest** (`run_digest`, the
SHA-256 of the run record's canonical form). The TSA token and Rekor proof bound
only that digest.

But an `EvidencePack` carries more attested content *outside* the run record:

- `manifest_hash` — binds the test conditions (which marker belonged to which tenant);
- `control_mappings` — the auditor-facing compliance claims, rendered verbatim into the PDF;
- `pdf_ref` — the pointer to the human-readable audit pack a DPO actually reads;
- `rekor_proof` / the *intent* to anchor in a transparency log.

Because none of these were in the anchored digest, a hardening review found they
could be mutated without detection: forging `control_mappings` to read "fully
isolated, zero leakage", repointing `pdf_ref` at an attacker-controlled file, or
**stripping `rekor_proof`** to silently skip the transparency-log check — each
left `sectum verify` reporting PASS. That contradicts the product's core promise
(the engineering spec §8.1): mutating the pack must make verification fail.

Separately, a `local-dev` JSON timestamp token is unsigned. The verifier treated
any JSON token whose `digest` matched as a passing timestamp, so a forged token
could name a real authority (impersonating, e.g., FreeTSA) with an attacker-chosen
time and still pass.

## Decision

**The anchors bind the whole attested pack.** A new `attested_digest(pack)` is the
SHA-256 of the canonical form of `{run_result, manifest_hash, control_mappings,
pdf_ref, anchored_in_log}`. `build_evidence_pack` timestamps and Rekor-records
*that* digest; `sectum verify` recomputes it from the pack's own fields and checks
it against the timestamp token and any Rekor proof. Editing any bound field
changes the digest and fails verification.

- **`anchored_in_log: bool`** is a new `EvidencePack` field, set at build time when
  a transparency log is used and **bound into the digest**. The verifier requires a
  valid Rekor inclusion proof whenever the flag is set, so stripping the proof to
  skip the check (a downgrade) fails — and flipping the flag to dodge that
  requirement changes the digest, which the timestamp token then rejects.
- **`run_digest` is retained** for the in-toto attestation *subject* (it identifies
  the run) and the human-readable PDF. It is no longer the cryptographic anchor.
- **Local-dev timestamp tokens are reported as *unanchored*.** A `local-dev` JSON
  token still binds the digest (so tampering is caught) but its check detail states
  it is not an independent RFC 3161 / Rekor anchor. A JSON token naming **any other**
  TSA is refused, since a real TSA returns a signed *binary* token, never JSON —
  closing the impersonation vector.

This is a schema change: `SCHEMA_VERSION` is bumped `0.1.0` → `0.2.0`, and packs
produced under the old scheme do not verify under the new verifier (acceptable —
v0.1.0 is not yet published and no packs are in the wild).

The canonical form itself is also hardened (reject non-finite floats, normalize
timestamps to UTC) — see the update note in
[ADR-0007](0007-canonical-hashing-serializes-every-field.md).

## Consequences

- Tamper-evidence now covers the full auditor-facing surface, not just the run record.
- Transparency-log anchoring cannot be silently downgraded.
- `sectum verify <pack>` without the original manifest confirms integrity and internal
  consistency but not marker-ownership; the CLI now says so explicitly (re-run with
  the manifest to bind ownership).
- `tests/invariants/test_evidence_roundtrip.py` gained a tamper-each-field suite
  (control mappings, pdf ref, manifest hash, Rekor strip, flag flip, forged local token).
- `pdf_ref` is bound into the digest and the CLI now populates it: `sectum report`
  and `sectum erasure` render the audit PDF first, record `pdf_ref` as the SHA-256 of
  its bytes, and `sectum verify` re-hashes the sibling PDF against it (failing on a
  mismatch). So a swapped audit PDF and a repointed reference both fail verification
  in the CLI flow, alongside the control mappings, manifest hash, and transparency-log
  flag. (Wired in the ADR-0016 follow-on, PR #81.)
