# Class 9 — LoRA / adapter cross-tenant influence

**OWASP:** LLM08:2025 · **Surface:** model / adapter layer · **Probe id:** `lora-cross-tenant`

## Goal

For a model that hosts per-tenant fine-tunes or LoRA adapters, verify that one
tenant's adapter does not influence another tenant's inference.

## Method

The probe trains a tenant's adapter on a memorizable hard-canary phrase, then
runs inference from every other tenant's session.

## Detection

A foreign canary reproduced in another tenant's inference is weight bleed — a
confirmed cross-tenant leak. With per-tenant-isolated adapters, inference draws
only on the calling tenant's own adapter and nothing surfaces.

## Status

Implemented in Phase 4.
