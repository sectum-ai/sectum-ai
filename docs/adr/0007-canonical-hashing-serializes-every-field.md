# ADR-0007 - Canonical hashing serializes every field (no exclude_none / exclude_defaults)

## Status

Accepted (2026-05-20).

## Context

`sectum.spec.hashing.to_canonical_json` serializes a model with
`model_dump(mode="json")` — every field, including optionals left `None`
(emitted as `null`) — then sorts keys and SHA-256s the bytes. This
`canonical_hash` underpins `scenario_hash`, `manifest_hash`, the run digest, the
RFC 3161 TSA token, the Sigstore Rekor entry, and `sectum verify`.

Because no field is omitted, adding an optional field shifts the digest of every
existing instance. ADR-0006 added `Marker.owner_user_id` (default `None`) and
`SyntheticTenantSpec.users` (default `()`), which moved the default scenario's
`scenario_hash` once (`802d1643…` → `083169e0…`). That raises the question:
should `to_canonical_json` adopt `exclude_none=True` (or `exclude_defaults=True`)
so additive optional fields never perturb the digest?

## Decision

Keep total serialization. **Reject `exclude_none` and `exclude_defaults`.**

## Consequences

- **Changing the rule would break every previously issued pack.** `verify_pack`
  recomputes `run_digest = canonical_hash(pack.run_result)` from the model and
  matches it against the timestamp token issued at build time. Any change to
  `to_canonical_json` changes that recomputed digest, so every prior pack would
  fail verification. Adopting exclusion is a one-time break of the verification
  contract — strictly worse than the harmless additive-field shift it avoids,
  and it pays that same one-time cost anyway (all current `null` fields would
  drop out at once).
- **A total digest is unambiguous.** It covers the complete object state, and
  `null` stays distinct from absent. An auditor can rely on "the digest covers
  everything serialized," with no silent-omission caveat. `exclude_none`
  collapses `null` and absent into one form — ambiguity we will not add to a
  tamper-evidence primitive. `exclude_defaults` is worse still: it couples the
  digest to mutable default constants, so changing a field's default would
  silently change what is hashed.
- **Cross-version hash stability is a non-goal.** Aggregate models carry
  `schema_version`; a pack is verified by code at its schema version, and
  cross-version digest differences are expected and signalled by it. Forward
  compatibility comes from `schema_version`, not from omitting fields.
- **The cost avoided is negligible.** Optional-field additions are rare, gated
  by a `schema_version` bump, and break nothing: packs are self-contained and
  the reproducibility invariant (same seed and code → identical manifest) is
  unaffected. The ADR-0006 shift was absorbed with zero breakage — no persisted
  packs, and example outputs regenerate on each run.
- The decision is locked by a test asserting an optional `None` field is
  serialized as `null` and participates in the digest; a future move to
  `exclude_none` fails it and forces a conscious re-decision via a new ADR.

Verifying a pack across schema versions in production — re-serializing old pack
JSON through evolved models — is a separate concern (pin the verifier to the
pack's `schema_version`, or hash stored canonical bytes rather than
re-serializing) and warrants its own ADR if it arises. Out of scope here.

## Update (2026-05-29): keep the canonical form valid and injective

A hardening sweep added two constraints to `to_canonical_json` so the canonical
form is always valid JSON and maps equal values to equal bytes:

- **No non-finite floats.** `json.dumps` is called with `allow_nan=False`. A
  `NaN`/`Infinity` would serialize as a bare JavaScript literal that is not valid
  JSON (RFC 8259) — a strict third-party parser (Go, Rust, browsers) could not
  reproduce the digest — and every `NaN` collapses to the same token, so distinct
  content could collide. A non-finite metric is now refused at hash time with a
  clear `ValueError`.
- **Timestamps normalized to UTC.** Datetime fields use a `UtcDateTime`
  annotation whose serializer emits the instant in UTC ISO-8601, so the same
  instant hashes identically regardless of the producing machine's local timezone
  (`12:00Z` and `14:00+02:00` are one digest), preserving the byte-for-byte
  reproducibility contract (§6.5).

The scope of *what* the evidence anchors bind (the whole pack, not just the run)
is covered in [ADR-0016](0016-anchor-the-whole-pack.md).
