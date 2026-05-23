# Class 6 — Embedding inversion across tenants

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0024, AML.T0024.001 · **NIST:** MEASURE 2.7 · **Surface:** vector DB · **Probe id:** `embedding-inversion`

## Goal

Verify that a tenant cannot reconstruct another tenant's source content from
embeddings reachable across the tenant boundary.

## Method

When embeddings are shared — typically through a shared index — an attacker who
holds only a partial signal for a foreign entity can recover the rest. The probe
queries the index with a fragment of each foreign entity canary (its codename
without the unique trailing sequence), modelling that partial knowledge.

## Detection

If the index returns the full canary content for a fragment query, the foreign
entity has been reconstructed — a confirmed cross-tenant leak. An isolated
per-tenant store returns nothing for a foreign fragment.

## Status

Implemented in Phase 5.
