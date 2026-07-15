# Embedding RPR sweep — "stronger embeddings leak more"

This example reproduces the second half of **Attack Class 2**: not just *that* a
shared vector index leaks across tenants, but that the leak gets **worse as the
embedding model gets stronger**. It runs a per-model **Retrieval-Pivot Rate (RPR)**
sweep and prints the gradient.

The companion [`retrieval-pivot/`](../retrieval-pivot/) example shows the base
cross-tenant leak end-to-end (seed → probe → signed evidence pack) with one
embedder. This one isolates the *embedding-strength* dimension of the same finding.

## The finding

A shared vector index leaks because tenants share organic entities (a vendor, a
compliance term like SOC 2, a person, an amount). A benign query naming one of
those retrieves the *nearest* documents regardless of owner. A **stronger**
embedding model places those documents more precisely in vector space, so it
retrieves *more* of the foreign-tenant matches — a higher RPR. The *Retrieval
Pivot Attacks in Hybrid RAG* research (2026) measured exactly this gradient
(mpnet-base-v2 leaked more than MiniLM). This is **OWASP LLM08:2025 — Vector and
Embedding Weaknesses**; it is a property of the *index*, not of any prompt, so no
injection is involved.

## Run it

```sh
cd examples/embedding-rpr-sweep
uv run python run.py
```

Fully offline and deterministic — it uses the hashing-trick embedder at increasing
dimensions (more buckets → fewer collisions → sharper similarity) as a strength
proxy, so no model download or API key is needed. Expected output:

```
Per-model Retrieval-Pivot Rate (stronger embeddings leak more)

  embedding model        RPR
  ------------------  ------
  hash-16              58.3%
  hash-64              66.7%
  hash-256             83.3%

  => the hash-16 embedder leaks 58% of benign cross-tenant queries;
     the sharper hash-256 embedder leaks 83% — the same shared
     vector index, a strictly worse leak with a stronger model.
```

`run.py` exits non-zero if the gradient is not monotone, so it doubles as a smoke
test of the sweep.

## Reproduce it on real embedding models

Edit `SPECS` in `run.py` to name two or more real providers and set the matching
credential. The sweep records a genuine per-model RPR against the seeded corpus
regardless of the production vector store — the offline hashing proxy just makes
the gradient reproducible with no dependencies.

| Provider | Spec form | Extra | Credential |
|---|---|---|---|
| sentence-transformers (local, BYOC-safe) | `st:all-mpnet-base-v2` | `sectum-ai[sentence-transformers]` | — |
| OpenAI | `openai:text-embedding-3-large` | `sectum-ai[openai]` | `OPENAI_API_KEY` |
| Cohere | `cohere:embed-english-v3.0` | `sectum-ai[cohere]` | `COHERE_API_KEY` |
| Voyage | `voyage:voyage-3` | `sectum-ai[voyage]` | `VOYAGE_API_KEY` |
| Amazon Bedrock (Titan) | `bedrock:amazon.titan-embed-text-v2:0` | `sectum-ai[bedrock]` | `AWS_REGION` (+ boto3 creds) |

The classic research pair is `st:all-MiniLM-L6-v2` (weaker) vs
`st:all-mpnet-base-v2` (stronger); both run locally, so no tenant data leaves the
box.

## On a live stack (via the CLI)

The same sweep runs as part of `sectum-ai probe` when the scenario configures two
or more `embedding_models`; the per-model RPR is recorded in the run's evidence
pack under `metrics.retrieval_pivot_rate_by_model`:

```yaml
# sectum-ai.yaml
scenario:
  seed: 2026
  embedding_models: ["st:all-MiniLM-L6-v2", "st:all-mpnet-base-v2"]
adapters:
  vector_store:
    kind: pgvector          # or any live vector backend
    dsn_env: SECTUM_PGVECTOR_DSN
```

See the [Class 2 attack-catalog page](../../docs/attack-catalog/class-02-rag-entity-bleed.md)
for the full write-up.
