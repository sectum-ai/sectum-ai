"""Embedding-model sweep for the Class 2 retrieval-pivot probe (the engineering spec, section 7).

Real retrieval embeddings differ in strength: a stronger model surfaces more
cross-tenant content, so the Retrieval-Pivot Rate rises with embedding strength
("stronger embeddings leak more"). With the deterministic fakes that effect is
modelled by a per-model retrieval recall on a shared index - a weaker model
misses a fraction of the cross-tenant pivot documents. The sweep runs the
flagship Class 2 bleed probe once per configured embedding model and reports the
Retrieval-Pivot Rate for each. Configuring real embedding providers (a later
phase) makes the gradient reflect the actual models.

It is a fake-substrate illustration: the CLI records its rates only for runs
that use the in-memory store, so a live vector adapter's evidence pack carries
no fake-derived per-model rates.
"""

from collections.abc import Sequence

from sectum.adapters.fakes import FakeVectorStore
from sectum.embeddings import EmbeddingModel, cosine
from sectum.probes import RagEntityBleedProbe
from sectum.runner import StepResult, _payload_int, retrieval_pivot_rate
from sectum.spec import Observation, Substrate, Surface

FAKE_EMBEDDING_STRENGTH: dict[str, float] = {
    "fake-mini": 0.2,
    "fake-base": 0.5,
    "fake-strong": 1.0,
    "fake-deterministic": 1.0,
}
"""Named fake embedding models mapped to a modelled retrieval recall (strength)."""


def model_recall(model: str) -> float:
    """Return the modelled retrieval recall for a fake embedding-model name."""
    return FAKE_EMBEDDING_STRENGTH.get(model, 1.0)


def embedding_model_sweep(substrate: Substrate, models: tuple[str, ...]) -> dict[str, float]:
    """Run the Class 2 bleed probe under each embedding model; return per-model RPR.

    Each model parameterises a shared-index ``FakeVectorStore`` by its modelled
    recall, so a weaker model surfaces fewer cross-tenant pivot documents and
    records a lower Retrieval-Pivot Rate.
    """
    probe = RagEntityBleedProbe()
    steps = probe.plan(substrate)
    rates: dict[str, float] = {}
    for model in models:
        store = FakeVectorStore(shared_index=True, recall=model_recall(model))
        for tenant in substrate.tenants:
            store.upsert(
                tenant.tenant_id,
                [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id],
            )
        results: list[StepResult] = []
        for step in steps:
            k = _payload_int(step, "k", "5")
            hits = store.query(step.actor_tenant_id, step.payload["query"], k)
            observation = Observation(
                step_id=step.step_id,
                surface=Surface.VECTOR_DB,
                raw_response="\n".join(hit.content for hit in hits),
            )
            results.append((step, probe.detect(step, observation, substrate)))
        rates[model] = retrieval_pivot_rate(results)
    return rates


def embedding_provider_sweep(
    substrate: Substrate, models: Sequence[EmbeddingModel]
) -> dict[str, float]:
    """Run the Class 2 bleed probe under each *real* embedding model; return per-model RPR.

    Unlike :func:`embedding_model_sweep` - a deterministic recall illustration on a
    ``FakeVectorStore`` that is meaningful only for the in-memory fake - this embeds
    every document and benign query with the model's real vectors and retrieves the
    top-k by cosine over a single shared index across all tenants. The per-model
    gradient therefore reflects the actual embeddings ("stronger embeddings leak
    more"), so it is recorded for any configured stack, not only the fake.

    Documents and queries are each embedded in one batch per model to keep a remote
    provider to two calls per model.
    """
    probe = RagEntityBleedProbe()
    steps = probe.plan(substrate)
    documents = list(substrate.documents)
    rates: dict[str, float] = {}
    for model in models:
        document_vectors = model.embed([f"{doc.title} {doc.content}" for doc in documents])
        index = list(zip(documents, document_vectors, strict=True))
        query_vectors = model.embed([step.payload["query"] for step in steps])
        results: list[StepResult] = []
        for step, query_vector in zip(steps, query_vectors, strict=True):
            k = _payload_int(step, "k", "5")
            ranked = sorted(
                ((cosine(query_vector, vector), doc) for doc, vector in index),
                key=lambda scored: (-scored[0], scored[1].doc_id),
            )[:k]
            observation = Observation(
                step_id=step.step_id,
                surface=Surface.VECTOR_DB,
                raw_response="\n".join(doc.content for _, doc in ranked),
            )
            results.append((step, probe.detect(step, observation, substrate)))
        rates[model.name] = retrieval_pivot_rate(results)
    return rates
