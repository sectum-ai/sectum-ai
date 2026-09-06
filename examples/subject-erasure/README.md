# Verify a real data subject's erasure (A3)

`sectum-ai erasure --subject` verifies a **real** data subject's GDPR Article 17 /
CCPA §1798.105 erasure *after your own deletion has run* — by record id and by
content fingerprint — and writes a per-subject signed attestation. Unlike the
canary-driven [erasure-attestation](../erasure-attestation/) demo, this verifies a
specific subject's real records rather than synthetic markers.

## Two methods

- **By id** — confirm each of the subject's record ids is gone by id (deterministic),
  on the vector store (`fetch`), the semantic cache (`get`), and tracing (`fetch_trace`).
- **By content fingerprint** — probe with the subject's known content and check
  whether it still surfaces, catching *derived* residual (an embedding copy, a
  memorised fine-tune, a memory entry, a search-index hit) that a by-id check would
  miss — on the vector store, model adapter, agent memory, and search index.

`records` carries **ids only** (no PII); `fingerprints` carries the subject's
**content**, used only to query and stored as a **hash** in the attestation — never
in the clear. See [`subject.yaml`](subject.yaml).

## Run

```sh
./run.sh
```

`run.sh` seeds a substrate, runs `erasure --subject subject.yaml`, and independently
verifies the attestation. It runs against the built-in synthetic store, so it reports
`ERASED` with a loud warning that no live adapter is configured — an honest run never
reads "verified" against an empty store.

## Against production data

Point `vector_store` in [`sectum-ai.yaml`](sectum-ai.yaml) at your real backend
(Qdrant, pgvector, …). A surface is `ERASED` only when every supplied id is gone
**and** no supplied content still surfaces; every other surface reads `NOT_COVERED`,
so the attestation never implies coverage it did not verify. Fingerprint probing is
best-effort — a clean result is evidence the content no longer surfaces, not proof of
absence. Against a real approximate-nearest-neighbour store the vector surface
usually reads `NOT_COVERED` rather than `ERASED`: the check treats a **full**
top-50 page without the phrase as inconclusive, and such a store returns a full
page whenever the tenant still holds that many vectors — which an A3 subject
erasure, removing one subject's data rather than the tenant's, leaves it doing
(see the coverage gaps in `docs/coverage.md`).
`tests/integration/test_subject_erasure_qdrant.py` shows a live,
residual-catching run against Qdrant.

## Exit codes

`0` clean · `2` residual remains (a record still present or content still surfaces) ·
`3` nothing could be verified.
