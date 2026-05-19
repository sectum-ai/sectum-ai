# Class 8 — Persistent memory contamination

**OWASP:** LLM08:2025 · **Surface:** agent memory · **Probe id:** `memory-contamination`

## Goal

Verify that a long-term or agent memory store does not carry one tenant's
content into another tenant's session.

## Method

The probe writes a hard canary into a tenant's memory, then recalls memory from
every other tenant's session.

## Detection

A foreign canary surfacing in another tenant's recall is cross-tenant memory
contamination. With a per-tenant memory store each tenant recalls only its own
entries and nothing surfaces.

## Status

Implemented in Phase 5.
