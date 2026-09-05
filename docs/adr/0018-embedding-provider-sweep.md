# ADR-0018: real embedding providers are opt-in extras; a deterministic hashing model is the default

- Status: Accepted
- Date: 2026-06-02
- Deciders: Dmitry Maranik

## Context

The flagship Class 2 finding is that *stronger* embedding models surface more
cross-tenant content — "stronger embeddings leak more" (arXiv:2602.08668,
mpnet-base-v2 > MiniLM). The per-model Retrieval-Pivot Rate sweep
(`retrieval_pivot_rate_by_model`) is the metric that demonstrates it.

The original sweep modelled embedding strength with a per-model retrieval
*recall* knob on the in-memory `FakeVectorStore`, and the CLI recorded the metric
only when the configured store was that fake. On a live POC — the exact moment a
prospect is watching — the gradient vanished: a real vector adapter recorded no
per-model rates. The spec's technology table (section 13) already calls for a
"provider-agnostic [embedding] interface; default via configured provider
(OpenAI/Anthropic/local)", so the fix is to make the sweep run on real
embeddings.

The constraint is the usual one: real providers are heavy or hosted.
sentence-transformers pulls in torch; OpenAI is a network call that sends the
corpus off-box. Forcing either into the base install would bloat the dependency
tree and break the "no network in unit tests" rule (the spec, section 15) and the
BYOC data-flow guarantee (section 17) — the same reasoning that makes weasyprint
([ADR-0017](0017-pdf-engine.md)) and Rekor anchoring optional extras.

## Decision

Introduce a provider-agnostic `EmbeddingModel` interface (`name` + batched
`embed`) with a deterministic default and opt-in real providers, and record the
per-model rate for **any** vector store.

- `HashingEmbedding` — a deterministic, offline hashing-trick embedder — is the
  default. It needs no model download or network, so it is the embedder for unit
  tests and CI and keeps the base install pure-Python. It is not semantic, so it
  does not reproduce the strength gradient; it exists to exercise the sweep
  machinery and the demo path deterministically.
- `SentenceTransformerEmbedding` (extra `sectum-ai[sentence-transformers]`) and
  `OpenAIEmbedding` (extra `sectum-ai[openai]`) are imported lazily, only when a
  matching `embedding_models` spec is resolved; an absent extra or missing API
  key raises a typed `ConfigError` with the install hint. sentence-transformers
  runs locally (BYOC-safe); OpenAI sends the synthetic corpus off-box and is
  documented as such.
- Scenario `embedding_models` entries are resolved by prefix: `st:<model>`,
  `openai:<model>`, `hash-<dim>`, or a legacy `fake-*` name.

  > **Update (2026-09-05).** Three more hosted providers ship behind the same
  > seam, so the full prefix set is `st:`, `openai:`, `cohere:`, `voyage:`,
  > `bedrock:`, `hash-<dim>`, and the legacy `fake-*` names
  > (`sectum_ai.embeddings`).
- `embedding_provider_sweep` embeds the corpus and the benign queries with each
  real model and retrieves top-k by **cosine** over a single shared index, so the
  per-model rate reflects the real embeddings. Because it is a property of the
  embedding model × corpus, it is independent of the production vector store and
  is recorded whatever that store is. Legacy `fake-*` names keep the old recall
  illustration, which stays gated to the in-memory store so fake-derived rates
  never enter a live run's evidence.

## Consequences

- The "stronger embeddings leak more" gradient is now demonstrable on a live
  stack: configure `embedding_models: ["st:all-MiniLM-L6-v2", "st:all-mpnet-base-v2"]`
  and the per-model rates reflect real retrieval.
- The base install and CI stay pure-Python and offline; the real providers are a
  one-line extra away.
- The sweep re-embeds the corpus per model rather than reusing the production
  store's vectors — correct for a model comparison, but it does not exercise the
  live adapter's own retrieval path. Validating an embedding the live store
  actually uses is a separate concern.
- Two embedding paths (real cosine vs legacy recall) coexist. The recall path is
  retained only for the deterministic offline illustration and its existing
  tests; new work targets the provider interface.
