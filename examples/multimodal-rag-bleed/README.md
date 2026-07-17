# Multi-modal RAG entity-bleed (Class 13)

The Class 2 Retrieval Pivot, generalised to **images**. Multi-modal RAG embeds images
(and text) into one vector space, so a benign, non-adversarial image query for a shared
*visual* entity — a chart type, a logo, a product photo, a floor plan — surfaces another
tenant's image, and its canary marker rides along in the retrieved image's caption. No
prompt injection; the pivot is a property of the shared multi-modal index (OWASP
LLM08:2025; *Retrieval Pivot Attacks in Hybrid RAG*, 2026, generalised to the multi-modal
index).

## Run it

```sh
uv run python examples/multimodal-rag-bleed/run.py
```

Fully offline and deterministic — no image downloads, no API keys. It seeds the demo
four-tenant substrate, renders each tenant's synthetic pivot image per shared visual
entity, and sweeps the deterministic `imagehash-<dim>` embedder at increasing
resolutions:

```
  image model (proxy)    image-RPR      k/n
  --------------------  ----------  -------
  imagehash-16               45.8%    11/24
  imagehash-64               95.8%    23/24
  imagehash-256             100.0%    24/24
```

Benign cross-tenant image queries surface foreign tenants' images — the Retrieval Pivot
over a shared multi-modal index. **`imagehash-<dim>` is a deterministic offline _proxy_**
(like the text `hash-<dim>`): it exercises the sweep machinery with no downloads, but it
is not a semantic model, so this per-dim curve is a reproducible artifact of the synthetic
substrate — **not** a measurement of embedder strength. The script exits non-zero if this
fixed demo ladder is not monotone, so it doubles as a determinism smoke test.

## Reproduce it on a real multi-modal model

Swap the specs in `run.py` for **CLIP** (the `sectum-ai[clip]` extra), which embeds
images and text into one space and runs locally (BYOC-safe — no data leaves the box):

```python
SPECS = ["clip:clip-ViT-B-32"]
```

```sh
pip install "sectum-ai[clip]"
```

The image-RPR then reflects a production multi-modal retriever's real embeddings.

## How the metric is computed

`sectum_ai.multimodal.multimodal_provider_sweep` embeds the shared image index and one
benign image query per (principal, visual entity), retrieves the top-k by cosine across
all tenants, and reports the fraction of benign queries that surfaced a foreign tenant's
marker — with the binomial counts (`multimodal_pivot_counts`) behind a Wilson interval,
exactly as Class 2's text embedding-strength sweep does. See
[`docs/attack-catalog/class-13-multimodal-rag-bleed.md`](../../docs/attack-catalog/class-13-multimodal-rag-bleed.md).
