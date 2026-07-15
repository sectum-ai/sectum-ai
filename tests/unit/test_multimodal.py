"""Tests for Class 13 multi-modal RAG entity-bleed: image substrate, embedders, sweep, probe."""

import pytest

from sectum_ai.multimodal import (
    ClipImageEmbedding,
    ImageEmbeddingModel,
    ImageHashEmbedding,
    multimodal_pivot_counts,
    multimodal_provider_sweep,
    render_entity_image,
    resolve_image_embedding_model,
    validate_image_embedding_spec,
)
from sectum_ai.probes import VISUAL_ENTITIES, MultimodalRagBleedProbe
from sectum_ai.spec import ConfigError, Observation, ProbeStep, Surface
from sectum_ai.substrate import build_substrate, default_scenario


def _cosine(a: list[float], b: list[float]) -> float:
    from sectum_ai.embeddings import cosine

    return cosine(a, b)


def test_render_is_deterministic_and_entity_specific() -> None:
    same_a = render_entity_image("bar-chart", 1).tobytes()
    same_b = render_entity_image("bar-chart", 1).tobytes()
    assert same_a == same_b  # same (entity, variant) -> byte-identical (reproducibility)
    # a different entity, and a different variant of the same entity, both differ
    assert render_entity_image("org-logo", 1).tobytes() != same_a
    assert render_entity_image("bar-chart", 2).tobytes() != same_a


def test_imagehash_embedding_satisfies_the_protocol_and_dims() -> None:
    model = ImageHashEmbedding(64)
    assert isinstance(model, ImageEmbeddingModel)
    assert model.name == "imagehash-64"
    [vector] = model.embed([render_entity_image("bar-chart")])
    assert len(vector) == 64  # grid 8x8 -> 64-dim


def test_imagehash_dim_must_be_a_perfect_square() -> None:
    with pytest.raises(ConfigError):
        ImageHashEmbedding(50)


def test_imagehash_of_a_uniform_image_is_the_zero_vector() -> None:
    # A flat image mean-centres to all zeros (norm 0) -> the zero vector, not a divide.
    from PIL import Image

    [vector] = ImageHashEmbedding(16).embed([Image.new("L", (64, 64), 128)])
    assert vector == [0.0] * 16


def test_imagehash_same_entity_is_nearer_than_a_different_entity() -> None:
    # The retrieval-pivot premise: two tenants' images of the SAME visual entity embed
    # closer than images of different entities, so a benign query pivots cross-tenant.
    model = ImageHashEmbedding(256)
    query, same_entity, other_entity = model.embed(
        [
            render_entity_image("bar-chart", 0),
            render_entity_image("bar-chart", 3),
            render_entity_image("org-logo", 3),
        ]
    )
    assert _cosine(query, same_entity) > _cosine(query, other_entity)


def test_resolve_image_embedding_model_dispatches() -> None:
    assert isinstance(resolve_image_embedding_model("imagehash-64"), ImageHashEmbedding)
    assert resolve_image_embedding_model("imagehash:16").name == "imagehash-16"  # type: ignore[union-attr]
    # a text spec is not an image model -> None (the caller falls through to text)
    assert resolve_image_embedding_model("st:all-mpnet-base-v2") is None
    with pytest.raises(ConfigError):
        resolve_image_embedding_model("imagehash-not-a-number")
    # a clip: spec dispatches to the CLIP adapter, which errors without the extra
    with pytest.raises(ConfigError, match="sentence-transformers"):
        resolve_image_embedding_model("clip:clip-ViT-B-32")


def test_imagehash_rejects_a_nonpositive_or_negative_dim() -> None:
    # A non-positive dim must raise ConfigError (the SectumError hierarchy the CLI maps to
    # exit code 3), not a bare ValueError from math.sqrt - via the class, resolve, and
    # validate paths. `imagehash:-4` must not silently parse as dim 4.
    with pytest.raises(ConfigError):
        ImageHashEmbedding(0)
    for spec in ("imagehash-0", "imagehash--4", "imagehash:-4"):
        with pytest.raises(ConfigError):
            resolve_image_embedding_model(spec)
        with pytest.raises(ConfigError):
            validate_image_embedding_spec(spec)


def test_resolve_clip_without_the_extra_is_a_config_error() -> None:
    # sentence-transformers is not installed in the default test environment.
    with pytest.raises(ConfigError, match="sentence-transformers"):
        ClipImageEmbedding("clip-ViT-B-32")


def test_validate_image_embedding_spec() -> None:
    validate_image_embedding_spec("imagehash-256")
    validate_image_embedding_spec("clip:clip-ViT-B-32")
    with pytest.raises(ConfigError, match="missing a model name"):
        validate_image_embedding_spec("clip:")
    with pytest.raises(ConfigError, match="unknown image-embedding spec"):
        validate_image_embedding_spec("mystery:model")


def test_sweep_is_deterministic_and_counts_match_rates() -> None:
    # The imagehash sweep is a DETERMINISTIC OFFLINE PROXY: these exact rates are a
    # regression lock on the synthetic substrate, not a claim about real embedder
    # strength (the imagehash curve is a substrate/tie-break artifact - the genuine
    # "stronger embedders leak more" gradient is the CLIP path). The demo ladder
    # [16, 64, 256] is deliberately chosen to be monotone; other perfect-square dims
    # (e.g. 49, 144) dip, so monotonicity is a property of this ladder, not the embedder.
    substrate = build_substrate(default_scenario(seed=2026))
    specs = ["imagehash-16", "imagehash-64", "imagehash-256"]
    real = [m for spec in specs if (m := resolve_image_embedding_model(spec)) is not None]
    rates = multimodal_provider_sweep(substrate, real)
    counts = multimodal_pivot_counts(substrate, real)
    n = len(VISUAL_ENTITIES) * len(substrate.principals())
    assert counts["imagehash-16"] == (11, n)
    assert counts["imagehash-64"] == (23, n)
    assert counts["imagehash-256"] == (24, n)
    for m in real:
        k, total = counts[m.name]
        assert total == n
        assert rates[m.name] == pytest.approx(k / total)


def test_probe_plans_one_benign_image_query_per_visual_entity_and_principal() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = MultimodalRagBleedProbe().plan(substrate)
    assert len(steps) == len(VISUAL_ENTITIES) * len(substrate.principals())
    assert all(step.action == "vector.query" for step in steps)
    assert {step.payload["query"] for step in steps} == set(VISUAL_ENTITIES)


def test_probe_detect_flags_a_foreign_marker_and_ignores_own() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    probe = MultimodalRagBleedProbe()
    tenant_a = substrate.tenants[0].tenant_id
    foreign_marker = next(m for m in substrate.manifest.markers if m.owner_tenant_id != tenant_a)
    own_marker = next(m for m in substrate.manifest.markers if m.owner_tenant_id == tenant_a)
    step = ProbeStep(
        step_id="multimodal-rag-bleed-0000",
        probe_id=probe.id,
        actor_tenant_id=tenant_a,
        action="vector.query",
        payload={"query": "bar-chart", "k": "5"},
    )
    foreign_obs = Observation(
        step_id=step.step_id,
        surface=Surface.VECTOR_DB,
        raw_response=f"Image record depicting bar-chart. Reference: {foreign_marker.plaintext}.",
    )
    assert probe.detect(step, foreign_obs, substrate)  # a foreign canary is a confirmed leak
    own_obs = Observation(
        step_id=step.step_id,
        surface=Surface.VECTOR_DB,
        raw_response=f"Image record depicting bar-chart. Reference: {own_marker.plaintext}.",
    )
    assert not probe.detect(step, own_obs, substrate)  # the observer's own marker is not a leak
