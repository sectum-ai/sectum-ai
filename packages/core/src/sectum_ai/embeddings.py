"""Embedding models for the Class 2 retrieval-pivot sweep (the engineering spec, sections 7 and 13).

The flagship Class 2 finding is that *stronger* embedding models surface more
cross-tenant content - "stronger embeddings leak more" (arXiv:2602.08668,
mpnet-base-v2 > MiniLM). Reproducing that gradient on a real stack needs real
embeddings, not the deterministic recall illustration the offline fakes use
(:func:`sectum_ai.sweep.embedding_model_sweep`).

This module defines a provider-agnostic :class:`EmbeddingModel` interface (the
spec, section 13: "provider-agnostic interface; default via configured provider
(OpenAI/Anthropic/local)"), a deterministic offline implementation for tests and
CI (:class:`HashingEmbedding`), and opt-in adapters for sentence-transformers
(the MiniLM-vs-mpnet research pair), OpenAI, Cohere, and Voyage behind optional
extras. A run that configures two or more *real* models records a genuine
per-model Retrieval-Pivot Rate via :func:`sectum_ai.sweep.embedding_provider_sweep`,
regardless of the production vector store.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any, Protocol, runtime_checkable

from sectum_ai.spec import ConfigError

__all__ = [
    "CohereEmbedding",
    "EmbeddingModel",
    "HashingEmbedding",
    "OpenAIEmbedding",
    "SentenceTransformerEmbedding",
    "VoyageEmbedding",
    "cosine",
    "resolve_embedding_model",
    "validate_embedding_spec",
]

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Voyage caps a single embed request (1000 texts / a per-model token budget) and does
# not auto-batch, unlike Cohere's client; chunk the corpus to stay under the cap.
_VOYAGE_BATCH = 128


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


def _as_float_rows(rows: Any) -> list[list[float]]:
    """Coerce a provider's embeddings payload to ``list[list[float]]``.

    Shared by the hosted providers whose SDK response shape shifts across releases;
    keeping the coercion here means it is unit-tested without the SDK installed.
    """
    if rows is None:
        raise ConfigError("embedding provider returned no vectors")
    return [[float(value) for value in row] for row in rows]


class CohereEmbedding:
    """Cohere embeddings (opt-in extra ``sectum-ai[cohere]``).

    Resolves its key from ``api_key_env`` (never inline, per the spec, section 16);
    a missing package or key is a config error. Like :class:`OpenAIEmbedding`, this
    sends the substrate's synthetic corpus to a hosted API, so it is not BYOC-safe.
    Uses ``input_type="search_document"`` (the sweep embeds corpus documents).
    """

    def __init__(self, model_name: str, *, api_key_env: str = "COHERE_API_KEY") -> None:
        try:
            import cohere
        except ImportError as error:  # pragma: no cover - exercised only without the extra
            raise ConfigError(
                'cohere is not installed; install the extra with: pip install "sectum-ai[cohere]"'
            ) from error
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ConfigError(f"Cohere embeddings need an API key in ${api_key_env}")
        self.name = f"cohere:{model_name}"
        self._model = model_name
        self._client = cohere.Client(api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` in one request and return the vectors in input order."""
        response = self._client.embed(texts=texts, model=self._model, input_type="search_document")
        return self._vectors(response)

    @staticmethod
    def _vectors(response: object) -> list[list[float]]:
        # Cohere's ``embeddings`` is a plain list of vectors on the v1-style client;
        # a v5 by-type response instead nests them under ``.float``/``.float_``. Read
        # either, so a client-version bump does not silently break the sweep.
        embeddings = getattr(response, "embeddings", response)
        for attr in ("float_", "float"):
            typed = getattr(embeddings, attr, None)
            if typed is not None:
                return _as_float_rows(typed)
        return _as_float_rows(embeddings)


class VoyageEmbedding:
    """Voyage AI embeddings (opt-in extra ``sectum-ai[voyage]``).

    Resolves its key from ``api_key_env`` (never inline, per the spec, section 16);
    a missing package or key is a config error. Like :class:`OpenAIEmbedding`, this
    sends the substrate's synthetic corpus to a hosted API, so it is not BYOC-safe.
    Uses ``input_type="document"`` (the sweep embeds corpus documents). Voyage caps a
    single request at 1000 texts (and a per-model token budget) and does not
    auto-batch, so the whole-corpus sweep is chunked in ``_VOYAGE_BATCH``-sized calls.
    """

    def __init__(self, model_name: str, *, api_key_env: str = "VOYAGE_API_KEY") -> None:
        try:
            import voyageai
        except ImportError as error:  # pragma: no cover - exercised only without the extra
            raise ConfigError(
                'voyageai is not installed; install the extra with: pip install "sectum-ai[voyage]"'
            ) from error
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ConfigError(f"Voyage embeddings need an API key in ${api_key_env}")
        self.name = f"voyage:{model_name}"
        self._model = model_name
        self._client = voyageai.Client(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` and return the vectors in input order, chunked per request."""
        return self._embed_batched(self._client, self._model, texts)

    @classmethod
    def _embed_batched(cls, client: Any, model: str, texts: list[str]) -> list[list[float]]:
        # Voyage does not batch a single embed request, so split the corpus into
        # <=_VOYAGE_BATCH-text calls and concatenate the vectors in input order.
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _VOYAGE_BATCH):
            batch = texts[start : start + _VOYAGE_BATCH]
            response = client.embed(batch, model=model, input_type="document")
            vectors.extend(cls._vectors(response))
        return vectors

    @staticmethod
    def _vectors(response: object) -> list[list[float]]:
        # Voyage returns an object with ``.embeddings`` = list[list[float]].
        return _as_float_rows(getattr(response, "embeddings", response))


def _hash_dim(spec: str) -> int:
    """Parse a ``hash-<int>`` / ``hash:<int>`` spec into a dimension (both prefixes are 5 chars).

    Rejects a non-positive dimension here, at config-validation time - otherwise
    ``hash-0`` / ``hash--3`` would pass ``validate_embedding_spec`` and fail only
    when the sweep instantiates the embedder, defeating the early check.
    """
    try:
        dim = int(spec[len("hash-") :])
    except ValueError as error:
        raise ConfigError(
            f"malformed hashing-embedding spec {spec!r}; expected hash-<dim>"
        ) from error
    if dim <= 0:
        raise ConfigError(f"hashing-embedding dimension must be positive, got {spec!r}")
    return dim


def resolve_embedding_model(spec: str) -> EmbeddingModel | None:
    """Resolve a scenario embedding-model name to a real :class:`EmbeddingModel`, or ``None``.

    Returns ``None`` for the legacy deterministic recall fakes (``fake-*``), which
    the sweep models through :class:`~sectum_ai.adapters.fakes.FakeVectorStore` recall
    rather than real embeddings. Real specs:

    - ``st:<model>`` -> :class:`SentenceTransformerEmbedding` (e.g. ``st:all-mpnet-base-v2``)
    - ``openai:<model>`` -> :class:`OpenAIEmbedding` (e.g. ``openai:text-embedding-3-small``)
    - ``cohere:<model>`` -> :class:`CohereEmbedding` (e.g. ``cohere:embed-english-v3.0``)
    - ``voyage:<model>`` -> :class:`VoyageEmbedding` (e.g. ``voyage:voyage-3``)
    - ``hash-<dim>`` / ``hash:<dim>`` -> deterministic :class:`HashingEmbedding`

    Raises :class:`~sectum_ai.spec.ConfigError` for a malformed real spec (the typed
    error maps to the CLI's config-error exit code).
    """
    if spec.startswith("st:"):
        return SentenceTransformerEmbedding(spec[len("st:") :])
    if spec.startswith("openai:"):
        return OpenAIEmbedding(spec[len("openai:") :])
    if spec.startswith("cohere:"):
        return CohereEmbedding(spec[len("cohere:") :])
    if spec.startswith("voyage:"):
        return VoyageEmbedding(spec[len("voyage:") :])
    if spec.startswith(("hash-", "hash:")):
        return HashingEmbedding(spec, dim=_hash_dim(spec))
    return None


def validate_embedding_spec(spec: str) -> None:
    """Raise :class:`~sectum_ai.spec.ConfigError` if ``spec`` is not a recognised model name.

    A lightweight, side-effect-free check (it does not load any provider, so it
    needs no API key or optional extra) used to reject an unknown ``embedding_models``
    entry at config-load / CLI-parse time rather than letting it silently become a
    no-op sweep. Accepts the legacy ``fake-*`` recall names, a deterministic
    ``hash-<dim>`` (whose dim is validated), and the ``st:`` / ``openai:`` provider
    prefixes (their install / key is checked lazily when the sweep runs).
    """
    for prefix in ("st:", "openai:", "cohere:", "voyage:"):
        if spec.startswith(prefix):
            if not spec[len(prefix) :]:
                raise ConfigError(
                    f"embedding spec {spec!r} is missing a model name after {prefix!r}"
                )
            return
    if spec.startswith(("hash-", "hash:")):
        _hash_dim(spec)
        return
    if spec.startswith("fake-"):
        return
    raise ConfigError(
        f"unknown embedding model {spec!r}; expected one of fake-<name>, hash-<dim>, "
        "st:<model>, openai:<model>, cohere:<model>, or voyage:<model>"
    )
