# Class 4 — Semantic-cache contamination

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0057 · **NIST:** MEASURE 2.7 · **Surface:** semantic cache · **Probe id:** `semantic-cache-contamination`

## Goal

Verify that a semantic or application cache never serves one tenant's cached
answer to another tenant.

## Method

A semantic cache collapses near-identical queries onto a single stored entry.
The probe primes such an entry as one tenant — with an answer carrying that
tenant's hard canary — then reads it from every other tenant's session.

## Detection

A foreign canary in the fetched cache value is a confirmed leak. The probe
verifies cache-key tenancy: whether the cache scopes its key space by tenant.

## Status

Implemented in Phase 3.
