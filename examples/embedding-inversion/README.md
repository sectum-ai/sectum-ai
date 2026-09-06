# Embedding inversion across tenants — Class 6

This example reproduces **Attack Class 6**: embedding inversion
across the tenant boundary (the engineering spec, §7). When
embeddings are reachable cross-tenant on a shared index, tenant Y
can attempt to recover tenant X source content via approximate
nearest-neighbour reconstruction of an `ENTITY_CANARY`'s
embedding.

## The attack

Embeddings preserve semantic content. If tenant Y can query a
shared vector index for nearest neighbours to a target embedding
(e.g., by embedding their own probe text and asking for the top-k
hits), and the index returns vectors owned by tenant X, then Y can
*reconstruct* the original X text by sampling synonyms and
re-embedding until the reconstruction matches.

Research has shown >70% inversion success on common embedding
models when the attacker has unrestricted nearest-neighbour
access. The mitigation is straightforward: never return foreign-
tenant vectors from a shared index, even on a query. The probe
verifies that property holds.

This is **OWASP LLM08:2025** on the embedding surface.

## What the demo does

`run.sh` runs the canonical CLI flow end to end against the in-
memory `FakeVectorStore` with `shared_index: true`:

1. **`sectum-ai seed`** provisions four synthetic tenants with
   `ENTITY_CANARY` markers planted across the corpora.
2. **`sectum-ai probe --probe embedding-inversion`** issues, from
   each tenant, nearest-neighbour queries crafted to surface a
   foreign tenant's entity canary. A foreign canary in the returned
   neighbours is a confirmed inversion path; the probe exits `2`
   on at least one such hit.
3. **`sectum-ai report`** assembles the tamper-evident evidence pack.
4. **`sectum-ai verify`** independently re-checks the pack.

## Run it

```sh
./run.sh
```

## What the report tells you

Each Class 6 finding carries:

- the owning tenant (X) + the observing tenant (Y) of the
  cross-tenant inversion path
- the recovered entity canary's id + plaintext +
  `evidence_span` (the text of the returned neighbour)
- the surface (`VECTOR_DB`)
- OWASP / ATLAS / NIST control IDs
Class 6 findings carry no per-finding remediation pointer. The counter-measure
is per-tenant namespace filtering on every query path, or moving to a per-tenant
index entirely.

## What's *not* in this example

- **Active reconstruction loop.** The probe verifies the *path*
  (foreign neighbours reachable cross-tenant) — not the full
  reconstruction attack (iterative re-embedding to recover the
  source text). The `inversion reconstruction rate` the run prints is
  the fraction of partial-fragment queries that surfaced a foreign
  entity canary, i.e. how often the path exists — not a measure of
  text recovered. The path's existence is the leak; closing the
  path closes the reconstruction surface.
- **Differential privacy / noise injection.** Some defences add
  noise to returned embeddings to make reconstruction harder.
  The probe does not measure noise resistance; that's a research-
  level follow-on the catalog may add later.
