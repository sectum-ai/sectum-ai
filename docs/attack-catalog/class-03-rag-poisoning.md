# Class 3 — Adversarial RAG poisoning

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0020, AML.T0024 · **NIST:** MEASURE 2.7 · **Surface:** vector DB · **Probe id:** `rag-poisoning`

## Goal

Verify that a tenant cannot plant a document that pivots retrieval to surface
its content in another tenant's session.

## Method

Each tenant plants a poisoned document: benign-looking, stuffed with a generic
lure phrase so it ranks highly for ordinary queries, and carrying that tenant's
hard canary. Every tenant then issues the lure query.

## Detection

On a shared index the poison document is retrieved into other tenants' queries
and its canary surfaces — a confirmed cross-tenant leak that exists only because
of the planted document. An isolated per-tenant store keeps each poison document
within its own namespace.

## Status

Implemented in Phase 5.
