# Direct tenant boundary fetch — Class 1

This example reproduces **Attack Class 1**: the table-stakes BOLA
(Broken Object Level Authorization) probe on the vector-store / API
surface. From one tenant's authenticated session, the probe
enumerates the canary document IDs of every *other* tenant and
issues a fetch for each. A document that comes back is a confirmed
authorisation failure: the store did not scope by tenant.

## The attack

Every multi-tenant AI system claims tenant A's data cannot reach
tenant B. A shared vector index that forgets tenant scope (or an
API gateway that doesn't enforce it) silently breaks that claim:
tenant Y fetches an ID owned by tenant X and the document comes
back as if the auth boundary never existed. This is the classic
Broken Object Level Authorization shape applied to AI surfaces.

This is **OWASP LLM08:2025** on the vector-DB / API surface and
also a classic **OWASP API Top 10 #1** (BOLA). Sectum's value-add
over a generic API fuzzer is **manifest-grounded zero-FP
detection**: the document IDs are canaries the substrate planted,
so a returned document is a confirmed leak — no LLM judge, no
fuzzy heuristic.

## What the demo does

`run.sh` runs the canonical CLI flow end to end against the
in-memory `FakeVectorStore` with `shared_index: true` (the leaky
condition Class 1 is built to catch):

1. **`sectum seed`** provisions four synthetic tenants (Acme,
   Globex, Initech, Hooli) and their canary markers; each marker is
   anchored to a doc id in the substrate manifest.
2. **`sectum probe --probe tenant-boundary-fetch`** enumerates each
   tenant's hard-canary doc IDs from the manifest, then from every
   foreign tenant issues a fetch for them. The probe exits `2` when
   it confirms at least one cross-tenant fetch — the success
   signal on the leaky demo stack.
3. **`sectum report`** assembles the tamper-evident evidence pack
   (PDF + JSON + in-toto envelope).
4. **`sectum verify`** independently re-checks the pack's integrity.

## Run it

```sh
./run.sh
```

Expect one confirmed finding per (owner, observer) cross-tenant
pair (12 pairs on the 4-tenant demo with `shared_index: true`).

## What the report tells you

Each Class 1 finding carries:

- the owning tenant + the observing tenant of the cross-tenant fetch
- the leaked marker id + plaintext + `evidence_span`
- the surface (`VECTOR_DB` or `API`)
- OWASP / ATLAS / NIST control IDs
- a remediation pointer naming the standard counter-measure:
  per-tenant namespace scoping (Pinecone namespaces, Weaviate
  multi-tenancy, pgvector schema-per-tenant) + an auth check on
  every read path

## Swap the in-memory store for a real backend

The probe is adapter-agnostic; only the `VectorStoreAdapter` it
routes through changes. Point `vector_store.kind` at any of the
live vector adapters Sectum ships (`pinecone` / `pgvector` /
`weaviate` / `chroma`) and the same probe runs against real
infrastructure:

```yaml
adapters:
  vector_store:
    kind: pgvector
    dsn_env: SECTUM_PGVECTOR_DSN
    shared_index: true   # delete to enforce per-tenant scoping
```

```sh
sectum probe --probe tenant-boundary-fetch --config sectum.yaml --workdir out
```

A real engagement runs the probe with `shared_index: false` to
*verify* isolation holds; the demo here flips it to `true` so the
walkthrough has a leak to show.

## What's *not* in this example

- **Authorisation bypass via header / token tricks.** Class 1
  tests the existence of the scoping boundary; bypass-via-forged-
  credentials is out of scope (Sectum does not test the
  authentication layer itself).
- **403-vs-200-with-empty ambiguity.** A real engagement extends
  the probe to flag stores that return an empty 200 instead of a
  proper 403 — currently those are treated as "no leak observed".
