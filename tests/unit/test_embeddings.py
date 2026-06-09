"""Tests for the embedding models and the real-provider sweep (the spec, sections 7 and 13)."""

import math

import pytest

from sectum_ai.embeddings import (
    EmbeddingModel,
    HashingEmbedding,
    cosine,
    resolve_embedding_model,
)
from sectum_ai.spec import ConfigError
from sectum_ai.substrate import build_substrate, default_scenario
from sectum_ai.sweep import embedding_provider_sweep


def test_hashing_embedding_satisfies_the_protocol() -> None:
    assert isinstance(HashingEmbedding(), EmbeddingModel)


def test_hashing_embedding_is_deterministic() -> None:
    model = HashingEmbedding(dim=64)
    assert model.embed(["Acme Robotics SOC 2"]) == model.embed(["Acme Robotics SOC 2"])


def test_hashing_embedding_returns_unit_vectors() -> None:
    [vector] = HashingEmbedding(dim=64).embed(["a shared vendor and a person"])
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-9)
    assert len(vector) == 64


def test_hashing_embedding_empty_text_is_the_zero_vector() -> None:
    [vector] = HashingEmbedding(dim=16).embed(["...!!!"])
    assert vector == [0.0] * 16


def test_hashing_embedding_rejects_a_nonpositive_dim() -> None:
    with pytest.raises(ConfigError):
        HashingEmbedding(dim=0)


def test_cosine_identical_is_one_orthogonal_and_zero_are_zero() -> None:
    assert math.isclose(cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_is_scale_invariant() -> None:
    assert math.isclose(cosine([1.0, 1.0], [3.0, 3.0]), 1.0)


def test_resolve_hashing_specs() -> None:
    dashed = resolve_embedding_model("hash-128")
    colon = resolve_embedding_model("hash:64")
    assert dashed is not None and dashed.name == "hash-128"
    assert colon is not None and colon.name == "hash:64"


def test_resolve_malformed_hashing_spec_raises() -> None:
    with pytest.raises(ConfigError):
        resolve_embedding_model("hash-not-a-number")


def test_resolve_legacy_fake_name_is_none() -> None:
    # The fake-* names are modelled by FakeVectorStore recall, not real embeddings.
    assert resolve_embedding_model("fake-deterministic") is None
    assert resolve_embedding_model("fake-mini") is None


def test_resolve_sentence_transformer_without_the_extra_is_a_config_error() -> None:
    # The opt-in extra is not installed in the default test environment.
    with pytest.raises(ConfigError, match="sentence-transformers"):
        resolve_embedding_model("st:all-mpnet-base-v2")


def test_resolve_openai_without_the_extra_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="openai"):
        resolve_embedding_model("openai:text-embedding-3-small")


def test_embedding_provider_sweep_is_deterministic_and_bounded() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    models = [HashingEmbedding("hash-32", dim=32), HashingEmbedding("hash-256", dim=256)]
    first = embedding_provider_sweep(substrate, models)
    assert first == embedding_provider_sweep(substrate, models)
    assert set(first) == {"hash-32", "hash-256"}
    assert all(0.0 <= rate <= 1.0 for rate in first.values())


def test_embedding_provider_sweep_reflects_real_cosine_retrieval() -> None:
    # A higher-dimension hashing embedder collides less, so it retrieves more of
    # the cross-tenant pivot documents and records a higher Retrieval-Pivot Rate.
    # The gradient comes from real cosine similarity, not a modelled recall knob.
    substrate = build_substrate(default_scenario(seed=2026))
    rates = embedding_provider_sweep(
        substrate, [HashingEmbedding("hash-32", dim=32), HashingEmbedding("hash-256", dim=256)]
    )
    assert rates["hash-32"] < rates["hash-256"]


def test_validate_embedding_spec_rejects_a_non_positive_hash_dim() -> None:
    # hash-0 / hash--3 passed config-time validation and failed only at sweep
    # time (HashingEmbedding's own constructor), defeating the early check.
    from sectum_ai.embeddings import validate_embedding_spec
    from sectum_ai.spec import ConfigError

    for bad in ("hash-0", "hash--3"):
        with pytest.raises(ConfigError):
            validate_embedding_spec(bad)
