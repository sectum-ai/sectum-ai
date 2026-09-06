# Class 10 — IKEA-style implicit benign extraction

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0024, AML.T0057 · **NIST:** MEASURE 2.7 · **Surface:** vector DB · **Probe id:** `ikea-extraction`

## Goal

Verify that a tenant cannot extract another tenant's content through a sequence
of ordinary, benign queries — with no prompt injection.

## Method

The probe reproduces the Silent Leaks pattern: a multi-turn sequence of benign
follow-up queries, each seeded on a shared entity. No single turn looks
adversarial.

## Detection

The extraction is confirmed when the multi-turn sequence surfaces a foreign
canary. An isolated per-tenant store surfaces nothing.

The user boundary is separate; see [the user boundary](index.md#the-user-boundary)
for when this class is tested cross-user and when those steps are dropped.

## Status

Implemented in Phase 5.
