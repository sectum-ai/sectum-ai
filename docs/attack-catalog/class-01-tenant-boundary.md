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

A foreign hard canary in the fetched content is a confirmed cross-tenant leak;
on a shared index the fetch returns the foreign document and the canary surfaces.

A tenant-isolated store instead returns **200-empty**, which is *not* a proven
deny — the backend may have silently swallowed the request rather than enforcing
authorization. The probe does not treat that as a clean pass: it records an
**unverified, informational** finding on every empty cross-principal fetch,
flagging that negative authorization is unproven. Distinguishing an enforced
`403` from a 200-empty needs an adapter that can report the refusal — the
`fetch` contract returns a hit or nothing, so `AccessOutcome.DENIED` is reserved
for it and is produced by no adapter today. These findings are excluded from the
confirmed-leak headline and carry a remediation pointer to return an explicit
authorization error.

## Status

Implemented in Phase 3. This is the table-stakes probe — its value is
manifest-grounded detection: every confirmation ties back to a planted marker.
