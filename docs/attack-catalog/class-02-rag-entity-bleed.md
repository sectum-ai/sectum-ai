# Class 2 — Organic entity-bleed RAG

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0024, AML.T0057 · **NIST:** MEASURE 2.7 · **Surfaces:** vector DB, RAG pipeline · **Probe ids:** `rag-entity-bleed`, `rag-pipeline-bleed`

The flagship probe. It reproduces the Retrieval Pivot: benign, non-adversarial
queries surface another tenant's content through shared organic entities.

Two probes measure the same Retrieval Pivot at two points in the stack.
`rag-entity-bleed` reads the retrieval directly at the **vector index** — the
purest measurement, isolating the store's tenant scoping. `rag-pipeline-bleed`
measures it at the **end of the RAG pipeline** (retriever + generator) - a live
one when configured, the built-in fake otherwise - where
a foreign canary reaching the generated answer confirms the leak survives the
full pipeline, not just the raw retrieval. The method and detection below apply to
both; they differ in where the retrieval is observed, and in what they can verify: the
pipeline probe plans tenant-level principals only, because the RAG contract carries
no user.

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
surfaced a foreign marker. The rate is a property of the stack under test: high
on a shared index with no isolation (81.2% in the bundled showcase), 0% on a
per-tenant-namespace store.

The rate is a binomial proportion (`k` of `n` benign cross-tenant queries
surfaced a foreign marker), where `n` pools the steps of *both* Class 2 probes —
the vector-index queries and the pipeline-end `rag.ask` steps — so the headline
does not separate the two ends of the retrieval path. On a run with any live
surface, `n` counts only the live surfaces' steps: a leaking fake beside a clean
live backend must not be reported as the configured stack's rate
([the scorecard](../scorecard.md)). So a bare point estimate over-claims precision when
`n` is small. Every run therefore reports a **95% Wilson score confidence
interval** alongside the rate — for example `81.2% (95% CI 68.1%-89.8%, n=48)` —
so the headline is never read as a precise number without its sample size and
uncertainty. The binomial counts (`retrieval_pivot_n`, `retrieval_pivot_k`) and
the interval (`retrieval_pivot_rate_ci`) are recorded in the run's metrics and
signed evidence, so the interval is reproducible by a third party rather than
trusting a rounded figure. The Wilson interval is the right tool here: unlike the
normal (Wald) approximation it stays inside [0, 100%] and keeps near-nominal
coverage at small `n` or an extreme rate (0% or 100%).

## Embedding-model sweep

Stronger retrieval embeddings surface more cross-tenant content, so the
Retrieval-Pivot Rate rises with embedding strength. When a scenario lists two or
more `embedding_models` entries that resolve to real providers, `sectum-ai probe`
sweeps them and reports `retrieval_pivot_rate_by_model`.

!!! warning "The gradient is modelled, not a measurement of your store"

    The sweep builds its **own** index and ranks by cosine over a single index
    shared by every tenant. It never queries the configured vector store, so that
    store's real isolation — namespaces, filters, ACLs — is bypassed by
    construction. The gradient therefore describes how much cross-tenant content
    each *embedding model* surfaces under an assumed shared-index condition; it is
    not `retrieval_pivot_rate`, which is the metric that measures the configured
    store. The CLI prints it under its own heading for this reason.

    Legacy `fake-*` names carry a modelled recall rather than real vectors, so they
    cannot share a sweep with a real provider: a mixed config drops them and says
    so, and a gradient needs two or more *real* models or none is recorded.

Each entry is resolved to an embedding model:

- `st:<model>` — a local [sentence-transformers](https://www.sbert.net/) model
  (opt-in extra `sectum-ai[sentence-transformers]`). The research pair is
  `st:all-MiniLM-L6-v2` (weaker) vs `st:all-mpnet-base-v2` (stronger); sweeping
  them reproduces the published gradient (arXiv:2602.08668). Runs locally, so no
  data leaves the box (BYOC-safe).
- `openai:<model>` — OpenAI embeddings (opt-in extra `sectum-ai[openai]`, key in
  `OPENAI_API_KEY`). Sends the synthetic corpus to OpenAI, so it is not BYOC-safe.
- `cohere:<model>` — Cohere embeddings (opt-in extra `sectum-ai[cohere]`, key in
  `COHERE_API_KEY`); hosted, not BYOC-safe.
- `voyage:<model>` — Voyage AI embeddings (opt-in extra `sectum-ai[voyage]`, key in
  `VOYAGE_API_KEY`); hosted, not BYOC-safe.
- `bedrock:<model>` — Amazon Bedrock embeddings (opt-in extra
  `sectum-ai[bedrock]`, region/creds from the boto3 chain); hosted, not BYOC-safe.
  Both text-embedding families are dispatched by the model id: Titan
  (`amazon.titan-embed-*`, the default) and Cohere-on-Bedrock (`cohere.embed-*`).
- `hash-<dim>` — a deterministic, offline hashing embedder for CI and demos.
- `fake-*` — the legacy recall illustration (embedding strength modelled by a
  per-model retrieval recall on the in-memory store).

The [`embedding-rpr-sweep`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/embedding-rpr-sweep)
example runs the deterministic `hash-<dim>` gradient offline and documents swapping
in these providers. With **real** providers (`st:`/`openai:`/`cohere:`/`voyage:`/`bedrock:`/`hash-`) the per-model rate comes from
actual cosine retrieval over the embedded corpus, so it is recorded for any
configured stack — the "stronger embeddings leak more" gradient no longer
vanishes off the in-memory fake. The legacy `fake-*` recall illustration is
recorded only for an in-memory-store run.

The user boundary is separate; see [the user boundary](index.md#the-user-boundary)
for when this class is tested cross-user and when those steps are dropped.

## Status

Implemented in Phase 3. Walkthrough:
[`examples/retrieval-pivot`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/retrieval-pivot).
