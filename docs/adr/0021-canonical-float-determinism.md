# ADR-0021: canonical hashing relies on deterministic float repr, not rounding

- Status: Accepted
- Date: 2026-06-03
- Deciders: Dmitry Maranik

## Context

ADR-0007 established that the canonical hash serializes every field. The evidence
chain (the engineering spec, section 8.2) adds: "deterministic JSON (sorted keys,
no floats where avoidable)." A reproducibility question follows: when a metric
*is* a float — a Retrieval-Pivot Rate, a Class 5 effect size, a confidence — is
its serialized form stable enough that a third party recomputes the same digest?

A tempting answer is to round finite floats to a fixed precision before hashing,
on the theory that floating-point noise in the last unit-in-the-last-place could
otherwise make two "equal" runs hash differently.

That theory does not hold for the runtime, and the cure is worse than the
disease:

- **`json.dumps` already serializes a finite float with CPython's shortest
  round-tripping `repr`** (David Gay's algorithm, default since CPython 3.1). The
  same `float` value produces the same string on every CPython platform, so the
  same logical run already hashes identically. There is no cross-machine
  float-repr drift to fix.
- **Rounding is lossy and can mask regressions.** Collapsing distinct values to a
  shared rounded token would make two genuinely different metric results hash the
  same — the exact failure a *verification* product must not have. For a tool
  whose job is to detect change, a hash that hides change is a defect.

## Decision

Do **not** round floats in the canonical form. Keep `canonical_hash` /
`to_canonical_json` as they are: sorted keys, compact separators, finite floats
via the standard deterministic `repr`, and an explicit refusal of non-finite
floats (NaN / ±Infinity), which have no valid, injective JSON form (RFC 8259) and
would otherwise collapse to a single non-reproducible token.

`SCHEMA_VERSION` is **not** bumped and no committed artifact is regenerated: the
canonical form is unchanged. This ADR records the analysis so the rounding idea
is not revisited. The contract is pinned by `tests/unit/test_hashing.py`
(determinism across constructions, distinct values stay distinct, non-finite and
non-JSON values are refused).

## Consequences

- The reproducibility contract for floats is now explicit and test-pinned, not
  incidental.
- A future move to a non-CPython runtime, or any change that introduces a
  different float emitter, must re-validate this assumption (the determinism test
  guards it) — and only *then* would a versioned canonicalization change (and the
  attendant artifact regeneration) be warranted.
- This refines, and does not supersede, ADR-0007: every field is still hashed;
  this only documents how the float fields are treated.
