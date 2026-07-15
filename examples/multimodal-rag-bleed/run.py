#!/usr/bin/env python
"""examples/multimodal-rag-bleed/run.py

Demonstrate the Class 13 finding — the Class 2 Retrieval Pivot generalises to
*images* — as a per-model image Retrieval-Pivot Rate (RPR) sweep. Multi-modal RAG
embeds images (and text) into one vector space, so a benign image query for a
shared *visual* entity (a chart type, a logo, a product photo) surfaces another
tenant's image, and its canary marker rides along in the retrieved image's caption.
(OWASP LLM08:2025; Retrieval Pivot Attacks in Hybrid RAG, 2026, generalised to the
multi-modal index.)

This runs fully offline and deterministically using the ``imagehash-<dim>`` embedder —
a DETERMINISTIC OFFLINE PROXY that exercises the sweep machinery with no downloads. It is
NOT a semantic model, so its per-dim curve is a reproducible artifact of the synthetic
substrate, not a measurement of embedder strength. The genuine "stronger embedders leak
more" gradient is a property of real embedders: swap the specs for two or more CLIP
models (``clip:clip-ViT-B-32``, the ``sectum-ai[clip]`` extra) — CLIP embeds images and
text into one space and runs locally, so no data leaves the box.
"""

from __future__ import annotations

import logging
import sys
from itertools import pairwise

import structlog

# The sweep logs every cross-tenant retrieval; quiet it so the table is readable.
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))

from sectum_ai.multimodal import (  # noqa: E402
    multimodal_pivot_counts,
    multimodal_provider_sweep,
    resolve_image_embedding_model,
)
from sectum_ai.substrate import build_substrate, default_scenario  # noqa: E402

# Increasing imagehash grid is a deterministic, offline strength proxy. Swap for real
# CLIP to reproduce the gradient on a production multi-modal retriever, e.g.:
#   SPECS = ["clip:clip-ViT-B-32"]                 # one real model (needs the clip extra)
SPECS = ["imagehash-16", "imagehash-64", "imagehash-256"]
SEED = 2026


def sweep(specs: list[str]) -> tuple[dict[str, float], dict[str, tuple[int, int]]]:
    """Return the per-model image-RPR and its binomial counts on the seeded corpus."""
    substrate = build_substrate(default_scenario(seed=SEED))
    models = [resolve_image_embedding_model(spec) for spec in specs]
    if any(model is None for model in models):
        raise SystemExit(f"every spec must name an image model; got {specs}")
    real = [model for model in models if model is not None]
    return multimodal_provider_sweep(substrate, real), multimodal_pivot_counts(substrate, real)


def main() -> int:
    rates, counts = sweep(SPECS)
    print("Per-model image Retrieval-Pivot Rate on the shared multi-modal index\n")
    print(f"  {'image model (proxy)':<20}  {'image-RPR':>10}  {'k/n':>7}")
    print(f"  {'-' * 20}  {'-' * 10}  {'-' * 7}")
    for spec in SPECS:
        k, n = counts[spec]
        print(f"  {spec:<20}  {rates[spec]:>10.1%}  {f'{k}/{n}':>7}")
    ordered = [rates[spec] for spec in SPECS]
    monotone = all(a <= b for a, b in pairwise(ordered))
    print(
        f"\n  => benign cross-tenant image queries surface foreign tenants' images "
        f"({ordered[-1]:.0%}\n     of them at {SPECS[-1]}) — the Retrieval Pivot over a shared "
        "multi-modal index.\n     imagehash is a deterministic offline PROXY (this curve is a "
        "substrate\n     artifact); the real strength gradient is the CLIP path (see the README)."
    )
    # The demo ladder is deliberately monotone; the check is a determinism smoke test, not
    # a claim that a stronger imagehash leaks more (see the module + README caveats).
    if not monotone:
        print("\n  ! demo ladder is not monotone for this run", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
