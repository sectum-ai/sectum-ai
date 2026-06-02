"""Embedding models for the Class 2 retrieval-pivot sweep (the engineering spec, sections 7 and 13).

The flagship Class 2 finding is that *stronger* embedding models surface more
cross-tenant content - "stronger embeddings leak more" (arXiv:2602.08668,
mpnet-base-v2 > MiniLM). Reproducing that gradient on a real stack needs real
embeddings, not the deterministic recall illustration the offline fakes use
(:func:`sectum.sweep.embedding_model_sweep`).

This module defines a provider-agnostic :class:`EmbeddingModel` interface (the
spec, section 13: "provider-agnostic interface; default via configured provider
(OpenAI/Anthropic/local)"), a deterministic offline implementation for tests and
CI (:class:`HashingEmbedding`), and opt-in adapters for sentence-transformers
(the MiniLM-vs-mpnet research pair) and OpenAI behind optional extras. A run that
configures two or more *real* models records a genuine per-model Retrieval-Pivot
Rate via :func:`sectum.sweep.embedding_provider_sweep`, regardless of the
production vector store.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol, runtime_checkable

from sectum.spec import ConfigError

__all__ = [
    "EmbeddingModel",
    "HashingEmbedding",
    "OpenAIEmbedding",
    "SentenceTransformerEmbedding",
    "cosine",
    "resolve_embedding_model",
]

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@runtime_checkable
class EmbeddingModel(Protocol):
    """A text embedder: a stable ``name`` plus a batch ``embed`` (the spec, section 13)."""

    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in order."""
        ...


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors; ``0.0`` if either is the zero vector.

    Robust to unnormalised inputs (it divides by both norms), so it works for any
    provider whether or not it returns unit-length vectors.
    """
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(math.fsum(x * x for x in a))
    norm_b = math.sqrt(math.fsum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class HashingEmbedding:
    """A deterministic, offline embedding via the hashing trick.

    No model download and no network: each text maps to an L2-normalised bag of
    SHA-256-hashed word tokens over ``dim`` buckets. Determinism makes it the
    embedder for unit tests and CI, and ``dim`` trades hash collisions for
    fidelity. It is *not* a semantic model, so it does not reproduce the
    embedding-strength gradient real providers show - that is what the opt-in
    :class:`SentenceTransformerEmbedding` / :class:`OpenAIEmbedding` adapters are
    for; this class exists to exercise the sweep machinery deterministically.
    """

    def __init__(self, name: str = "hash-256", *, dim: int = 256) -> None:
        if dim <= 0:
            raise ConfigError(f"embedding dim must be positive, got {dim}")
        self.name = name
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return an L2-normalised hashed bag-of-tokens vector per text."""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in _TOKEN_RE.findall(text.lower()):
            bucket = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % self._dim
            vector[bucket] += 1.0
        norm = math.sqrt(math.fsum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


class SentenceTransformerEmbedding:
    """sentence-transformers embeddings (opt-in extra ``sectum-ai[sentence-transformers]``).

    The research pair is ``all-MiniLM-L6-v2`` (weaker) versus ``all-mpnet-base-v2``
    (stronger); sweeping the two reproduces the "stronger embeddings leak more"
    gradient (arXiv:2602.08668). The model runs locally, so no data leaves the box
    (BYOC-safe). Construction loads the model; an absent extra is a config error.
    """

    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:  # pragma: no cover - exercised only without the extra
            raise ConfigError(
                "sentence-transformers is not installed; "
                'install the extra with: pip install "sectum-ai[sentence-transformers]"'
            ) from error
        self.name = f"st:{model_name}"
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode ``texts`` to normalised vectors with the local model."""
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]


class OpenAIEmbedding:
    """OpenAI embeddings (opt-in extra ``sectum-ai[openai]``).

    Resolves its key from ``api_key_env`` (never inline, per the spec, section 16);
    a missing package or key is a config error. Note this sends the substrate's
    synthetic corpus to OpenAI, so it is not BYOC-safe - prefer
    :class:`SentenceTransformerEmbedding` when data must stay on the box.
    """

    def __init__(self, model_name: str, *, api_key_env: str = "OPENAI_API_KEY") -> None:
        try:
            import openai
        except ImportError as error:  # pragma: no cover - exercised only without the extra
            raise ConfigError(
                'openai is not installed; install the extra with: pip install "sectum-ai[openai]"'
            ) from error
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ConfigError(f"OpenAI embeddings need an API key in ${api_key_env}")
        self.name = f"openai:{model_name}"
        self._model = model_name
        self._client = openai.OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` in one request and return the vectors in input order."""
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [list(item.embedding) for item in response.data]


def _hash_dim(spec: str) -> int:
    """Parse a ``hash-<int>`` / ``hash:<int>`` spec into a dimension (both prefixes are 5 chars)."""
    try:
        return int(spec[len("hash-") :])
    except ValueError as error:
        raise ConfigError(
            f"malformed hashing-embedding spec {spec!r}; expected hash-<dim>"
        ) from error


def resolve_embedding_model(spec: str) -> EmbeddingModel | None:
    """Resolve a scenario embedding-model name to a real :class:`EmbeddingModel`, or ``None``.

    Returns ``None`` for the legacy deterministic recall fakes (``fake-*``), which
    the sweep models through :class:`~sectum.adapters.fakes.FakeVectorStore` recall
    rather than real embeddings. Real specs:

    - ``st:<model>`` -> :class:`SentenceTransformerEmbedding` (e.g. ``st:all-mpnet-base-v2``)
    - ``openai:<model>`` -> :class:`OpenAIEmbedding` (e.g. ``openai:text-embedding-3-small``)
    - ``hash-<dim>`` / ``hash:<dim>`` -> deterministic :class:`HashingEmbedding`

    Raises :class:`~sectum.spec.ConfigError` for a malformed real spec (the typed
    error maps to the CLI's config-error exit code).
    """
    if spec.startswith("st:"):
        return SentenceTransformerEmbedding(spec[len("st:") :])
    if spec.startswith("openai:"):
        return OpenAIEmbedding(spec[len("openai:") :])
    if spec.startswith(("hash-", "hash:")):
        return HashingEmbedding(spec, dim=_hash_dim(spec))
    return None
