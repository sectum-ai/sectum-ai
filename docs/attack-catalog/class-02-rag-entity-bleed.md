# Class 2 — Organic entity-bleed RAG

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0024, AML.T0057 · **NIST:** MEASURE 2.7 · **Surface:** vector DB · **Probe id:** `rag-entity-bleed`

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

## Embedding-model sweep

Stronger retrieval embeddings surface more cross-tenant content, so the
Retrieval-Pivot Rate rises with embedding strength. When a scenario lists more
than one `embedding_models` entry, `sectum probe` runs the probe once per model
and reports a per-model rate (`retrieval_pivot_rate_by_model`).

Each entry is resolved to an embedding model:

- `st:<model>` — a local [sentence-transformers](https://www.sbert.net/) model
  (opt-in extra `sectum-ai[sentence-transformers]`). The research pair is
  `st:all-MiniLM-L6-v2` (weaker) vs `st:all-mpnet-base-v2` (stronger); sweeping
  them reproduces the published gradient (arXiv:2602.08668). Runs locally, so no
  data leaves the box (BYOC-safe).
- `openai:<model>` — OpenAI embeddings (opt-in extra `sectum-ai[openai]`, key in
  `OPENAI_API_KEY`). Sends the synthetic corpus to OpenAI, so it is not BYOC-safe.
- `hash-<dim>` — a deterministic, offline hashing embedder for CI and demos.
- `fake-*` — the legacy recall illustration (embedding strength modelled by a
  per-model retrieval recall on the in-memory store).

With **real** providers (`st:`/`openai:`/`hash-`) the per-model rate comes from
actual cosine retrieval over the embedded corpus, so it is recorded for any
configured stack — the "stronger embeddings leak more" gradient no longer
vanishes off the in-memory fake. The legacy `fake-*` recall illustration is
recorded only for an in-memory-store run.

## Status

Implemented in Phase 3. Walkthrough:
[`examples/retrieval-pivot`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/retrieval-pivot).
