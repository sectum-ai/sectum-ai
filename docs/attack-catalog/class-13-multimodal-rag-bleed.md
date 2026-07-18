# Class 13 — Multi-modal RAG entity-bleed

**OWASP:** LLM08:2025 · **ATLAS:** AML.T0024, AML.T0057 · **NIST:** MEASURE 2.7 · **Surface:** vector DB (multi-modal) · **Probe id:** `multimodal-rag-bleed`

The Class 2 Retrieval Pivot, generalised to **images**. Multi-modal RAG embeds
images (and text) into one vector space, so the shared-index isolation failure that
Class 2 finds over text recurs over *visual* entities.

## Goal

Show that ordinary, non-adversarial image queries — with no prompt injection — leak
across tenants when a multi-modal RAG system retrieves images from a shared vector
index. Multi-modal RAG is the fastest-growing retrieval modality, and it inherits Class
2's failure mode: the pivot is a property of the shared embedding space, not of the
modality.

## Method

Tenants deliberately share *visual entities*: a chart type, a logo, a product photo, a
floor plan, a signature card. Each tenant owns a *pivot image* per shared visual entity
— its own rendered copy of that entity — and the image's caption/payload carries one of
the tenant's canary markers. The probe issues one benign image query per shared visual
entity from each principal's session (a tenant, or a user within a tenant — ADR-0006; a
query for "images of a bar chart"), retrieving by image-embedding similarity across the
shared index.

The substrate renders deterministic synthetic images (Pillow), so a run is reproducible
and needs no image downloads. Each visual entity is a distinct high-frequency texture on
a shared low-frequency base; a tenant's copy adds a small per-tenant jitter so same-entity
images stay near each other without being identical.

## Detection

A foreign canary in the retrieved image's payload is a confirmed leak — the same
detection pipeline as Class 2. The headline metric is the **image Retrieval-Pivot Rate**
— the fraction of benign cross-tenant image queries that surfaced a foreign marker.
`multimodal_pivot_counts` reports the binomial counts (`k` of `n`) behind the rate, so a
95% Wilson score confidence interval can be formed rather than reading the rate as a
precise number without its sample size.

!!! warning "The image-RPR is not yet carried in the evidence pack"

    Unlike Class 2 — whose rate, counts, and Wilson interval are fields on `RunMetrics`
    and are therefore signed and recomputable from an evidence pack — the image-RPR and
    its counts exist only in the sweep API and the example. `RunMetrics` carries no
    multi-modal field, and `multimodal-rag-bleed` is in no named suite, so nothing
    multi-modal reaches `run.json` or a signed pack. Forming the interval means calling
    `multimodal_pivot_counts` yourself. The CLI/suite wiring that would make these counts
    signed evidence is a follow-on.

## Image-embedding-model sweep

`sectum_ai.multimodal.multimodal_provider_sweep` runs the probe once per image-embedding
model and reports the per-model image Retrieval-Pivot Rate. On **real** embedders (CLIP)
a stronger model resolves the shared visual entity more precisely and surfaces more
cross-tenant images — the multi-modal echo of Class 2's "stronger embeddings leak more".
Each spec resolves to an image model:

- `imagehash-<dim>` — a deterministic, offline perceptual-hash embedder (`dim` a perfect
  square, e.g. `imagehash-16` / `imagehash-64` / `imagehash-256`) for CI and demos, the
  image analogue of the text `hash-<dim>`. Like `hash-<dim>`, it is **not** a semantic
  model: it exercises the sweep machinery deterministically with no downloads, and its
  per-dim curve is a reproducible artifact of the synthetic substrate, **not** a
  measurement of embedder strength (the genuine gradient is the `clip:` path).
- `clip:<model>` — real [CLIP](https://www.sbert.net/examples/applications/image-search/README.html)
  image embeddings via sentence-transformers (opt-in extra `sectum-ai[clip]`, default
  `clip:clip-ViT-B-32`). CLIP embeds images and text into one space and runs locally, so
  no data leaves the box (BYOC-safe); sweeping two or more CLIP models measures the real
  embedding-strength gradient.

The [`multimodal-rag-bleed`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/multimodal-rag-bleed)
example runs the deterministic `imagehash-<dim>` proxy offline (a fixed, deliberately
monotone demo ladder: `imagehash-16` ~46% → `imagehash-256` 100% on the demo substrate)
and documents swapping in CLIP for the real gradient. `run.py` exits non-zero if the demo
ladder is not monotone, so it doubles as a determinism smoke test.

## Status

Implemented in the multi-modal wave. The Class 13 image Retrieval-Pivot Rate is measured
by its per-model sweep (as Class 2's embedding-strength gradient is a core sweep over the
flagship probe), driving the probe's plan/detect over the deterministic image substrate
or real CLIP. Live multi-modal vector-store adapters and generic-suite / CLI wiring are a
follow-on. Walkthrough:
[`examples/multimodal-rag-bleed`](https://github.com/sectum-ai/sectum-ai/tree/main/examples/multimodal-rag-bleed).
