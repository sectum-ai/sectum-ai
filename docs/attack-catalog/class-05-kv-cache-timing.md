# Class 5 — KV-cache timing side channel

**OWASP:** LLM08:2025 · **ATLAS:** — (not an attack technique; a statistical timing side channel) · **NIST:** MEASURE 2.7 · **Surface:** KV cache · **Probe id:** `kv-cache-timing`

## Goal

Detect whether shared inference infrastructure leaks one tenant's prompt content
to another through KV prefix-cache timing.

## Method

Class 5 is a statistical timing test. It warms the cache as one tenant, then, as
another tenant, measures inference latency over many trials for prompts that do
and do not share the warmed prefix.

## Detection

The probe computes the effect size (Cohen's d) of the timing gap between the
primed and control conditions. An effect size above the large-effect threshold —
clear of the per-prompt jitter noise floor — is a confirmed side-channel
finding, with severity scaled by signal strength. The per-pair effect sizes are
recorded in the run metrics.

## Status

Implemented in Phase 5. Like the Class 11 erasure probe, Class 5 is a
statistical workflow with its own entry point rather than a plan/detect probe.
