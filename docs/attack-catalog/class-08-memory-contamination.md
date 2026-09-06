# Class 8 — Persistent memory contamination

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0057 · **NIST:** MEASURE 2.7 · **Surface:** agent memory · **Probe id:** `memory-contamination`

## Goal

Verify that a long-term or agent memory store does not carry one tenant's
content into another tenant's session.

## Method

The probe writes a hard canary into a tenant's memory, then recalls memory from
every other tenant's session.

## Detection

A foreign canary surfacing in another tenant's recall is cross-tenant memory
contamination. With a per-tenant memory store each tenant recalls only its own
entries and nothing surfaces cross-tenant. The user boundary is separate: where
the memory adapter carries a user (the built-in fake always; live Redis only with
`user_scoped: true`; mem0 never, because its flat `user_id` space *is* the
tenant), a store keyed by tenant alone lets one user recall a sibling user's
note. Where it cannot, those steps are dropped rather than failed and the run
records `user_steps_dropped`.

## Status

Implemented in Phase 5.
