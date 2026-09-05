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
key-value store. A cache that keys per tenant passes here whatever its similarity
threshold does.

## Detection

A foreign canary in the fetched cache value is a confirmed leak. The probe
verifies cache-key tenancy: whether the cache scopes its key space by tenant.

## Status

Implemented in Phase 3.
