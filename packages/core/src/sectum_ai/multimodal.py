"""Multi-modal RAG entity-bleed (Class 13): image marker substrate + image embedders + sweep.

Class 2 reproduces the Retrieval Pivot over *text* embeddings: benign queries on a
shared organic entity surface another tenant's text through a shared vector index.
Multi-modal RAG embeds images (and text) into one space, so the same pivot happens
over *visual* entities - a benign image query for a shared visual entity (a chart, a
logo, a product photo) surfaces another tenant's image, and the canary marker rides
along in that image's caption/payload. Multi-modal RAG is the fastest-growing retrieval
modality and inherits Class 2's isolation failure (arXiv:2602.08668's pivot generalises
to any shared embedding space).

This module mirrors :mod:`sectum_ai.embeddings` / :mod:`sectum_ai.sweep` for images:

- a small catalog of shared *visual entities*, each a deterministic synthetic image
  (Pillow) so the substrate stays reproducible and needs no image downloads;
- a provider-agnostic :class:`ImageEmbeddingModel` interface with a deterministic
  offline implementation for tests and CI (:class:`ImageHashEmbedding`, the image
  analogue of :class:`~sectum_ai.embeddings.HashingEmbedding`; the ``multimodal`` extra)
  and an opt-in CLIP adapter (:class:`ClipImageEmbedding`, real CLIP via
  sentence-transformers; the ``clip`` extra);
- :func:`multimodal_provider_sweep`, which embeds the image corpus and benign image
  queries with each model and reports the per-model **image Retrieval-Pivot Rate** - the
  image analogue of Class 2's per-model rate.

Like the text :class:`~sectum_ai.embeddings.HashingEmbedding`, :class:`ImageHashEmbedding`
is a deterministic offline stand-in that exercises the sweep machinery in CI/demos; it
does *not* faithfully reproduce the "stronger embeddings leak more" gradient real image
embedders show - that is what the opt-in CLIP path is for. The real gradient is a property
of the embedder, measured by running the sweep over :class:`ClipImageEmbedding`.

Pillow is imported lazily (the ``multimodal`` extra) so importing this module - and the
rest of core - never requires it.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from sectum_ai.embeddings import cosine
from sectum_ai.spec import ConfigError, Substrate

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

__all__ = [
    "ClipImageEmbedding",
    "ImageEmbeddingModel",
    "ImageHashEmbedding",
    "multimodal_pivot_counts",
    "multimodal_provider_sweep",
    "render_entity_image",
    "resolve_image_embedding_model",
    "validate_image_embedding_spec",
]

_CANVAS = 64
# Per-tenant filler images (no marker) that a weak embedder confuses with the query
# entity, crowding foreign pivots out of the top-k - the distractors that make the
# Retrieval-Pivot Rate rise with embedding strength.
_FILLERS_PER_TENANT = 40
_TOP_K = 5


def _require_pillow() -> Any:
    try:
        from PIL import Image
    except ImportError as error:  # pragma: no cover - exercised only without the extra
        raise ConfigError(
            "Pillow is not installed; the multi-modal image substrate needs it. "
            'Install the extra with: pip install "sectum-ai[multimodal]"'
        ) from error
    return Image


def _digest(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:8], 16)


def _pattern(key: str) -> tuple[int, int, int]:
    """A distinct stripe pattern per visual-entity key: ``(freq, angle_deg, phase_deg)``.

    The frequency, angle, and phase are hashed from the key so every entity gets a stable,
    distinct texture and a tenant's copies of the same entity cluster together - enough to
    drive the deterministic ``imagehash`` proxy. (It is only a proxy: the texture is above
    the Nyquist limit of the small hash grids, so the sweep's per-dim differences are a
    reproducible artifact of the synthetic substrate, not a faithful strength gradient.)
    """
    raw = _digest("pattern", key)
    return 16 + (raw % 16), (raw // 10) % 180, (raw // 1000) % 360


def render_entity_image(key: str, variant: int = 0) -> Image:
    """Render a deterministic grayscale image for a visual entity (or filler) ``key``.

    Each image is a *shared* low-frequency base (identical across every image, so a
    coarse hash sees them all as near-identical) plus an entity-specific high-frequency
    texture (the only distinguishing signal) plus a small per-``variant`` jitter (so a
    tenant's copy of a shared entity differs slightly without moving off the entity).

    Byte-deterministic per platform (verified in tests). The pixel values come from float
    trig, so a last-ULP ``libm`` difference could flip a byte across platforms - fine here
    because these images are ephemeral sweep inputs, never part of the signed evidence.
    """
    image_cls = _require_pillow()
    freq, angle, phase = _pattern(key)
    theta = math.radians(angle)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    phase_r = math.radians(phase)
    jitter = (_digest("variant", key, variant) % 13) - 6
    img = image_cls.new("L", (_CANVAS, _CANVAS))
    pixels = img.load()
    for y in range(_CANVAS):
        for x in range(_CANVAS):
            base = 90.0 + 60.0 * math.sin(2 * math.pi * ((x + y) / (2 * _CANVAS)))
            u = (x * cos_t + y * sin_t) / _CANVAS
            texture = 60.0 * math.sin(2 * math.pi * (freq * u) + phase_r)
            pixels[x, y] = int(max(0, min(255, base + texture + jitter)))
    return cast("Image", img)


@runtime_checkable
class ImageEmbeddingModel(Protocol):
    """An image embedder: a stable ``name`` plus a batch ``embed`` over PIL images."""

    name: str

    def embed(self, images: list[Any]) -> list[list[float]]:
        """Return one vector per input image, in order."""
        ...


def _image_grid(dim: int) -> int:
    if dim < 1:
        raise ConfigError(f"imagehash dim must be positive, got {dim}")
    grid = round(math.sqrt(dim))
    if grid * grid != dim:
        raise ConfigError(f"imagehash dim {dim} must be a perfect square (e.g. 16, 64, 256)")
    return grid


class ImageHashEmbedding:
    """A deterministic, offline perceptual-hash image embedder (the image ``hash-<dim>``).

    Downsamples each image to ``grid x grid`` grayscale (``grid = sqrt(dim)``),
    mean-centres and L2-normalises the pixels. Determinism makes it the image embedder for
    unit tests and CI, with no model download, so the multi-modal sweep runs reproducibly.
    Like the text :class:`~sectum_ai.embeddings.HashingEmbedding`, it is *not* a semantic
    model: it does not faithfully reproduce the "stronger embeddings leak more" gradient
    real image embedders show. Sweeping increasing ``dim`` produces a reproducible per-dim
    rate on the synthetic substrate, but that curve is an artifact of the proxy (near-tied
    cosines broken by the sweep's tie-break), not a measurement of embedder strength - the
    real gradient is the opt-in :class:`ClipImageEmbedding` path.
    """

    def __init__(self, dim: int = 64) -> None:
        self._grid = _image_grid(dim)
        self.name = f"imagehash-{dim}"

    def embed(self, images: list[Any]) -> list[list[float]]:
        image_module = _require_pillow()
        resample = image_module.Resampling.LANCZOS
        return [self._hash_one(image, resample) for image in images]

    def _hash_one(self, image: Any, resample: Any) -> list[float]:
        small = image.resize((self._grid, self._grid), resample).convert("L")
        values = [float(pixel) for pixel in small.tobytes()]
        mean = math.fsum(values) / len(values)
        centered = [value - mean for value in values]
        norm = math.sqrt(math.fsum(component * component for component in centered))
        if norm == 0.0:
            return [0.0] * (self._grid * self._grid)
        return [component / norm for component in centered]


class ClipImageEmbedding:
    """A real CLIP image embedder via sentence-transformers (opt-in ``sectum-ai[clip]``).

    CLIP embeds images and text into one space, so it is the natural production
    multi-modal retriever; sweeping two or more CLIP models measures the real
    embedding-strength gradient on actual vectors (unlike the deterministic
    :class:`ImageHashEmbedding` proxy). Runs locally (BYOC-safe): no data leaves the box.
    The default model is ``clip-ViT-B-32``.
    """

    def __init__(self, model_name: str = "clip-ViT-B-32") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:  # pragma: no cover - exercised only without the extra
            raise ConfigError(
                "sentence-transformers is not installed; the CLIP image embedder needs it. "
                'Install the extra with: pip install "sectum-ai[clip]"'
            ) from error
        self.name = f"clip:{model_name}"
        self._model = SentenceTransformer(model_name)

    def embed(self, images: list[Any]) -> list[list[float]]:  # pragma: no cover - opt-in live
        vectors = self._model.encode(images, convert_to_numpy=True, normalize_embeddings=False)
        return [[float(value) for value in row] for row in vectors]


def resolve_image_embedding_model(spec: str) -> ImageEmbeddingModel | None:
    """Resolve an image-embedding spec to a model, or ``None`` if it is not one.

    - ``imagehash-<dim>`` -> :class:`ImageHashEmbedding` (deterministic, offline; CI/demo default)
    - ``clip:<model>`` -> :class:`ClipImageEmbedding` (real CLIP via sentence-transformers)

    Returns ``None`` for a spec that is not an image model (e.g. a text ``st:`` spec),
    so a caller can fall through to the text resolver.
    """
    if spec.startswith(("imagehash-", "imagehash:")):
        return ImageHashEmbedding(_imagehash_dim(spec))
    if spec.startswith("clip:"):
        return ClipImageEmbedding(spec[len("clip:") :])
    return None


def validate_image_embedding_spec(spec: str) -> None:
    """Validate an image-embedding spec at config-load time (side-effect-free).

    Accepts ``imagehash-<dim>`` and ``clip:<model>``; the install/model load is deferred
    to :func:`resolve_image_embedding_model`. Raises :class:`ConfigError` on a bare
    ``clip:`` (no model) or a malformed ``imagehash`` dim.
    """
    if spec.startswith("clip:"):
        if not spec[len("clip:") :]:
            raise ConfigError(f"image-embedding spec {spec!r} is missing a model name")
        return
    if spec.startswith(("imagehash-", "imagehash:")):
        _image_grid(_imagehash_dim(spec))
        return
    raise ConfigError(
        f"unknown image-embedding spec {spec!r}; expected imagehash-<dim> or clip:<model>"
    )


def _imagehash_dim(spec: str) -> int:
    """Parse ``imagehash-<int>`` / ``imagehash:<int>`` -> dim (both prefixes are 10 chars).

    Slices off the fixed-length prefix (not ``split('-')``, which would read
    ``imagehash:-4`` as dim 4), and rejects a non-positive dim here so ``imagehash-0`` /
    ``imagehash--4`` raise a ``ConfigError`` at validation time rather than a bare
    ``ValueError`` from ``math.sqrt`` later - mirroring the text ``_hash_dim`` guard.
    """
    try:
        dim = int(spec[len("imagehash-") :])
    except ValueError as error:
        raise ConfigError(f"malformed imagehash spec {spec!r}; expected imagehash-<dim>") from error
    if dim < 1:
        raise ConfigError(f"imagehash dim must be positive, got {dim}")
    return dim


class _ImageItem:
    """One entry in the multi-modal shared index: an image plus its marker-bearing payload."""

    __slots__ = ("entity", "image", "payload", "tenant_ordinal")

    def __init__(self, tenant_ordinal: int, entity: str | None, image: Any, payload: str) -> None:
        self.tenant_ordinal = tenant_ordinal
        self.entity = entity  # None for a filler (no marker)
        self.image = image
        self.payload = payload


def _multimodal_corpus(substrate: Substrate) -> list[_ImageItem]:
    """Build the shared image index: one pivot image per (tenant, marker) plus fillers.

    Each of a tenant's markers is assigned a shared visual entity (round-robin over
    :data:`VISUAL_ENTITIES`), rendered as that tenant's variant of the entity, and its
    payload carries the marker plaintext - so a benign query for the entity retrieves
    foreign tenants' pivot images and the detection pipeline confirms the foreign marker.
    Filler images carry no marker and act as distractors.
    """
    from sectum_ai.probes import VISUAL_ENTITIES

    items: list[_ImageItem] = []
    for ordinal, tenant in enumerate(substrate.tenants):
        markers = [m for m in substrate.manifest.markers if m.owner_tenant_id == tenant.tenant_id]
        for index, marker in enumerate(markers):
            entity = VISUAL_ENTITIES[index % len(VISUAL_ENTITIES)]
            payload = f"Image record depicting {entity}. Reference: {marker.plaintext}."
            items.append(
                _ImageItem(ordinal, entity, render_entity_image(entity, ordinal + 1), payload)
            )
        for filler in range(_FILLERS_PER_TENANT):
            key = f"filler-{ordinal}-{filler}"
            payload = f"Routine {key} image; no reference on file."
            items.append(_ImageItem(ordinal, None, render_entity_image(key, 0), payload))
    return items


def multimodal_provider_sweep(
    substrate: Substrate, models: Sequence[ImageEmbeddingModel]
) -> dict[str, float]:
    """Run the multi-modal bleed under each image model; return the per-model image-RPR.

    Mirrors :func:`sectum_ai.sweep.embedding_provider_sweep` for images: each model
    embeds the shared image index and one benign image query per (principal, visual
    entity), retrieves the top-k by cosine across all tenants, and the rate is the
    fraction of benign queries that surfaced a foreign tenant's marker. Documents and
    queries are each embedded in one batch per model.
    """
    rates, _ = _sweep(substrate, models)
    return rates


def multimodal_pivot_counts(
    substrate: Substrate, models: Sequence[ImageEmbeddingModel]
) -> dict[str, tuple[int, int]]:
    """The binomial ``(k, n)`` behind each model's image-RPR (for a Wilson interval).

    ``n`` is the number of benign cross-tenant image queries and ``k`` how many surfaced
    a foreign marker, so ``k / n`` is exactly :func:`multimodal_provider_sweep`'s rate.
    """
    _, counts = _sweep(substrate, models)
    return counts


def _sweep(
    substrate: Substrate, models: Sequence[ImageEmbeddingModel]
) -> tuple[dict[str, float], dict[str, tuple[int, int]]]:
    # Import here to keep the import graph acyclic at module load (ADR-0004: core
    # depends on probes; runner supplies the shared Retrieval-Pivot metrics).
    from sectum_ai.probes import MultimodalRagBleedProbe
    from sectum_ai.runner import (
        StepResult,
        payload_int,
        retrieval_pivot_counts,
        retrieval_pivot_rate,
    )
    from sectum_ai.spec import Observation, Surface

    probe = MultimodalRagBleedProbe()
    steps = probe.plan(substrate)
    corpus = _multimodal_corpus(substrate)
    rates: dict[str, float] = {}
    counts: dict[str, tuple[int, int]] = {}
    for model in models:
        item_vectors = model.embed([item.image for item in corpus])
        index = list(zip(corpus, item_vectors, strict=True))
        query_vectors = model.embed(
            [render_entity_image(step.payload["query"], 0) for step in steps]
        )
        results: list[StepResult] = []
        for step, query_vector in zip(steps, query_vectors, strict=True):
            k = payload_int(step, "k", str(_TOP_K))
            # Break cosine ties by a neutral content hash, not the payload string. The
            # deterministic imagehash proxy leaves many images near-tied on cosine, and a
            # payload-text tie-break would rank the "Image record ..." pivots above the
            # "Routine ..." fillers purely alphabetically - a sort artifact masquerading as
            # a leak. A hash tie-break keeps ties pivot/filler-neutral (a real embedder
            # separates them on cosine and rarely ties, so this only shapes the proxy).
            ranked = sorted(
                index,
                key=lambda scored: (-cosine(query_vector, scored[1]), _digest(scored[0].payload)),
            )[:k]
            observation = Observation(
                step_id=step.step_id,
                surface=Surface.VECTOR_DB,
                raw_response="\n".join(item.payload for item, _ in ranked),
            )
            results.append((step, probe.detect(step, observation, substrate)))
        rates[model.name] = retrieval_pivot_rate(results)
        counts[model.name] = retrieval_pivot_counts(results)
    return rates, counts
