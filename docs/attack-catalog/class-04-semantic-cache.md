# Class 4 — Semantic-cache contamination

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0057 · **NIST:** MEASURE 2.7 · **Surface:** semantic cache · **Probe id:** `semantic-cache-contamination`

## Goal

Verify that a semantic or application cache never serves one tenant's cached
answer to another tenant.

## Method

A semantic cache collapses near-identical queries onto a single stored entry.
What the probe measures is the tenancy of the **cache key**, not that collapse:
it primes one entry as one tenant — with an answer carrying that tenant's hard
canary — then reads the *same* key from every other tenant's session. Similarity
matching is assumed, not modelled, and the shipped Redis backend is a plain
key-value store. Tenant-scoping alone is not the whole test: where the adapter
carries the caller's user (the built-in fake always; live Redis only with
`user_scoped: true`), the probe also reads the identical key as a sibling user,
and a cache keyed by tenant alone leaves a confirmed cross-user finding. Where
the adapter cannot carry a user, those steps are dropped rather than failed, the
run records `user_steps_dropped`, and `diff` reports `[BOUNDARY LOST]` — a pass
that says the user boundary was not tested, not that it held.

## Detection

A foreign canary in the fetched cache value is a confirmed leak. The probe
verifies cache-key tenancy: whether the cache scopes its key space by tenant.

## Status

Implemented in Phase 3.
