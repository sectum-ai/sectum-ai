# Class 11 — GDPR Article 17 erasure verification

**OWASP:** LLM08:2025 · **Surfaces:** vector DB, tracing, agent memory, semantic cache · **Probe id:** `gdpr-erasure-verification`

Proving a tenant's data has actually left an AI system after a right-to-erasure
request.

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

Implemented for the vector-store surface (Phase 3) and, in post-Phase-5
hardening, the observability / tracing, agent / long-term memory, and
semantic / application cache surfaces: `ErasureProbe` accepts a vector-store
plus optional observability, memory, and cache adapters, scans each
independently, and reports a per-surface verdict. The remaining "ten hiding
places" (backups, derived indexes, and the rest) follow as their adapter
families gain a `delete` primitive. Walkthrough:
[`examples/erasure-attestation`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/erasure-attestation).
