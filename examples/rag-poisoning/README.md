# Adversarial RAG poisoning — Class 3

This example reproduces **Attack Class 3**: adversarial RAG
poisoning (the engineering spec, §7). Tenant Y plants poisoned
content into a shared vector index that is designed to act as a
retrieval pivot; the probe then queries the poison's lure from
every tenant and flags any query whose retrieved context comes
back carrying Y's canary.

## The attack

A multi-tenant RAG system that lets one tenant write content into a
shared retrieval store hands every other tenant an attack surface.
Tenant Y inserts a document crafted to surface in other tenants'
queries — a poison document stuffed with a generic lure phrase (a
"quarterly operations digest") so it ranks highly, carrying Y's
hard canary in its body. When another tenant queries that lure, the
poisoned document is retrieved; Y's canary in the retrieved context
proves the cross-tenant leak path.

Real deployments hit this whenever a "knowledge base" or "shared
prompt library" feature lets one tenant's content land in another
tenant's retrieval path without strict isolation. This is **OWASP
LLM08:2025** combined with **OWASP LLM04 (Data and Model
Poisoning)**.

## What the demo does

`run.sh` runs the canonical CLI flow end to end:

1. **`sectum seed`** provisions four synthetic tenants and their
   canary markers.
2. **`sectum probe --probe rag-poisoning`** plants one poison
   document per hard canary (carrying that marker's owning
   principal's canary under the lure phrase) into the shared index,
   then queries the lure from every principal. A finding lands
   whenever a query's retrieved context carries a canary owned by a
   *different* principal — the cross-tenant poison pivot.
3. **`sectum report`** assembles the tamper-evident evidence pack.
4. **`sectum verify`** independently re-checks the pack.

## Run it

```sh
./run.sh
```

## What the report tells you

Each Class 3 finding carries:

- the owning principal (Y, who planted the poison) + the observing
  principal (X, whose query retrieved it)
- the canary id + its `evidence_span` in the retrieved context
- the surface (`VECTOR_DB`)
- OWASP / ATLAS / NIST control IDs
- a remediation pointer naming the standard counter-measure: per-
  tenant write scoping on the index, schema-level isolation, or
  signed-provenance metadata on every ingested document

## What's *not* in this example

- **Cross-tenant prompt injection via retrieved content.** This
  probe verifies retrieval-side leakage; prompt-injection payloads
  that the RAG pipeline then executes are a separate surface the
  attack catalog treats under Class 2 + a future explicit prompt-
  injection probe.
- **Embedding-model-specific poisoning.** Some attacks exploit
  embedding-space proximity directly (gradient-aligned tokens);
  this probe stays at the document-content level so it works
  across embedding models.
