# Adversarial RAG poisoning — Class 3

This example reproduces **Attack Class 3**: adversarial RAG
poisoning (the engineering spec, §7). Tenant Y plants poisoned
content into a shared vector index that is designed to act as a
retrieval pivot; the probe measures the *marker-bleed delta*
between the baseline run and the post-poisoning run.

## The attack

A multi-tenant RAG system that lets one tenant write content into a
shared retrieval store hands every other tenant an attack surface.
Tenant Y inserts a document crafted to surface in tenant X's
queries — a `poison_pivot` document that names a high-frequency
shared entity (a person, a vendor, a compliance term) and carries
a canary. When tenant X next queries on that entity, the poisoned
document comes back; the canary in its body proves the leak path.

Real deployments hit this whenever a "knowledge base" or "shared
prompt library" feature lets one tenant's content land in another
tenant's retrieval path without strict isolation. This is **OWASP
LLM08:2025** combined with **OWASP LLM04 (Data and Model
Poisoning)**.

## What the demo does

`run.sh` runs the canonical CLI flow end to end:

1. **`sectum seed`** provisions four synthetic tenants and their
   canary markers.
2. **`sectum probe --probe rag-poisoning`** runs the probe in two
   phases: (a) a clean baseline run against the substrate, and
   (b) a post-poisoning run after the probe plants `poison_pivot`
   documents into the shared index from each tenant. A finding
   lands whenever a post-poisoning query surfaces a canary that
   the baseline did not — the delta is the leak attributable to
   the poison.
3. **`sectum report`** assembles the tamper-evident evidence pack.
4. **`sectum verify`** independently re-checks the pack.

## Run it

```sh
./run.sh
```

## What the report tells you

Each Class 3 finding carries:

- the planting tenant (Y) + the observing tenant (X) of the
  poisoned retrieval
- the canary id + its `evidence_span` in the post-poisoning result
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
