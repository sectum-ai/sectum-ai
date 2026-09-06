# RAG-pipeline bleed — Class 2 at the customer-facing endpoint

This example reproduces **Attack Class 2** — the organic entity-bleed Retrieval
Pivot — but at the **RAG pipeline** end rather than the raw vector store. It is
the companion to [`retrieval-pivot`](../retrieval-pivot/README.md): same benign
queries, same leak, different surface.

## Why a second surface

The [retrieval-pivot](../retrieval-pivot/README.md) demo probes the vector store
directly (`Surface.VECTOR_DB`). In production, the customer rarely calls the
vector store — they call a **RAG endpoint** that retrieves context and composes
an answer. A shared-index retriever wrapped in a tenant-aware-*looking* pipeline
still leaks, and the contract that matters is the one the customer actually uses.
This probe issues the benign shared-entity queries through the RAG pipeline
adapter (`Surface.RAG_PIPELINE`, the `rag.ask` action) and scans the composed
**answer** for a foreign tenant's canary.

Run both probes against a stack with a real RAG pipeline: the vector probe
verifies the retriever, this one verifies the pipeline that wraps it.

## What the demo does

`run.sh` runs the full Sectum AI workflow:

1. **`sectum-ai seed`** provisions four synthetic tenants (Acme, Globex, Initech,
   Hooli), generates their corpora, and plants canary markers.
2. **`sectum-ai probe --probe rag-pipeline-bleed`** issues a benign query for each
   shared entity from each tenant - six per tenant, 24 in all - through the demo
   RAG pipeline — a shared-index retriever with
   no tenant scoping.
3. **`sectum-ai report`** assembles a tamper-evident evidence pack (JSON + PDF).
4. **`sectum-ai verify`** independently re-checks the pack's integrity.

## Run it

```sh
./run.sh
```

Artifacts are written to `out/`.

## Expected result

The demo pipeline wraps a single shared index, so benign cross-tenant queries
surface foreign canaries through the answer:

```
ran 1 probe: 15 confirmed cross-tenant findings; 0 on live surfaces
retrieval-pivot rate: 62.5% (95% CI 42.7%-78.8%, n=24)
```

`sectum-ai probe` exits with code 2 because it confirmed cross-tenant leaks, and
`sectum-ai verify` reports `INTEGRITY OK — UNANCHORED`: the pack is internally
consistent, but its only timestamp is a reproducible local-dev token, so this
is not independent tamper evidence. As with the vector-store
demo, the rate is a property of the *stack under test*: point the RAG adapter at
a properly tenant-scoped pipeline and the same probe reports **0%**.
