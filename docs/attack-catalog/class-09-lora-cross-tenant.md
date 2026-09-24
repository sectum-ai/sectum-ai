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
only on the calling tenant's own adapter and nothing surfaces cross-tenant. The
probe also runs cross-USER where the model adapter carries a user (the built-in
fake always; HuggingFace only with `user_scoped: true`; a vLLM/TGI serving
backend never, because the user never reaches the server) — there, an adapter
scoped to the tenant alone still leaks a sibling user's memorized content. Where
the user cannot reach the backend those steps are dropped, not failed, and the
run records `user_steps_dropped`.

The probe also asserts **routing**: when the adapter reports which tenant's weights
served an inference (`served_by`), an answer served by a foreign tenant's
adapter is a HIGH finding even if no canary text surfaced — the request reached the
wrong model.

**No shipped live model adapter implements `served_by`.** The base class returns
`None` (unknown), and `None` is never a finding, so against a live adapter the
routing assertion is *inert*: it emits neither a finding nor a `NOT_COVERED`, and
the class reads exactly as it would had routing been checked and found correct.
Only the built-in fake attributes routing precisely. Unlike the recall half — which
is skipped outright on a serving-only backend, below — this half runs and answers
nothing, so read a clean Class 9 as evidence about memorization, not about routing.
Implementing `served_by` on an adapter that can introspect its routing is what
would change that; the SDK can already do it.

That finding carries `AML.T0024` and `AML.T0057` but **not** `AML.T0024.000` (Infer
Training Data Membership): it evidences that a foreign adapter served the step, and
infers nothing about what the adapter was trained on. The class tuple above is the
probe's full footprint; each finding carries the subset its own sub-probe
demonstrates, as [Class 7](class-07-agent-tool-hijack.md) does and for the reason
[ADR-0009](../adr/0009-atlas-technique-review-process.md) gives.

## Runs when

The probe needs a model adapter that trains per-tenant adapters, reporting either
`per_tenant_adapter` (isolated) or `shared_weights` (the bleed it is built to catch).
A serving-only backend such as vLLM or TGI reports neither, so the probe is
**skipped** there and the class scores `NOT_COVERED`, never `PASS`.

The **routing** assertion has a second, narrower gate that no live adapter passes:
it needs `served_by`, which only the built-in fake implements. A live HuggingFace
adapter reports `per_tenant_adapter` or `shared_weights`, so the probe runs and its
recall half is real — its routing half is inert. See
[Known coverage gaps](../coverage.md#known-coverage-gaps).

## Status

Implemented in Phase 4.
