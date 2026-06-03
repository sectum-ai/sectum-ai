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

1. **`sectum seed`** provisions four synthetic tenants (Acme, Globex, Initech,
   Hooli), generates their corpora, and plants canary markers.
2. **`sectum probe --probe rag-pipeline-bleed`** issues one benign shared-entity
   query per tenant through the demo RAG pipeline — a shared-index retriever with
   no tenant scoping.
3. **`sectum report`** assembles a tamper-evident evidence pack (JSON + PDF).
4. **`sectum verify`** independently re-checks the pack's integrity.

## Run it

```sh
./run.sh
```

Artifacts are written to `out/`.

## Expected result

The demo pipeline wraps a single shared index, so benign cross-tenant queries
surface foreign canaries through the answer:

```
ran 1 probe: 15 confirmed cross-tenant findings
retrieval-pivot rate: 62%
```

`sectum probe` exits with code 2 because it confirmed cross-tenant leaks, and
`sectum verify` confirms the evidence pack is intact. As with the vector-store
demo, the rate is a property of the *stack under test*: point the RAG adapter at
a properly tenant-scoped pipeline and the same probe reports **0%**.
