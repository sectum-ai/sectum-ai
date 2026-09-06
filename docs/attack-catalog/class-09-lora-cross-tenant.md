# Class 9 — LoRA / adapter cross-tenant influence

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0024, AML.T0024.000, AML.T0057 · **NIST:** MEASURE 2.7 · **Surface:** model / adapter layer · **Probe id:** `lora-cross-tenant`

## Goal

For a model that hosts per-tenant fine-tunes or LoRA adapters, verify that one
tenant's adapter does not influence another tenant's inference.

## Method

The probe trains a tenant's adapter on a memorizable hard-canary phrase, then
runs inference from every other tenant's session.

## Detection

A foreign canary reproduced in another tenant's inference is weight bleed — a
confirmed cross-tenant leak. With per-tenant-isolated adapters, inference draws
only on the calling tenant's own adapter and nothing surfaces cross-tenant --
but the probe also runs cross-USER, so an adapter scoped to the tenant alone
still leaks a sibling user's memorized content and fails the class.

The probe also asserts **routing**: when the adapter reports which tenant's weights
served an inference (`served_by_tenant`), an answer served by a foreign tenant's
adapter is a HIGH finding even if no canary text surfaced — the request reached the
wrong model.

## Runs when

The probe needs a model adapter that trains per-tenant adapters, reporting either
`per_tenant_adapter` (isolated) or `shared_weights` (the bleed it is built to catch).
A serving-only backend such as vLLM or TGI reports neither, so the probe is
**skipped** there and the class scores `NOT_COVERED`, never `PASS`.

## Status

Implemented in Phase 4.
