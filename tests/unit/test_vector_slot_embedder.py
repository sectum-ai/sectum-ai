"""The vector slot can be driven by a real embedding model (Phase 1).

Every live vector store used to be backed by the CLI's 64-dim bag-of-tokens
`_hashing_embed`, with no config path to a real model. So against any live store
the flagship Class 2 Retrieval-Pivot measured LEXICAL bleed - and the paper's
central finding is that STRONGER embeddings leak MORE, an effect a bag-of-tokens
counter cannot exhibit.

The embedder belongs to the customer's store, not to Sectum: a real index was
built with the customer's model, so Sectum must upsert the synthetic corpus in
that same geometry. It is therefore configured on the vector adapter and is
independent of `detection.embedder`, which is Sectum's own choice for grading.
"""

from pathlib import Path

import pytest

from sectum_ai.adapters import Capability
from sectum_ai.config import AdapterConfig, SectumConfig, build_vector_store
from sectum_ai.embeddings import EmbedderBridge, HashingEmbedding, is_hosted_embedding_spec
from sectum_ai.spec import ConfigError


def _opensearch(**extra: object) -> AdapterConfig:
    # OpenSearch constructs offline (opensearchpy opens no connection until a
    # request), so the live path is checkable without a cluster.
    return AdapterConfig(kind="opensearch", host="example", port=9200, **extra)


def test_without_an_embedder_a_live_store_keeps_the_hashing_default() -> None:
    # Unchanged behaviour: no `embedder` key means the deterministic 64-dim
    # hashing embedder, so existing configs and their reproducibility are intact.
    store = build_vector_store(_opensearch())
    assert store.embedder_name == "hashing-64", store.embedder_name


def test_a_configured_embedder_drives_the_store_in_its_own_dimension() -> None:
    # Five of the eight live kinds take an explicit `dim`, hardcoded to 64. A real
    # model has its own fixed output dimension, so it must flow from the embedder
    # into the store - otherwise every upsert fails, or worse, silently pads.
    from sectum_ai.adapters.vector.opensearch import OpenSearchVectorStore

    store = build_vector_store(_opensearch(embedder="hash-128"))
    assert store.embedder_name == "hash-128", store.embedder_name
    assert isinstance(store, OpenSearchVectorStore)
    # The dimension the index is created with, and the width the store actually
    # embeds at - both must be the model's, not the hardcoded 64.
    assert store._dim == 128, store._dim
    assert len(store._embed("a sample passage")) == 128


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ("nonsense", "unknown embedding model"),
        ("openai:", "missing a model name"),
        ("fake-mini", "sweep recall name"),
    ],
)
def test_an_unusable_embedder_spec_is_refused_at_build_time(spec: str, reason: str) -> None:
    # `fake-*` is a sweep RECALL name, not an embedding model: it has no vectors
    # to give a store, so accepting it would build a store that cannot rank. The
    # reason is pinned too: calling `nonsense` a recall name sends the operator
    # looking for a sweep they never configured.
    with pytest.raises(ConfigError, match=reason):
        build_vector_store(_opensearch(embedder=spec))


def test_an_embedder_on_the_built_in_fake_store_is_refused() -> None:
    # The fake does not embed, so an `embedder` on it would change nothing while
    # reading as if the run had been driven by that model.
    from sectum_ai.config import build_vector_slot

    config = SectumConfig.model_validate(
        {"adapters": {"vector_store": {"kind": "fake", "embedder": "hash-128"}}}
    )
    with pytest.raises(ConfigError, match="does not read: embedder"):
        build_vector_slot(config)


def test_semantic_retrieval_stays_withdrawn_in_phase_1_even_with_a_real_embedder() -> None:
    # The capability gates Classes 6 and 13. It is deliberately NOT advertised yet:
    # Class 13 retrieves by IMAGE similarity and needs a multimodal embedder a text
    # model cannot provide, and Class 6's `AML.T0024.001` attribution is under
    # review. Advertising it would let both run where neither can be honest, so
    # they keep reading NOT_COVERED. Class 2 does not gate on it - it just queries,
    # and its retrieval quality now comes from the configured model.
    store = build_vector_store(_opensearch(embedder="hash-128"))
    assert not store.supports(Capability.SEMANTIC_RETRIEVAL)


def test_the_bridge_batches_a_prefetched_corpus_into_few_calls() -> None:
    # Every live store calls its embedder once per document inside `upsert`, so a
    # hosted model meant ~2,000 sequential network calls for the default corpus.
    # The CLI knows the corpus before it upserts, so the bridge embeds it in
    # batches up front and serves the per-document calls from cache.
    calls: list[int] = []

    class _Counting(HashingEmbedding):
        def embed(self, texts: list[str]) -> list[list[float]]:
            calls.append(len(texts))
            return super().embed(texts)

    bridge = EmbedderBridge(_Counting("hash-32", dim=32), batch_size=10)
    corpus = [f"document {i}" for i in range(25)]
    bridge.prefetch(corpus)
    assert calls == [10, 10, 5], calls  # three batches, not 25 calls
    for text in corpus:
        bridge(text)
    assert calls == [10, 10, 5], "a prefetched text was embedded again"
    bridge("a query nobody prefetched")
    assert calls[-1] == 1, "an unseen query still embeds on demand"
    assert bridge.dim == 32


@pytest.mark.parametrize(
    ("spec", "hosted"),
    [
        ("openai:text-embedding-3-small", True),
        ("cohere:embed-english-v3.0", True),
        ("voyage:voyage-3", True),
        ("bedrock:amazon.titan-embed-text-v2:0", True),
        ("st:all-mpnet-base-v2", False),
        ("hash-128", False),
    ],
)
def test_hosted_specs_are_told_apart_from_local_ones(spec: str, hosted: bool) -> None:
    assert is_hosted_embedding_spec(spec) is hosted


def _local(**overrides: object) -> dict[str, object]:
    return {"detection": {"mode": "local"}, **overrides}


def test_byoc_local_mode_refuses_a_hosted_vector_slot_embedder() -> None:
    # `detection.mode: local` is the "no data leaves the box" guarantee. The vector
    # slot embeds the WHOLE CORPUS, so a hosted embedder there is the largest
    # egress in the product - and the gate, being a validator on `DetectionConfig`,
    # never saw it.
    with pytest.raises(ValueError, match="vector_store"):
        SectumConfig.model_validate(
            _local(adapters={"vector_store": {"kind": "opensearch", "embedder": "openai:x"}})
        )


def test_byoc_local_mode_refuses_hosted_scenario_embedding_models() -> None:
    # The pre-existing hole this closes: `scenario.embedding_models` feeds the
    # Class 2 sweep, which embeds the corpus with each listed model, and the gate
    # ignored it entirely - so `mode: local` failed open silently.
    with pytest.raises(ValueError, match="embedding_models"):
        SectumConfig.model_validate(
            _local(scenario={"embedding_models": ["cohere:embed-english-v3.0"]})
        )


def test_byoc_local_mode_still_accepts_local_embedders() -> None:
    # The false-alarm half: sentence-transformers runs on the box, so it is the
    # real embedder a zero-egress deployment should be able to use.
    SectumConfig.model_validate(
        _local(
            adapters={"vector_store": {"kind": "opensearch", "embedder": "st:all-mpnet-base-v2"}},
            scenario={"embedding_models": ["hash-128", "st:all-MiniLM-L6-v2"]},
        )
    )


def test_the_probe_run_records_the_geometry_its_store_actually_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Read off the store the run DROVE, not off the config, so it cannot drift from
    # what happened. A built-in fake records None, which is indistinguishable from a
    # wiring bug that reads the wrong variable - so this drives a store that carries
    # a name and checks the signed record says the same.
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.config import build_adapters as real_build

    def _named(loaded: SectumConfig) -> object:
        bundle = real_build(loaded)
        bundle.vector.embedder_name = "st:all-mpnet-base-v2"
        return bundle

    monkeypatch.setattr("sectum_ai.cli.app.build_adapters", _named)
    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    record = json.loads((tmp_path / "run.json").read_text())
    assert record["vector_embedder"] == "st:all-mpnet-base-v2", record.get("vector_embedder")


@pytest.mark.parametrize(
    ("scope", "expected"),
    [("vector_db", "st:all-mpnet-base-v2"), ("tracing", None)],
)
def test_the_erasure_run_records_the_geometry_only_when_it_scanned_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str, expected: str | None
) -> None:
    # The erasure record is the probe record's sibling, so it carries the same
    # field - scoped like its surface provenance: a run that never scanned the
    # vector surface says nothing about the geometry the store ranks in.
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.config import build_vector_slot as real_build

    def _named(*args: object, **kwargs: object) -> object:
        store = real_build(*args, **kwargs)  # type: ignore[arg-type]
        store.embedder_name = "st:all-mpnet-base-v2"
        return store

    monkeypatch.setattr("sectum_ai.cli.app.build_vector_slot", _named)
    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--scope", scope])
    pack = json.loads((tmp_path / "erasure-evidence.json").read_text())
    assert pack["run_result"]["vector_embedder"] == expected
