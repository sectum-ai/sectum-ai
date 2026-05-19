# Class 2 — Organic entity-bleed RAG

**OWASP:** LLM08:2025 · **Surface:** vector DB · **Probe id:** `rag-entity-bleed`

The flagship probe. It reproduces the Retrieval Pivot: benign, non-adversarial
queries surface another tenant's content through shared organic entities.

## Goal

Show that ordinary business queries — with no prompt injection — leak across
tenants when a multi-tenant RAG system retrieves from a shared vector index.

## Method

Tenants deliberately share organic entities: a person, a vendor, a compliance
term, a monetary amount, a date. Each tenant owns a *pivot document* per shared
entity that names the entity and carries one of the tenant's canary markers. The
probe issues one benign query per shared entity from each tenant's session.

## Detection

A foreign canary in the retrieved context is a confirmed leak. The headline
metric is the **Retrieval-Pivot Rate** — the fraction of benign queries that
surfaced a foreign marker. The rate is a property of the stack under test: 100%
on a shared index with no isolation, 0% on a per-tenant-namespace store.

## Status

Implemented in Phase 3. Walkthrough:
[`examples/retrieval-pivot`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/retrieval-pivot).
