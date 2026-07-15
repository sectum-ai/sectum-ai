#!/usr/bin/env python
"""examples/embedding-rpr-sweep/run.py

Reproduce the flagship Class 2 finding — *stronger embedding models leak more* —
as a per-model Retrieval-Pivot Rate (RPR) sweep. For each embedding model, the
sweep re-embeds the seeded multi-tenant corpus, runs every tenant's benign
cross-tenant queries, and measures the fraction that retrieve a *foreign* tenant's
pivot document (the RPR). A sharper embedding model resolves the shared organic
entities more precisely, so it pulls back more cross-tenant documents — a higher
RPR. (OWASP LLM08:2025; Retrieval Pivot Attacks in Hybrid RAG, 2026.)

This runs fully offline and deterministically using the hashing-trick embedder at
increasing dimensions as a strength proxy (more buckets → fewer collisions →
sharper similarity). To reproduce the gradient on *real* models, swap the specs
for two or more providers (see ``SPECS`` below) and set the matching API key /
region — the sweep records a genuine per-model RPR regardless of the vector store.
"""

from __future__ import annotations

import logging
import sys
from itertools import pairwise

import structlog

# The sweep logs every cross-tenant retrieval; quiet it so the table is readable.
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))

from sectum_ai.embeddings import resolve_embedding_model  # noqa: E402
from sectum_ai.substrate import build_substrate, default_scenario  # noqa: E402
from sectum_ai.sweep import embedding_provider_sweep  # noqa: E402

# Increasing hashing-embedder dimension is a deterministic, offline strength proxy.
# Swap for real providers to reproduce the gradient on a live stack, e.g.:
#   SPECS = ["st:all-MiniLM-L6-v2", "st:all-mpnet-base-v2"]        # local, BYOC-safe
#   SPECS = ["openai:text-embedding-3-small", "openai:text-embedding-3-large"]
#   SPECS = ["cohere:embed-english-v3.0", "voyage:voyage-3", "bedrock:amazon.titan-embed-text-v2:0"]
SPECS = ["hash-16", "hash-64", "hash-256"]
SEED = 2026


def sweep(specs: list[str]) -> dict[str, float]:
    """Return the per-model Retrieval-Pivot Rate for ``specs`` on the seeded corpus."""
    substrate = build_substrate(default_scenario(seed=SEED))
    models = [resolve_embedding_model(spec) for spec in specs]
    if any(model is None for model in models):
        raise SystemExit(f"every spec must name a real embedding model; got {specs}")
    return embedding_provider_sweep(substrate, models)  # type: ignore[arg-type]


def main() -> int:
    rates = sweep(SPECS)
    print("Per-model Retrieval-Pivot Rate (stronger embeddings leak more)\n")
    print(f"  {'embedding model':<18}  {'RPR':>6}")
    print(f"  {'-' * 18}  {'-' * 6}")
    for spec in SPECS:
        print(f"  {spec:<18}  {rates[spec]:>6.1%}")
    ordered = [rates[spec] for spec in SPECS]
    monotone = all(a <= b for a, b in pairwise(ordered))
    print(
        f"\n  => the {SPECS[0]} embedder leaks {ordered[0]:.0%} of benign cross-tenant "
        f"queries;\n     the sharper {SPECS[-1]} embedder leaks {ordered[-1]:.0%} — "
        "the same shared\n     vector index, a strictly worse leak with a stronger model."
    )
    if not monotone:
        print("\n  ! gradient is not monotone for this run", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
