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


def test_resolve_cohere_without_the_extra_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="cohere"):
        resolve_embedding_model("cohere:embed-english-v3.0")


def test_resolve_voyage_without_the_extra_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="voyageai"):
        resolve_embedding_model("voyage:voyage-3")


def test_validate_accepts_the_hosted_provider_prefixes() -> None:
    from sectum_ai.embeddings import validate_embedding_spec

    # side-effect-free: accepted at config time, the install/key checked lazily
    for spec in ("cohere:embed-english-v3.0", "voyage:voyage-3"):
        validate_embedding_spec(spec)


def test_validate_rejects_an_unknown_prefix_and_names_the_options() -> None:
    from sectum_ai.embeddings import validate_embedding_spec

    with pytest.raises(ConfigError, match="cohere:<model>, or voyage:<model>"):
        validate_embedding_spec("mystery:model")


def test_cohere_vectors_parses_a_v1_list_and_a_v5_by_type_response() -> None:
    from types import SimpleNamespace

    from sectum_ai.embeddings import CohereEmbedding

    # v1-style: embeddings is a plain list of vectors (ints coerced to float)
    v1 = SimpleNamespace(embeddings=[[1, 2], [3, 4]])
    assert CohereEmbedding._vectors(v1) == [[1.0, 2.0], [3.0, 4.0]]
    # v5 by-type: vectors nested under .float_ (the reserved-name field the real
    # SDK exposes)
    v5 = SimpleNamespace(embeddings=SimpleNamespace(float_=[[0.5, 0.6]]))
    assert CohereEmbedding._vectors(v5) == [[0.5, 0.6]]
    # forward-compat: a future/un-suffixed .float accessor is also handled (the
    # parser tries float_ then float), so a client rename does not break the sweep
    v5b = SimpleNamespace(embeddings=SimpleNamespace(float=[[0.7, 0.8]]))
    assert CohereEmbedding._vectors(v5b) == [[0.7, 0.8]]


def test_cohere_vectors_raises_when_no_vectors_are_returned() -> None:
    from types import SimpleNamespace

    from sectum_ai.embeddings import CohereEmbedding

    with pytest.raises(ConfigError):
        CohereEmbedding._vectors(SimpleNamespace(embeddings=None))


def test_voyage_vectors_parses_the_embeddings_attribute() -> None:
    from types import SimpleNamespace

    from sectum_ai.embeddings import VoyageEmbedding

    response = SimpleNamespace(embeddings=[[1, 2, 3]])
    assert VoyageEmbedding._vectors(response) == [[1.0, 2.0, 3.0]]


def test_voyage_embed_chunks_beyond_the_per_request_cap() -> None:
    # Voyage caps a single embed request and does not auto-batch, so a whole-corpus
    # embed must be split into <=128-text calls - one vector per input, in order.
    from types import SimpleNamespace

    from sectum_ai.embeddings import VoyageEmbedding

    class _FakeVoyage:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def embed(self, texts: list[str], *, model: str, input_type: str) -> object:
            self.batch_sizes.append(len(texts))
            # a deterministic 1-d vector per text so order can be checked
            return SimpleNamespace(embeddings=[[float(len(t))] for t in texts])

    client = _FakeVoyage()
    texts = [f"text-{i}" for i in range(300)]
    vectors = VoyageEmbedding._embed_batched(client, "voyage-3", texts)
    assert len(vectors) == 300  # one vector per input
    assert max(client.batch_sizes) == 128  # a full batch is actually used (not < cap)
    assert client.batch_sizes == [128, 128, 44]  # 300 split into <=128 chunks, in order
    assert sum(client.batch_sizes) == 300  # every text embedded exactly once
    assert vectors[0] == [float(len("text-0"))] and vectors[-1] == [float(len("text-299"))]


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
