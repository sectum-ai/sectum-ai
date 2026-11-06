"""Client libraries' own telemetry under ``detection.mode: local``.

Audited against the versions in uv.lock. Where Sectum builds the client it turns
the telemetry off there (the full chromadb 1.1.1 posts a PostHog event per
``HttpClient``; weaviate-client 4.23.0 fetches its latest version from pypi.org on
every connect). Where it cannot - huggingface_hub 1.30.0 fetches its agent-harness
registry from huggingface.co while building any Hub request's headers, crewai
1.15.1 exports usage spans to telemetry.crewai.com from import - local mode
refuses the stage until the library's own env var turns it off, read as the
library reads it, like the mem0 refusal before them.

Env vars that turn egress on, measured against the same versions: langsmith
0.14.16's tracing env makes langchain_core 1.7.3 trace every run - full inputs and
outputs - to LangSmith, so local mode refuses a langchain RAG or langgraph agent
while it is on. Its tracing-mode env would point the clients Sectum builds at a
global OTel exporter, and langfuse 4.15.6 ranks ``LANGFUSE_BASE_URL`` above the
``host`` Sectum passes; those clients now pin both.
"""

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sectum_ai.config import SectumConfig, refuse_hosted_embeddings
from sectum_ai.spec import ConfigError

_HF_VARS = (
    "HF_HUB_DISABLE_TELEMETRY",
    "DISABLE_TELEMETRY",
    "DO_NOT_TRACK",
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
)
_CREWAI_VARS = ("OTEL_SDK_DISABLED", "CREWAI_DISABLE_TELEMETRY", "CREWAI_DISABLE_TRACKING")
_LANGSMITH_VARS = (
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING",
)


@pytest.fixture(autouse=True)
def _telemetry_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*_HF_VARS, *_CREWAI_VARS, *_LANGSMITH_VARS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEM0_TELEMETRY", "False")


def _local(**overrides: object) -> dict[str, object]:
    return {"detection": {"mode": "local"}, **overrides}


def test_the_chroma_store_turns_chromadbs_telemetry_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import chromadb

    from sectum_ai.adapters.vector import chroma

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kwargs: calls.append(kwargs))
    chroma.ChromaVectorStore("chroma.internal", 8000, lambda text: [0.0])
    [kwargs] = calls
    assert (kwargs["host"], kwargs["port"]) == ("chroma.internal", 8000)
    assert isinstance(kwargs["settings"], chromadb.Settings)
    assert kwargs["settings"].anonymized_telemetry is False


def test_the_weaviate_store_skips_the_pypi_version_check(monkeypatch: pytest.MonkeyPatch) -> None:
    import weaviate as weaviate_client

    from sectum_ai.adapters.vector import weaviate

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(weaviate_client, "connect_to_local", lambda **kwargs: calls.append(kwargs))
    weaviate.WeaviateVectorStore("weaviate.internal", 8080, 50051, lambda text: [0.0])
    assert calls == [
        {
            "host": "weaviate.internal",
            "port": 8080,
            "grpc_port": 50051,
            "skip_init_checks": True,
        }
    ]


_HF_STAGES: dict[str, dict[str, Any]] = {
    "vector_store.embedder": {
        "adapters": {"vector_store": {"kind": "pgvector", "embedder": "st:all-MiniLM-L6-v2"}}
    },
    "scenario.embedding_models": {"scenario": {"embedding_models": ["hash-64", "st:bge-small"]}},
    "memory mem0 embedder": {
        "adapters": {
            "memory": {"kind": "mem0", "config": {"embedder": {"provider": "huggingface"}}}
        }
    },
    "model ('huggingface')": {
        "adapters": {"model": {"kind": "huggingface", "base_model_id": "m", "adapters_dir": "d"}}
    },
    "model ('tgi')": {"adapters": {"model": {"kind": "tgi", "base_url": "http://tgi:80"}}},
}


@pytest.mark.parametrize("stage", list(_HF_STAGES))
def test_byoc_local_mode_refuses_a_hugging_face_stage_with_its_telemetry_on(stage: str) -> None:
    # huggingface_hub fetches huggingface.co/api/agent-harnesses while building the
    # headers of any Hub request - st: and mem0 huggingface model loads, the LoRA
    # model's from_pretrained, and every request of the tgi model's client.
    config = _local(**_HF_STAGES[stage])
    with pytest.raises(ValueError, match="HF_HUB_DISABLE_TELEMETRY=1") as refused:
        SectumConfig.model_validate(config)
    assert stage in str(refused.value)
    SectumConfig.model_validate({**config, "detection": {"mode": "hosted"}})


@pytest.mark.parametrize(
    ("env", "refused"),
    [
        ({}, True),
        ({"HF_HUB_DISABLE_TELEMETRY": "1"}, False),
        ({"HF_HUB_DISABLE_TELEMETRY": "true"}, False),
        ({"HF_HUB_DISABLE_TELEMETRY": "on"}, False),
        ({"HF_HUB_DISABLE_TELEMETRY": "Yes"}, False),
        ({"HF_HUB_DISABLE_TELEMETRY": "0"}, True),
        ({"HF_HUB_DISABLE_TELEMETRY": "false"}, True),
        ({"HF_HUB_DISABLE_TELEMETRY": ""}, True),
        ({"HF_HUB_DISABLE_TELEMETRY": "y"}, True),
        ({"DISABLE_TELEMETRY": "1"}, False),
        ({"DO_NOT_TRACK": "1"}, False),
        ({"HF_HUB_OFFLINE": "1"}, False),
        ({"TRANSFORMERS_OFFLINE": "1"}, False),
        # huggingface_hub reads `HF_HUB_OFFLINE or TRANSFORMERS_OFFLINE`: a blank
        # value falls through, a set one wins.
        ({"HF_HUB_OFFLINE": "", "TRANSFORMERS_OFFLINE": "1"}, False),
        ({"HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "1"}, True),
    ],
)
def test_byoc_local_mode_reads_hugging_face_telemetry_as_huggingface_hub_does(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], refused: bool
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    config = _local(**_HF_STAGES["scenario.embedding_models"])
    if refused:
        with pytest.raises(ValueError, match="agent-harness registry"):
            SectumConfig.model_validate(config)
    else:
        SectumConfig.model_validate(config)


@pytest.mark.parametrize(
    "overrides",
    [
        # A built-in fake never reads an `embedder`; nothing loads a model.
        {"adapters": {"vector_store": {"kind": "fake", "embedder": "st:all-MiniLM-L6-v2"}}},
        {"adapters": {"vector_store": {"kind": "pgvector", "embedder": "hash-64"}}},
        {"scenario": {"embedding_models": ["hash-64", "fake-strong"]}},
        # Pointed at a base URL, mem0's huggingface embedder is an OpenAI client.
        {
            "adapters": {
                "memory": {
                    "kind": "mem0",
                    "config": {
                        "embedder": {
                            "provider": "huggingface",
                            "config": {"huggingface_base_url": "http://tei:80/v1"},
                        }
                    },
                }
            }
        },
        {"adapters": {"model": {"kind": "vllm", "base_url": "http://vllm:8000", "model": "m"}}},
    ],
)
def test_byoc_local_mode_leaves_stages_that_load_nothing_from_the_hub(
    overrides: dict[str, object],
) -> None:
    SectumConfig.model_validate(_local(**overrides))


def test_byoc_local_mode_refuses_st_specs_from_the_command_line_with_hf_telemetry_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = SectumConfig.model_validate(_local())
    with pytest.raises(ConfigError, match=r"--embedder \('st:bge-small'\)") as refused:
        refuse_hosted_embeddings(config, ["hash-64", "st:bge-small"], "--embedder")
    assert "HF_HUB_DISABLE_TELEMETRY=1" in str(refused.value)
    refuse_hosted_embeddings(config, ["hash-64", "fake"], "--embedder")
    hosted = SectumConfig.model_validate({})
    refuse_hosted_embeddings(hosted, ["st:bge-small"], "--embedder")
    monkeypatch.setenv("HF_HUB_DISABLE_TELEMETRY", "1")
    refuse_hosted_embeddings(config, ["st:bge-small"], "--embedder")


def _crewai() -> dict[str, object]:
    return {"agent": {"kind": "crewai", "factory": "crew_module:build"}}


@pytest.mark.parametrize(
    ("env", "refused"),
    [
        ({}, True),
        ({"CREWAI_DISABLE_TELEMETRY": "true"}, False),
        ({"CREWAI_DISABLE_TELEMETRY": "TRUE"}, False),
        ({"CREWAI_DISABLE_TRACKING": "true"}, False),
        ({"OTEL_SDK_DISABLED": "true"}, False),
        # crewai compares `.lower() == "true"`: these leave its exporter on.
        ({"CREWAI_DISABLE_TELEMETRY": "1"}, True),
        ({"CREWAI_DISABLE_TELEMETRY": "yes"}, True),
        ({"CREWAI_DISABLE_TELEMETRY": "false"}, True),
    ],
)
def test_byoc_local_mode_refuses_crewai_with_its_telemetry_on(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], refused: bool
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    config = _local(adapters=_crewai())
    if refused:
        with pytest.raises(ValueError, match="CREWAI_DISABLE_TELEMETRY=true"):
            SectumConfig.model_validate(config)
    else:
        SectumConfig.model_validate(config)
    SectumConfig.model_validate({"adapters": _crewai()})
    SectumConfig.model_validate(
        _local(adapters={"agent": {"kind": "langgraph", "factory": "graph_module:build"}})
    )


_LANGCHAIN_STAGES: dict[str, dict[str, Any]] = {
    "rag ('langchain')": {"rag": {"kind": "langchain", "factory": "chain_module:build"}},
    "agent ('langgraph')": {"agent": {"kind": "langgraph", "factory": "graph_module:build"}},
}


@pytest.mark.parametrize("stage", list(_LANGCHAIN_STAGES))
@pytest.mark.parametrize(
    ("env", "refused"),
    [
        ({}, None),
        ({"LANGSMITH_TRACING": "true"}, "LANGSMITH_TRACING"),
        ({"LANGCHAIN_TRACING": "true"}, "LANGCHAIN_TRACING"),
        ({"LANGSMITH_TRACING_V2": "true"}, "LANGSMITH_TRACING_V2"),
        ({"LANGCHAIN_TRACING_V2": "true"}, "LANGCHAIN_TRACING_V2"),
        # langsmith compares the value to exactly "true".
        ({"LANGSMITH_TRACING": "True"}, None),
        ({"LANGSMITH_TRACING": "1"}, None),
        ({"LANGSMITH_TRACING": " true"}, None),
        # The first non-blank _V2 name decides, before either plain name is read.
        ({"LANGSMITH_TRACING_V2": "false", "LANGSMITH_TRACING": "true"}, None),
        ({"LANGSMITH_TRACING_V2": "false", "LANGCHAIN_TRACING_V2": "true"}, None),
        ({"LANGSMITH_TRACING_V2": " ", "LANGSMITH_TRACING": "true"}, "LANGSMITH_TRACING"),
        ({"LANGSMITH_TRACING": "", "LANGCHAIN_TRACING": "true"}, "LANGCHAIN_TRACING"),
    ],
)
def test_byoc_local_mode_refuses_a_langchain_stage_while_langsmith_tracing_is_on(
    monkeypatch: pytest.MonkeyPatch, stage: str, env: dict[str, str], refused: str | None
) -> None:
    # Measured with the locked versions: LangChainRAGPipeline and LangGraphAgent
    # runs posted their query, retrieved documents and answer to /runs/multipart
    # on LANGSMITH_ENDPOINT, or opened api.smith.langchain.com:443 without one.
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    config = _local(adapters=_LANGCHAIN_STAGES[stage])
    if refused:
        with pytest.raises(ValueError, match=f"while {refused} is 'true'") as error:
            SectumConfig.model_validate(config)
        assert stage in str(error.value)
        assert f"Unset {refused}." in str(error.value)
    else:
        SectumConfig.model_validate(config)
    SectumConfig.model_validate({"adapters": _LANGCHAIN_STAGES[stage]})


def test_byoc_local_mode_leaves_stages_that_never_run_langchain_to_langsmith_tracing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("CREWAI_DISABLE_TELEMETRY", "true")
    SectumConfig.model_validate(
        _local(
            adapters={
                "rag": {"kind": "http", "url": "http://rag:80"},
                "agent": {"kind": "crewai", "factory": "crew_module:build"},
                "observability": {"kind": "langsmith", "api_key": "k"},
            }
        )
    )


def _stub(monkeypatch: pytest.MonkeyPatch, module: str, cls: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    stub = types.ModuleType(module)
    setattr(stub, cls, lambda **kwargs: calls.append(kwargs))
    monkeypatch.setitem(sys.modules, module, stub)
    return calls


def test_the_langsmith_clients_pin_their_tracing_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Under LANGSMITH_TRACING_MODE=otel|hybrid (or *_OTEL_ENABLED / *_OTEL_ONLY) the
    # client installed a global OTel exporter: a span carrying a canary went to
    # LANGSMITH_ENDPOINT/otel, or api.smith.langchain.com:443, never to `api_url`.
    from sectum_ai.adapters.eval_set.langsmith import LangSmithEvalSet
    from sectum_ai.adapters.observability.langsmith import LangSmithObservability

    calls = _stub(monkeypatch, "langsmith", "Client")
    LangSmithObservability.connect("k", "http://langsmith.internal")
    LangSmithEvalSet.connect("k", "http://langsmith.internal")
    expected = {"api_url": "http://langsmith.internal", "api_key": "k", "tracing_mode": "langsmith"}
    assert calls == [expected, expected]


def test_the_langfuse_client_goes_to_the_configured_host(monkeypatch: pytest.MonkeyPatch) -> None:
    # langfuse resolves `base_url or LANGFUSE_BASE_URL or host`: given `host`, a
    # LANGFUSE_BASE_URL in the environment took the keyed requests elsewhere.
    from sectum_ai.adapters.observability.langfuse import LangfuseObservability

    calls = _stub(monkeypatch, "langfuse", "Langfuse")
    LangfuseObservability.connect("pk", "sk", "http://langfuse.internal")
    assert calls == [
        {"public_key": "pk", "secret_key": "sk", "base_url": "http://langfuse.internal"}
    ]
