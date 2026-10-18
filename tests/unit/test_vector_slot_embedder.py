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
from sectum_ai.adapters.fakes import FakeVectorStore
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
        # Fail closed: a provider nobody classified is hosted.
        ("gemini:text-embedding-004", True),
        ("st:all-mpnet-base-v2", False),
        ("hash-128", False),
        ("hash:64", False),
        # `calibrate --embedder fake` names the offline fake by the bare word;
        # refusing it told a BYOC operator the most local option sent data off box.
        ("fake", False),
        ("fake-deterministic", False),
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
    text = runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    record = json.loads((tmp_path / "run.json").read_text())
    assert record["vector_embedder"] == "st:all-mpnet-base-v2", record.get("vector_embedder")
    # Every renderer of the rate names its geometry, not just the signed record.
    assert "vector-store steps ranked by: st:all-mpnet-base-v2" in text.output, text.output
    summary = runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--output", "json"])
    payload = json.loads(summary.stdout)
    assert payload["vector_embedder"] == "st:all-mpnet-base-v2"
    assert payload["vector_embedder_note"] is None


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


class _Modes(HashingEmbedding):
    """Records which mode each text was embedded in."""

    def __init__(self) -> None:
        super().__init__("hash-16", dim=16)
        self.documents: list[str] = []
        self.queries: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return super().embed(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        self.queries.extend(texts)
        return super().embed(texts)


def _bridged_store(bridge: EmbedderBridge) -> FakeVectorStore:
    """A built-in fake carrying ``bridge``, as the CLI's helpers receive a store."""
    store = FakeVectorStore()
    store.embedder_bridge = bridge
    return store


def test_only_registered_queries_embed_in_query_mode() -> None:
    # The store embeds documents and queries through one callable, so the bridge
    # cannot tell them apart by the call. Defaulting an unknown text to QUERY mode
    # indexed Class 3's mid-run poison documents as queries - in the wrong half of
    # an asymmetric space. Unknown texts are documents; planned queries are
    # registered.
    model = _Modes()
    bridge = EmbedderBridge(model)
    bridge.prefetch(["acme payroll", "globex contract"])
    bridge.prefetch_queries(["who owns the contract", "who owns the contract"])
    bridge("acme payroll")  # the upsert: served from the document cache
    bridge("who owns the contract")  # a planned query: served from the query cache
    bridge("a poison document planted mid-run")  # unknown: embedded as a document
    assert model.documents == [
        "acme payroll",
        "globex contract",
        "a poison document planted mid-run",
    ]
    assert model.queries == ["who owns the contract"]


def test_the_probe_registers_every_planned_vector_query() -> None:

    from sectum_ai.cli.app import _build_suite, _prefetch_queries
    from sectum_ai.config import DetectionConfig, build_detection_providers
    from sectum_ai.substrate import build_substrate, default_scenario

    substrate = build_substrate(default_scenario(seed=2026))
    suite = _build_suite(build_detection_providers(DetectionConfig()))
    model = _Modes()
    _prefetch_queries(_bridged_store(EmbedderBridge(model)), suite, substrate)
    planned = {
        step.payload["query"]
        for probe in suite
        for step in probe.plan(substrate)
        if step.action == "vector.query"
    }
    assert planned
    assert set(model.queries) == planned


def test_a_provider_failure_is_a_typed_adapter_error_that_does_not_echo_the_sdk() -> None:
    # An SDK's own exception escaped the CLI's typed handler as a traceback and
    # exit 1; its message can also echo part of the API key.
    from sectum_ai.spec import AdapterError

    class _Revoked(HashingEmbedding):
        def embed(self, texts: list[str]) -> list[list[float]]:
            # Split so secret scanning does not flag the synthetic key.
            raise RuntimeError("Incorrect API key provided: " + "sk-" + "proj-abc123")

    bridge = EmbedderBridge(_Revoked("hash-16", dim=16))
    with pytest.raises(AdapterError) as caught:
        bridge.prefetch(["a document"])
    assert "sk-proj" not in str(caught.value)
    assert "RuntimeError" in str(caught.value)


def _local_config(tmp_path: Path) -> Path:
    path = tmp_path / "local.yaml"
    path.write_text("detection:\n  mode: local\n")
    return path


def test_byoc_local_mode_refuses_hosted_specs_that_bypass_the_config(tmp_path: Path) -> None:
    # The config validator only sees the config. `probe` sweeps the list fixed into
    # the substrate at seed time, and `seed`/`calibrate` take overrides - each of
    # which passed a `local` config untouched and sent the corpus to the provider.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    runner = CliRunner()
    local = str(_local_config(tmp_path))
    hosted = ["--embedding-model", "openai:text-embedding-3-small"]
    seeded = runner.invoke(
        app, ["seed", "--workdir", str(tmp_path / "a"), "--config", local, *hosted]
    )
    assert seeded.exit_code == 3, seeded.output
    assert "--embedding-model" in seeded.output

    # Seeded under a hosted config, then probed under the local one.
    workdir = str(tmp_path / "b")
    assert runner.invoke(app, ["seed", "--workdir", workdir, *hosted]).exit_code == 0
    probed = runner.invoke(app, ["probe", "--workdir", workdir, "--config", local])
    assert probed.exit_code == 3, probed.output
    assert "seeded scenario" in probed.output
    assert not (tmp_path / "b" / "run.json").exists()

    calibrated = runner.invoke(
        app, ["calibrate", "--config", local, "--embedder", "cohere:embed-english-v3.0"]
    )
    assert calibrated.exit_code == 3, calibrated.output
    # Refused for egress, not merely for the provider's extra being absent.
    assert "detection.mode 'local'" in calibrated.output, calibrated.output


def test_byoc_local_mode_refuses_mem0_on_its_default_hosted_embedder() -> None:
    # mem0 defaults its embedder to OpenAI, and every memory write is embedded, so
    # `memory: {kind: mem0}` alone sends tenant content off the box.
    with pytest.raises(ValueError, match="mem0 embedder"):
        SectumConfig.model_validate(_local(adapters={"memory": {"kind": "mem0"}}))
    # Its LLM does not run for Sectum's verbatim (`infer=False`) writes, so without
    # a graph store a default LLM is not egress - refusing it was a false refusal.
    SectumConfig.model_validate(_mem0({"embedder": {"provider": "huggingface"}}))


def test_the_shared_hashing_name_states_the_hashing_embedders_real_dimension() -> None:
    # The PDF explains this name and the resolver records it; both read one
    # constant, which must not drift from the embedder it names.
    from sectum_ai.config import _hashing_embed
    from sectum_ai.spec import HASHING_EMBEDDER_NAME

    assert f"hashing-{len(_hashing_embed('probe text'))}" == HASHING_EMBEDDER_NAME


def _mem0(config: dict[str, object]) -> dict[str, object]:
    return _local(adapters={"memory": {"kind": "mem0", "config": config}})


def test_byoc_local_mode_checks_the_llm_that_feeds_a_graph_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A graph store (one with a `config`) runs an LLM over every write: its own
    # `graph_store.llm`, else the main `llm`, else OpenAI.
    local_embedder = {"provider": "huggingface"}
    neo4j = {"provider": "neo4j", "config": {"url": "bolt://localhost:7687"}}
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="mem0 llm"):
        SectumConfig.model_validate(_mem0({"embedder": local_embedder, "graph_store": neo4j}))
    with pytest.raises(ValueError, match=r"graph_store\.llm"):
        SectumConfig.model_validate(
            _mem0(
                {
                    "llm": {"provider": "ollama"},
                    "embedder": local_embedder,
                    "graph_store": {**neo4j, "llm": {"provider": "openai"}},
                }
            )
        )
    # An OpenAI-compatible server the operator pointed at is local - the same trust
    # `detection`'s base_url gets.
    pointed = {"provider": "openai", "config": {"openai_base_url": "http://localhost:11434/v1"}}
    graphed = {"llm": pointed, "embedder": local_embedder, "graph_store": neo4j}
    SectumConfig.model_validate(_mem0(graphed))
    # Unless mem0's OpenAI LLM will ignore the base URL: with an OpenRouter key in
    # the environment it routes to OpenRouter instead...
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic")
    with pytest.raises(ValueError, match="mem0 llm"):
        SectumConfig.model_validate(_mem0(graphed))
    # ...unless the OpenRouter endpoint is pointed too.
    routed = {"provider": "openai", "config": {"openrouter_base_url": "http://localhost:8080/v1"}}
    SectumConfig.model_validate(_mem0({**graphed, "llm": routed}))
    monkeypatch.delenv("OPENROUTER_API_KEY")


def test_the_probe_command_registers_its_queries_before_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.config import build_adapters as real_build

    model = _Modes()

    def _bridged(loaded: SectumConfig) -> object:
        bundle = real_build(loaded)
        bundle.vector.embedder_bridge = EmbedderBridge(model)
        return bundle

    monkeypatch.setattr("sectum_ai.cli.app.build_adapters", _bridged)
    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert model.queries, "the planned vector queries were never registered"


def _bridged_slot(monkeypatch: pytest.MonkeyPatch, model: _Modes) -> None:
    from sectum_ai.config import build_vector_slot as real_build

    def _bridged(*args: object, **kwargs: object) -> object:
        store = real_build(*args, **kwargs)  # type: ignore[arg-type]
        store.embedder_bridge = EmbedderBridge(model)
        return store

    monkeypatch.setattr("sectum_ai.cli.app.build_vector_slot", _bridged)


def test_both_erasure_modes_register_their_fingerprint_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each erasure mode scans the vector store with similarity queries - the
    # target's document titles, the subject's vector fingerprints. Unregistered,
    # they embedded as documents, which an asymmetric model ranks lower: a residual
    # document fell past top-k and the surface read erased or inconclusive.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import _load_substrate, app

    runner = CliRunner()
    canary = _Modes()
    _bridged_slot(monkeypatch, canary)
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--scope", "vector_db"])
    substrate = _load_substrate(tmp_path)
    target = substrate.tenants[0].tenant_id
    by_id = {doc.doc_id: doc for doc in substrate.documents}
    # Exactly the titles the residue scan queries: those of the documents holding
    # ANY of the target's markers - the probe scans every type, and registering only
    # the hard canaries left the entity and secret canaries in document mode.
    titles = {
        by_id[location.doc_id].title
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == target
        for location in marker.planted_locations
    }
    hard_only = {
        by_id[location.doc_id].title
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == target and marker.marker_type.value == "HARD_CANARY"
        for location in marker.planted_locations
    }
    assert titles != hard_only
    assert set(canary.queries) == titles

    subject = _Modes()
    _bridged_slot(monkeypatch, subject)
    manifest = tmp_path / "subject.yaml"
    manifest.write_text('subject_ref: u\nfingerprints:\n  vector_db: ["a subject phrase"]\n')
    runner.invoke(app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)])
    assert subject.queries == ["a subject phrase"]


def test_a_failure_registering_subject_fingerprints_costs_no_surface_its_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The subject probe contains each surface's failure so one adapter cannot cost
    # every other surface its verdict. Registering the fingerprints up front sat
    # outside that, so a provider blip aborted the whole erasure at exit 3.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    class _QueryModeDown(_Modes):
        def embed_queries(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("rate limited")

    _bridged_slot(monkeypatch, _QueryModeDown())
    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    manifest = tmp_path / "subject.yaml"
    manifest.write_text('subject_ref: u\nfingerprints:\n  vector_db: ["a subject phrase"]\n')
    result = runner.invoke(app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)])
    assert result.exit_code != 3, result.output
    assert "embed on demand" in result.output, result.output
    assert (tmp_path / "erasure-evidence.json").exists()


def test_a_failed_query_registration_still_embeds_those_texts_as_queries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Containing the failure is only safe if the texts keep their mode: falling
    # back to document mode on demand silently under-ranked an erasure scan's
    # queries, which can read a residual document as erased.

    from sectum_ai.cli.app import _register_queries

    class _FlakyQueries(_Modes):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        def embed_queries(self, texts: list[str]) -> list[list[float]]:
            if not self.failed:
                self.failed = True
                raise RuntimeError("rate limited")
            return super().embed_queries(texts)

    model = _FlakyQueries()
    bridge = EmbedderBridge(model)
    _register_queries(_bridged_store(bridge), ["who owns the contract"])
    assert "embed on demand" in capsys.readouterr().err
    bridge("who owns the contract")
    assert model.queries == ["who owns the contract"]
    assert model.documents == []


def test_a_provider_that_fails_to_load_is_a_typed_adapter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A misspelled `st:` model fails its download inside the constructor - outside
    # every call path - and escaped as a raw traceback.
    import sectum_ai.embeddings as embeddings
    from sectum_ai.spec import AdapterError

    def _missing(name: str) -> object:
        raise OSError(f"{name} is not a valid model identifier")

    monkeypatch.setattr(embeddings, "SentenceTransformerEmbedding", _missing)
    with pytest.raises(AdapterError, match="OSError"):
        embeddings.resolve_embedding_model("st:all-mpnet-base-v3")


def test_the_probe_summary_says_a_hashing_geometry_is_lexical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.config import build_adapters as real_build

    def _hashed(loaded: SectumConfig) -> object:
        bundle = real_build(loaded)
        bundle.vector.embedder_name = "hash-128"
        return bundle

    monkeypatch.setattr("sectum_ai.cli.app.build_adapters", _hashed)
    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    text = runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert (
        "vector-store steps ranked by: hash-128 - a deterministic hashing embedder" in text.output
    ), text.output
    import json

    summary = runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--output", "json"])
    assert "shared tokens" in json.loads(summary.stdout)["vector_embedder_note"]


def test_a_run_that_ranked_nothing_names_no_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A suite narrowed to Class 1's by-id fetch measured nothing in any geometry;
    # naming one let an embedder swap gate `diff` as a regression over numbers the
    # swap cannot have moved.
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
    runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--probe", "tenant-boundary-fetch"])
    record = json.loads((tmp_path / "run.json").read_text())
    assert "tenant-boundary-fetch" in record["probe_versions"]
    assert record["vector_embedder"] is None


@pytest.mark.parametrize(
    ("embedder", "expected"),
    [
        ("st:all-mpnet-base-v2", ", vector-store steps ranked by st:all-mpnet-base-v2)"),
        (
            "hashing-64",
            ", vector-store steps ranked by hashing-64 - a deterministic hashing embedder,"
            " which ranks by shared tokens rather than meaning; no embedding model was"
            " configured for the vector store)",
        ),
        (None, "n=10)"),
    ],
)
def test_the_scorecard_headline_names_the_geometry(embedder: str | None, expected: str) -> None:
    # The PDF names the geometry beside the rate; the scorecard showed a rate
    # ranked by shared tokens exactly as one ranked by a production model.
    from sectum_ai.score import CATALOG, _headline
    from sectum_ai.spec import RunMetrics

    class_2 = next(entry for entry in CATALOG if entry.class_id == 2)
    headline = _headline(class_2, RunMetrics(retrieval_pivot_n=10, retrieval_pivot_k=4), embedder)
    assert headline is not None and headline.endswith(expected), headline


def test_a_scored_run_carries_its_geometry_into_the_class_2_line(tmp_path: Path) -> None:
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.score import score_run
    from sectum_ai.spec import RunResult

    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    record = json.loads((tmp_path / "run.json").read_text())
    record["vector_embedder"] = "st:all-mpnet-base-v2"
    score = score_run(RunResult.model_validate(record))
    class_2 = next(line for line in score.classes if line.class_id == 2)
    assert class_2.headline is not None
    assert "vector-store steps ranked by st:all-mpnet-base-v2" in class_2.headline, class_2.headline


def test_only_a_ranking_records_the_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pipeline-end probe asks the RAG pipeline (the built-in fake keeps its own
    # index), and a subject check of record ids only fetches by id: neither ranked
    # over the store, so neither names its geometry.
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
    runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--probe", "rag-pipeline-bleed"])
    record = json.loads((tmp_path / "run.json").read_text())
    assert "rag-pipeline-bleed" in record["probe_versions"]
    assert record["vector_embedder"] is None

    monkeypatch.setattr("sectum_ai.cli.app.build_vector_slot", _with_name("st:all-mpnet-base-v2"))
    for body, expected in (
        ("records:\n  vector_db: [doc-a]\n", None),
        ('fingerprints:\n  vector_db: ["a subject phrase"]\n', "st:all-mpnet-base-v2"),
    ):
        manifest = tmp_path / "subject.yaml"
        manifest.write_text("subject_ref: u\n" + body)
        runner.invoke(app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)])
        pack = json.loads((tmp_path / "erasure-evidence.json").read_text())
        assert pack["run_result"]["vector_embedder"] == expected, body


def _with_name(name: str) -> object:
    from sectum_ai.config import build_vector_slot as real_build

    def _named(*args: object, **kwargs: object) -> object:
        store = real_build(*args, **kwargs)  # type: ignore[arg-type]
        store.embedder_name = name
        return store

    return _named


def test_a_hash_spec_is_recorded_by_its_dim_not_its_spelling() -> None:
    # Two spellings of one geometry tripped [EMBEDDER CHANGED]; the gradient keys
    # by the same canonical spelling.
    names = {
        build_vector_store(_opensearch(embedder=spec)).embedder_name
        for spec in ("hash:64", "hash-64")
    }
    assert names == {"hash-64"}


def test_the_planted_poison_is_batched_as_documents() -> None:
    # Class 3 plants its poison mid-run; each plant embedded on demand, one provider
    # call per document.

    from sectum_ai.cli.app import _build_suite, _prefetch_queries
    from sectum_ai.config import DetectionConfig, build_detection_providers
    from sectum_ai.substrate import build_substrate, default_scenario

    substrate = build_substrate(default_scenario(seed=2026))
    suite = _build_suite(build_detection_providers(DetectionConfig()))
    model = _Modes()
    _prefetch_queries(_bridged_store(EmbedderBridge(model)), suite, substrate)
    planted = {
        f"{step.payload['doc_id']} {step.payload['content']}"
        for probe in suite
        for step in probe.plan(substrate)
        if step.action == "vector.upsert"
    }
    assert planted
    assert set(model.documents) == planted


def test_the_scorecard_names_the_geometry_on_every_similarity_ranked_headline() -> None:
    from sectum_ai.score import CATALOG, _headline
    from sectum_ai.spec import RunMetrics

    metrics = RunMetrics(
        poisoning_bleed_delta=0.5, inversion_reconstruction_rate=0.5, extraction_efficiency=0.5
    )
    for class_id in (3, 6, 10):
        entry = next(entry for entry in CATALOG if entry.class_id == class_id)
        headline = _headline(entry, metrics, "hashing-64")
        assert headline is not None and "ranked by hashing-64" in headline, headline


def test_the_scorecard_names_no_geometry_where_no_similarity_probe_fed_the_class(
    tmp_path: Path,
) -> None:
    # Class 2's rate pools the RAG pipeline's steps, which its own retriever ranked:
    # on a run where only the pipeline-end probe fed it, naming the store's geometry
    # described a ranking that never happened.
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.score import score_run
    from sectum_ai.spec import RunResult

    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--probe", "rag-pipeline-bleed"])
    record = json.loads((tmp_path / "run.json").read_text())
    record["vector_embedder"] = "st:all-mpnet-base-v2"
    score = score_run(RunResult.model_validate(record))
    class_2 = next(line for line in score.classes if line.class_id == 2)
    assert class_2.headline is not None
    assert "ranked by" not in class_2.headline, class_2.headline


def test_a_query_already_indexed_as_a_document_is_not_embedded_again() -> None:
    # It is served as the document either way, so a query-mode call is paid for
    # nothing.
    model = _Modes()
    bridge = EmbedderBridge(model)
    bridge.prefetch(["acme payroll"])
    bridge.prefetch_queries(["acme payroll", "who owns the contract"])
    assert model.queries == ["who owns the contract"]


def test_an_st_model_is_recorded_as_spelled(monkeypatch: pytest.MonkeyPatch) -> None:
    # A bare `st:` name can resolve to a local folder the namespaced one would not,
    # so merging the two could hide a real model change behind a comparison.
    namespaced = "st:sentence-transformers/all-mpnet-base-v2"
    monkeypatch.setattr(
        "sectum_ai.config.resolve_embedding_model",
        lambda spec: HashingEmbedding(spec, dim=32),
    )
    assert build_vector_store(_opensearch(embedder=namespaced)).embedder_name == namespaced


def test_st_models_use_their_own_query_and_document_prompts() -> None:
    # e5-style models ship `query: `/`passage: ` prompts; encoding without them
    # ranks a probe query differently from the production index built with them.
    from sectum_ai.embeddings import SentenceTransformerEmbedding

    calls: list[str | None] = []

    class _Model:
        def __init__(self, prompts: dict[str, str]) -> None:
            self.prompts = prompts

        def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
            calls.append(kwargs.get("prompt_name"))  # type: ignore[arg-type]
            return [[1.0] for _ in texts]

    for prompts, expected in (
        ({"query": "query: ", "passage": "passage: "}, ["passage", "query"]),
        ({}, [None, None]),
    ):
        calls.clear()
        model = SentenceTransformerEmbedding.__new__(SentenceTransformerEmbedding)
        model._model = _Model(prompts)
        model.embed(["a document"])
        model.embed_queries(["a query"])
        assert calls == expected


def test_a_failed_plant_batch_does_not_end_the_run(capsys: pytest.CaptureFixture[str]) -> None:
    # Batching the planted poison is an optimisation: each plant embeds on demand
    # if it fails, so a rate limit here must not end the run before any probe ran.
    from sectum_ai.cli.app import _build_suite, _prefetch_queries
    from sectum_ai.config import DetectionConfig, build_detection_providers
    from sectum_ai.substrate import build_substrate, default_scenario

    class _DocumentsDown(_Modes):
        def embed(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("rate limited")

    substrate = build_substrate(default_scenario(seed=2026))
    suite = _build_suite(build_detection_providers(DetectionConfig()))
    store = _bridged_store(EmbedderBridge(_DocumentsDown()))
    _prefetch_queries(store, suite, substrate)
    assert "planted documents embed on demand" in capsys.readouterr().err


def test_an_unknown_spec_is_refused_as_unknown_at_load_in_every_mode(tmp_path: Path) -> None:
    # Refused at load like scenario.embedding_models, so a typo surfaces before
    # `seed`; in local mode it used to be refused as "would call a hosted AI API" -
    # false, and the wrong fix to point an operator at.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.config import build_vector_slot

    for mode in ("hosted", "local"):
        with pytest.raises(ValueError, match="unknown embedding model") as caught:
            SectumConfig.model_validate(
                {
                    "detection": {"mode": mode},
                    "adapters": {"vector_store": {"kind": "opensearch", "embedder": "hashing-64"}},
                }
            )
        assert "hosted" not in str(caught.value)
    # `calibrate` validates its override in every mode: resolving `openai:` built a
    # client with an empty model name and sent the labeled set to the provider.
    for config in ([], ["--config", str(_local_config(tmp_path))]):
        result = CliRunner().invoke(app, ["calibrate", *config, "--embedder", "openai:"])
        assert result.exit_code == 3, result.output
        assert "missing a model name" in result.output, result.output
    # The built-in fake never reads an `embedder`: refused as an unread field, not
    # as egress, even for a hosted spec in local mode.
    fake = SectumConfig.model_validate(
        _local(adapters={"vector_store": {"kind": "fake", "embedder": "openai:x-embed"}})
    )
    with pytest.raises(ConfigError, match="does not read: embedder"):
        build_vector_slot(fake)


def test_the_json_note_carries_the_same_description_as_the_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # For the default the description says no model was configured for the store;
    # the JSON note dropped that clause, so a dashboard could not tell the default
    # from a deliberately configured hash spec.
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.config import build_adapters as real_build

    def _default(loaded: SectumConfig) -> object:
        bundle = real_build(loaded)
        bundle.vector.embedder_name = "hashing-64"
        return bundle

    monkeypatch.setattr("sectum_ai.cli.app.build_adapters", _default)
    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    summary = runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--output", "json"])
    note = json.loads(summary.stdout)["vector_embedder_note"]
    assert "no embedding model was configured for the vector store" in note, note


@pytest.mark.parametrize(
    ("spec", "reason"),
    [("", "unknown embedding model ''"), ("fake-mini", "sweep recall name")],
)
def test_the_store_embedder_names_a_real_model_at_load(spec: str, reason: str) -> None:
    # An empty value was refused in local mode as egress, and a fake-* recall name
    # loaded cleanly to fail only at build - after the error had told the operator
    # to use one.
    for mode in ("hosted", "local"):
        with pytest.raises(ValueError, match=reason) as caught:
            SectumConfig.model_validate(
                {
                    "detection": {"mode": mode},
                    "adapters": {"vector_store": {"kind": "qdrant", "embedder": spec}},
                }
            )
        assert "hosted AI API" not in str(caught.value)
        assert "fake-<name>" not in str(caught.value)


def test_resolving_a_malformed_spec_is_refused_at_the_source() -> None:
    from sectum_ai.embeddings import resolve_embedding_model

    with pytest.raises(ConfigError, match="missing a model name"):
        resolve_embedding_model("openai:")


def test_an_unknown_seeded_embedding_model_is_refused_before_any_probe_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sweep resolves the seeded list only while the record is built, so an
    # unknown name failed after the whole suite had run against the stack.
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])

    def _never(*_: object) -> object:
        raise AssertionError("the stack was reached before the seeded list was checked")

    monkeypatch.setattr("sectum_ai.cli.app.build_adapters", _never)
    path = tmp_path / "substrate.json"
    substrate = json.loads(path.read_text())
    substrate["scenario"]["embedding_models"] = ["fake-mini", "mini-lm"]
    path.write_text(json.dumps(substrate))
    result = runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 3, result.output
    assert "unknown embedding model 'mini-lm'" in result.output, result.output


def test_a_seeded_model_that_cannot_load_fails_before_the_suite_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Well-formed but unloadable (an extra or key missing): it passed the name
    # check and failed only while the record was built, after every probe had run.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    runner = CliRunner()
    seeded = runner.invoke(
        app,
        [
            "seed",
            "--workdir",
            str(tmp_path),
            "--embedding-model",
            "hash-16",
            "--embedding-model",
            "cohere:embed-english-v3.0",
        ],
    )
    assert seeded.exit_code == 0, seeded.output

    def _never(*_: object) -> object:
        raise AssertionError("the corpus was upserted before the sweep's models loaded")

    monkeypatch.setattr("sectum_ai.cli.app._prefetch_corpus", _never)
    result = runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 3, result.output
    assert "cohere" in result.output.lower(), result.output


def test_a_local_mode_calibrate_refusal_names_its_offline_option(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    local = str(_local_config(tmp_path))
    result = CliRunner().invoke(
        app, ["calibrate", "--config", local, "--embedder", "openai:text-embedding-3-small"]
    )
    assert result.exit_code == 3, result.output
    assert "hosted embedding API" in result.output, result.output
    assert "calibrate also accepts --embedder fake" in result.output, result.output


def test_a_usage_error_is_reported_before_the_sweep_models_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Resolving the sweep at the top of `probe` downloaded models before a mistyped
    # flag was checked - and an unloadable model replaced the usage error.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    runner = CliRunner()
    runner.invoke(
        app,
        [
            "seed",
            "--workdir",
            str(tmp_path),
            "--embedding-model",
            "hash-16",
            "--embedding-model",
            "cohere:embed-english-v3.0",
        ],
    )
    result = runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--probe", "typo"])
    assert result.exit_code == 3, result.output
    assert "unknown probe 'typo'" in result.output, result.output


def test_a_model_the_sweep_would_discard_is_never_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One real model beside the fakes is not a gradient; building it anyway cost a
    # download - and, unloadable, refused a run that would never have used it.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    def _never(spec: str) -> object:
        raise AssertionError(f"{spec} was built for a sweep that will not run")

    runner = CliRunner()
    runner.invoke(
        app,
        [
            "seed",
            "--workdir",
            str(tmp_path),
            "--embedding-model",
            "fake-deterministic",
            "--embedding-model",
            "st:all-mpnet-base-v2",
        ],
    )
    monkeypatch.setattr("sectum_ai.cli.app.resolve_embedding_model", _never)
    result = runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code in (0, 2), result.output
    assert "the list names only one" in result.output, result.output


def test_the_cli_sweeps_the_real_models_of_a_mixed_list_it_resolved_up_front(
    tmp_path: Path,
) -> None:
    # The CLI is the only caller that hands the gradient pre-resolved models; a
    # wrong list there recorded an empty or mis-keyed gradient with every unit test
    # of the gradient itself still green.
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    runner = CliRunner()
    specs = ["hash-32", "hash-256", "fake-mini"]
    seed_args = [arg for spec in specs for arg in ("--embedding-model", spec)]
    runner.invoke(app, ["seed", "--workdir", str(tmp_path), *seed_args])
    result = runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert "fake-mini excluded from the embedding-model gradient" in result.output
    record = json.loads((tmp_path / "run.json").read_text())
    assert set(record["metrics"]["retrieval_pivot_rate_by_model"]) == {"hash-32", "hash-256"}


def test_an_adapter_config_error_reports_before_the_sweep_models_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A misspelled adapter field is a cheap error; it waited behind a model load
    # when the sweep resolved first - and an unloadable model replaced it.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    config = tmp_path / "sectum-ai.yaml"
    config.write_text("adapters:\n  vector_store:\n    kind: fake\n    shared_idx: true\n")
    runner = CliRunner()
    runner.invoke(
        app,
        [
            "seed",
            "--workdir",
            str(tmp_path),
            "--embedding-model",
            "hash-16",
            "--embedding-model",
            "cohere:embed-english-v3.0",
        ],
    )
    result = runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--config", str(config)])
    assert result.exit_code == 3, result.output
    assert "does not read: shared_idx" in result.output, result.output


def test_a_provider_failing_mid_sweep_fails_before_the_suite_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A constructor checks no credential, so a revoked key or a quota fails at the
    # first embed - which, at record time, threw away every probe's measurement.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.embeddings import resolve_embedding_model as real_resolve

    class _Revoked(HashingEmbedding):
        def embed(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("401")

    def _resolve(spec: str) -> object:
        return _Revoked(spec, dim=256) if spec == "hash-256" else real_resolve(spec)

    def _never(*_: object) -> object:
        raise AssertionError("the corpus was upserted before the sweep ran")

    runner = CliRunner()
    seed_args = ["--embedding-model", "hash-16", "--embedding-model", "hash-256"]
    runner.invoke(app, ["seed", "--workdir", str(tmp_path), *seed_args])
    monkeypatch.setattr("sectum_ai.cli.app.resolve_embedding_model", _resolve)
    monkeypatch.setattr("sectum_ai.cli.app._prefetch_corpus", _never)
    result = runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 3, result.output
    assert "embedder 'hash-256' failed" in result.output, result.output


def test_a_spec_listed_twice_is_one_model_not_a_gradient(tmp_path: Path) -> None:
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    runner = CliRunner()
    seed_args = ["--embedding-model", "hash-32", "--embedding-model", "hash-32"]
    runner.invoke(app, ["seed", "--workdir", str(tmp_path), *seed_args])
    result = runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert "the list names only one" in result.output, result.output
    record = json.loads((tmp_path / "run.json").read_text())
    assert record["metrics"]["retrieval_pivot_rate_by_model"] == {}


@pytest.mark.parametrize(
    "specs",
    [["hash-32", "hash:32"], ["fake-mini", "fake-mini"]],
)
def test_one_model_spelled_or_listed_twice_is_not_a_gradient(
    tmp_path: Path, specs: list[str]
) -> None:
    # `hash:32` and `hash-32` are one geometry: compared, they recorded a two-entry
    # "gradient" of identical vectors. And the recall-illustration branch still
    # took a duplicated fake as two models.
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    runner = CliRunner()
    seed_args = [arg for spec in specs for arg in ("--embedding-model", spec)]
    runner.invoke(app, ["seed", "--workdir", str(tmp_path), *seed_args])
    runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    record = json.loads((tmp_path / "run.json").read_text())
    assert record["metrics"]["retrieval_pivot_rate_by_model"] == {}


def test_the_gradients_warnings_print_beside_the_summary_not_above_the_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Computed before the suite, its warnings scrolled away above every probe's
    # output; the gradient they qualify prints at the end.
    import typer
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    def _marker(*_: object) -> None:
        typer.echo("SUITE-STARTED", err=True)

    runner = CliRunner()
    seed_args = ["--embedding-model", "hash-32", "--embedding-model", "fake-mini"]
    runner.invoke(app, ["seed", "--workdir", str(tmp_path), *seed_args])
    monkeypatch.setattr("sectum_ai.cli.app._prefetch_corpus", _marker)
    result = runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    warning = result.output.index("fake-mini excluded from the embedding-model gradient")
    assert warning > result.output.index("SUITE-STARTED"), result.output


def test_the_gradient_is_keyed_by_the_canonical_spelling(tmp_path: Path) -> None:
    # Keyed by the first raw spelling, one record named one model two ways: the
    # gradient's `hash:32` beside the store's `hash-32`.
    import json

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    runner = CliRunner()
    seed_args = ["--embedding-model", "hash:32", "--embedding-model", "hash-256"]
    runner.invoke(app, ["seed", "--workdir", str(tmp_path), *seed_args])
    runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    record = json.loads((tmp_path / "run.json").read_text())
    assert set(record["metrics"]["retrieval_pivot_rate_by_model"]) == {"hash-32", "hash-256"}


def test_a_fake_listed_twice_warns_like_a_real_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sectum_ai.adapters.fakes import FakeVectorStore
    from sectum_ai.cli.app import _per_model_rpr
    from sectum_ai.substrate import build_substrate, default_scenario

    substrate = build_substrate(
        default_scenario(seed=2026, embedding_models=("fake-mini", "fake-mini"))
    )
    assert _per_model_rpr(substrate, FakeVectorStore()) == {}
    assert "the list names only one" in capsys.readouterr().err


def test_subject_fingerprints_are_not_embedded_before_the_other_adapters_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A typo in another adapter block is a cheap config error; registering first
    # sent the data subject's text to a hosted embedder before it was reported.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    model = _Modes()
    _bridged_slot(monkeypatch, model)
    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    config = tmp_path / "sectum-ai.yaml"
    config.write_text("adapters:\n  cache:\n    kind: fake\n    shared_idx: true\n")
    manifest = tmp_path / "subject.yaml"
    manifest.write_text('subject_ref: u\nfingerprints:\n  vector_db: ["a subject phrase"]\n')
    result = runner.invoke(
        app,
        [
            "erasure",
            "--subject",
            str(manifest),
            "--workdir",
            str(tmp_path),
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 3, result.output
    assert "does not read: shared_idx" in result.output, result.output
    assert model.queries == []


def test_a_failed_batch_keeps_the_batches_before_it() -> None:
    # Caching only after every batch returned threw away the ones that succeeded,
    # and the contained fallback re-billed them as one-text calls.
    from sectum_ai.spec import AdapterError

    class _ThirdCallFails(_Modes):
        calls = 0

        def embed_queries(self, texts: list[str]) -> list[list[float]]:
            type(self).calls += 1
            if type(self).calls == 3:
                raise RuntimeError("429")
            return super().embed_queries(texts)

    model = _ThirdCallFails()
    bridge = EmbedderBridge(model, batch_size=10)
    with pytest.raises(AdapterError):
        bridge.prefetch_queries([f"query {n}" for n in range(30)])
    assert len(model.queries) == 20
    bridge("query 5")  # served from the cache, not re-embedded
    assert len(model.queries) == 20


def test_a_subject_scan_warns_when_a_hosted_embedder_receives_real_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The one path where a hosted embedder receives the data subject's REAL text,
    # not the synthetic corpus - which no doc or output said.
    from typer.testing import CliRunner

    from sectum_ai.cli.app import app
    from sectum_ai.config import build_vector_slot as real_build

    def _hosted(*args: object, **kwargs: object) -> object:
        model = _Modes()
        model.name = "openai:text-embedding-3-small"
        store = real_build(*args, **kwargs)  # type: ignore[arg-type]
        store.embedder_bridge = EmbedderBridge(model)
        return store

    monkeypatch.setattr("sectum_ai.cli.app.build_vector_slot", _hosted)
    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    manifest = tmp_path / "subject.yaml"
    manifest.write_text('subject_ref: u\nfingerprints:\n  vector_db: ["a subject phrase"]\n')
    result = runner.invoke(app, ["erasure", "--subject", str(manifest), "--workdir", str(tmp_path)])
    assert "sends the data subject's fingerprint text to openai:" in result.output, result.output
