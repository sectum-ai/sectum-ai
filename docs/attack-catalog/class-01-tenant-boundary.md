# Class 1 — Direct tenant boundary fetch

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0024 · **NIST:** MEASURE 2.7 · **Surface:** vector DB · **Probe id:** `tenant-boundary-fetch`

## Goal

Verify negative authorization: from one tenant's session, a direct fetch of
another tenant's document by id must be denied.

## Method

For every hard-canary document in the manifest, the probe issues a fetch-by-id
from each other tenant's session — a BOLA-style direct object lookup, distinct
from the similarity query used by Class 2.

## Detection

A foreign hard canary in the fetched content is a confirmed cross-tenant leak.
On a tenant-isolated store the fetch returns nothing; on a shared index it
returns the foreign document.

## Status

Implemented in Phase 3. This is the table-stakes probe — its value is
manifest-grounded, zero-false-positive detection.
