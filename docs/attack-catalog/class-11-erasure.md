# Class 11 — GDPR Article 17 erasure verification

**OWASP:** LLM08:2025 · **Surface:** vector DB · **Probe id:** `gdpr-erasure-verification`

The wedge product: proving a tenant's data has actually left an AI system after
a right-to-erasure request.

## Goal

Confirm that, after an erasure request, none of a target tenant's canary markers
remain observable.

## Method

Pre-erasure, confirm the target tenant's hard canaries are present. Trigger the
erasure flow. Post-erasure, re-scan for any residual marker.

## Detection

A residual marker after erasure is an itemized erasure failure. A surface with
no pre-erasure baseline is reported as inconclusive — never as a vacuous pass.

## Output

`sectum erasure` produces an attestation pack — a PDF for the Data Protection
Officer and a JSON evidence pack — control-mapped to GDPR Articles 17 and 32.

## Status

Implemented in Phase 3 for the vector-store surface. The remaining surfaces of
the "ten hiding places" (logs, caches, backups, derived indexes, and the rest)
follow in later phases. Walkthrough:
[`examples/erasure-attestation`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/erasure-attestation).
