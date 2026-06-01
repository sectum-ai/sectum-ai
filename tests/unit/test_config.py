"""Tests for the ``sectum.yaml`` configuration loader."""

from pathlib import Path

import pytest

from sectum.adapters import (
    Capability,
    FakeAgent,
    FakeCache,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeRAGPipeline,
    FakeVectorStore,
)
from sectum.config import (
    AdapterConfig,
    EmbedderConfig,
    JudgeConfig,
    SectumConfig,
    _resolve_secret,
    build_adapters,
    build_agent,
    build_cache,
    build_embedder,
    build_judge,
    build_mcp,
    build_memory,
    build_model,
    build_observability,
    build_rag,
    build_vector_store,
    load_config,
)
from sectum.spec import ConfigError


def test_load_config_returns_defaults_for_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "sectum.yaml"
    path.write_text("")
    config = load_config(path)
    assert config == SectumConfig()
    assert config.scenario.seed == 2026
    assert config.workdir == Path(".sectum")
    assert config.evidence.timestamper == "local"


def test_load_config_parses_the_init_template_shape(tmp_path: Path) -> None:
    path = tmp_path / "sectum.yaml"
    path.write_text(
        "scenario:\n"
        "  seed: 42\n"
        "  corpus_profile: production\n"
        "workdir: out\n"
        "adapters:\n"
        "  vector_store:\n"
        "    kind: pgvector\n"
        "    dsn_env: SECTUM_PGVECTOR_DSN\n"
        "  cache:\n"
        "    kind: redis\n"
        "    host: localhost\n"
        "evidence:\n"
        "  timestamper: rfc3161\n"
        "  tsa_url: https://freetsa.org/tsr\n"
    )
    config = load_config(path)
    assert config.scenario.seed == 42
    assert config.scenario.corpus_profile == "production"
    assert config.workdir == Path("out")
    assert config.adapters["vector_store"].kind == "pgvector"
    # AdapterConfig allows extras; the backend-specific fields survive the parse
    assert config.adapters["vector_store"].model_extra == {"dsn_env": "SECTUM_PGVECTOR_DSN"}
    assert config.adapters["cache"].kind == "redis"
    assert config.adapters["cache"].model_extra == {"host": "localhost"}
    assert config.evidence.timestamper == "rfc3161"
    assert config.evidence.tsa_url == "https://freetsa.org/tsr"


def test_load_config_raises_when_the_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_load_config_raises_on_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "sectum.yaml"
    path.write_text("scenario: : :\n  bad")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


def test_load_config_raises_on_a_non_mapping_top_level(tmp_path: Path) -> None:
    path = tmp_path / "sectum.yaml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ConfigError, match="YAML mapping"):
        load_config(path)


def test_load_config_rejects_an_unknown_top_level_field(tmp_path: Path) -> None:
    path = tmp_path / "sectum.yaml"
    path.write_text("typo_field: 1\n")
    with pytest.raises(ConfigError, match="invalid config"):
        load_config(path)


def test_load_config_rejects_an_unknown_evidence_timestamper(tmp_path: Path) -> None:
    path = tmp_path / "sectum.yaml"
    path.write_text("evidence:\n  timestamper: invalid-kind\n")
    with pytest.raises(ConfigError, match="invalid config"):
        load_config(path)


# --- adapter resolver -------------------------------------------------------


def test_build_vector_store_defaults_to_an_isolated_fake() -> None:
    adapter = build_vector_store(AdapterConfig(kind="fake"))
    assert isinstance(adapter, FakeVectorStore)
    assert adapter.supports(Capability.PER_TENANT_NAMESPACE)
    assert not adapter.supports(Capability.SHARED_INDEX)


def test_build_vector_store_leaky_fake_via_shared_index_knob() -> None:
    adapter = build_vector_store(AdapterConfig(kind="fake", shared_index=True))
    assert adapter.supports(Capability.SHARED_INDEX)


def test_build_vector_store_rejects_a_non_boolean_knob() -> None:
    with pytest.raises(ConfigError, match="must be a boolean"):
        build_vector_store(AdapterConfig(kind="fake", shared_index="yes"))


def test_build_vector_store_rejects_an_unknown_kind() -> None:
    with pytest.raises(ConfigError, match="not yet supported"):
        build_vector_store(AdapterConfig(kind="not-a-real-kind"))


def test_build_cache_fake_with_a_tenant_scoping_knob() -> None:
    isolated = build_cache(AdapterConfig(kind="fake"))
    assert isolated.supports(Capability.TENANT_SCOPED_KEYS)
    shared = build_cache(AdapterConfig(kind="fake", tenant_scoped=False))
    assert not shared.supports(Capability.TENANT_SCOPED_KEYS)


def test_build_cache_fake_with_a_user_scoping_knob() -> None:
    default = build_cache(AdapterConfig(kind="fake"))
    assert not default.supports(Capability.USER_SCOPED)
    scoped = build_cache(AdapterConfig(kind="fake", user_scoped=True))
    assert scoped.supports(Capability.USER_SCOPED)


def test_build_cache_rejects_an_unknown_kind() -> None:
    with pytest.raises(ConfigError, match="not yet supported"):
        build_cache(AdapterConfig(kind="not-a-real-kind"))


def test_build_model_fake_with_leak_knobs() -> None:
    isolated = build_model(AdapterConfig(kind="fake"))
    assert isolated.supports(Capability.PER_TENANT_ADAPTER)
    leaky = build_model(AdapterConfig(kind="fake", adapter_bleed=True, prefix_cache=True))
    assert leaky.supports(Capability.SHARED_WEIGHTS)
    assert leaky.supports(Capability.SHARED_PREFIX_CACHE)


def test_build_mcp_fake_with_leak_knobs() -> None:
    isolated = build_mcp(AdapterConfig(kind="fake"))
    assert isolated.supports(Capability.TENANT_SCOPED_TOOLS)
    confused = build_mcp(AdapterConfig(kind="fake", confused_deputy=True))
    assert not confused.supports(Capability.TENANT_SCOPED_TOOLS)


def test_build_memory_fake_with_a_shared_memory_knob() -> None:
    isolated = build_memory(AdapterConfig(kind="fake"))
    assert isolated.supports(Capability.PER_TENANT_MEMORY)
    shared = build_memory(AdapterConfig(kind="fake", shared_memory=True))
    assert shared.supports(Capability.SHARED_MEMORY)


def test_model_memory_mcp_fakes_thread_user_scoped_from_config() -> None:
    # ADR-0006: the user-isolation dimension must be reachable from config, not
    # only when a fake is built directly in a test. The model/memory/MCP fake
    # branches previously dropped the `user_scoped` knob (unlike vector/cache),
    # so a user-scoped verification silently ran against a tenant-only fake.
    assert build_model(AdapterConfig(kind="fake", user_scoped=True)).supports(
        Capability.USER_SCOPED
    )
    assert build_memory(AdapterConfig(kind="fake", user_scoped=True)).supports(
        Capability.USER_SCOPED
    )
    assert build_mcp(AdapterConfig(kind="fake", user_scoped=True)).supports(Capability.USER_SCOPED)
    # The default stays tenant-only for all three.
    assert not build_model(AdapterConfig(kind="fake")).supports(Capability.USER_SCOPED)
    assert not build_memory(AdapterConfig(kind="fake")).supports(Capability.USER_SCOPED)
    assert not build_mcp(AdapterConfig(kind="fake")).supports(Capability.USER_SCOPED)


def test_build_adapters_defaults_missing_families_to_plain_fakes() -> None:
    bundle = build_adapters(SectumConfig())
    assert isinstance(bundle.vector, FakeVectorStore)
    assert isinstance(bundle.cache, FakeCache)
    assert isinstance(bundle.model, FakeModel)
    assert isinstance(bundle.mcp, FakeMCP)
    assert isinstance(bundle.memory, FakeMemory)
    # all default to non-leaky
    assert not bundle.vector.supports(Capability.SHARED_INDEX)
    assert bundle.cache.supports(Capability.TENANT_SCOPED_KEYS)


def test_build_adapters_respects_per_family_knobs() -> None:
    config = SectumConfig(
        adapters={
            "vector_store": AdapterConfig(kind="fake", shared_index=True),
            "cache": AdapterConfig(kind="fake", tenant_scoped=False),
        }
    )
    bundle = build_adapters(config)
    assert bundle.vector.supports(Capability.SHARED_INDEX)
    assert not bundle.cache.supports(Capability.TENANT_SCOPED_KEYS)


# The eight adapter-family keys `build_adapters` reads (config.py). A key in a
# config file that is NOT one of these is silently ignored - the resolver falls
# back to the fake - so the shipped example must use exactly these names.
_RESOLVER_FAMILIES = {
    "vector_store",
    "cache",
    "model",
    "mcp",
    "memory",
    "rag",
    "observability",
    "agent",
}


def test_example_config_uses_only_adapter_keys_the_resolver_reads() -> None:
    # sectum.yaml.example must use the exact family keys build_adapters consumes:
    # a copied-and-edited example with a stray key (e.g. `vector:` instead of
    # `vector_store:`) silently runs against the in-memory fake with no error,
    # which defeats real-stack probing. Guards that footgun against regressing.
    example = Path(__file__).resolve().parents[2] / "sectum.yaml.example"
    config = load_config(example)
    unknown = set(config.adapters) - _RESOLVER_FAMILIES
    assert not unknown, (
        f"sectum.yaml.example has adapter keys the resolver ignores: {sorted(unknown)}"
    )


# --- live adapter wirings ---------------------------------------------------


def test_resolve_secret_reads_a_value_from_an_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECTUM_TEST_DSN", "postgresql://example/test")
    value = _resolve_secret({"dsn_env": "SECTUM_TEST_DSN"}, "dsn", "dsn_env")
    assert value == "postgresql://example/test"


def test_resolve_secret_uses_a_direct_value_when_present() -> None:
    value = _resolve_secret({"dsn": "postgresql://example/inline"}, "dsn", "dsn_env")
    assert value == "postgresql://example/inline"


def test_resolve_secret_raises_when_the_env_var_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SECTUM_TEST_DSN", raising=False)
    with pytest.raises(ConfigError, match="unset or empty"):
        _resolve_secret({"dsn_env": "SECTUM_TEST_DSN"}, "dsn", "dsn_env")


def test_resolve_secret_raises_when_neither_key_is_present() -> None:
    with pytest.raises(ConfigError, match="missing 'dsn' or 'dsn_env'"):
        _resolve_secret({}, "dsn", "dsn_env")


def test_resolve_secret_raises_when_env_name_is_empty() -> None:
    with pytest.raises(ConfigError, match="must name an environment variable"):
        _resolve_secret({"dsn_env": ""}, "dsn", "dsn_env")


def test_resolve_secret_raises_when_direct_value_is_empty() -> None:
    with pytest.raises(ConfigError, match="must not be empty"):
        _resolve_secret({"dsn": ""}, "dsn", "dsn_env")


def test_resolve_secret_raises_when_env_var_is_set_to_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECTUM_TEST_DSN", "")
    with pytest.raises(ConfigError, match="unset or empty"):
        _resolve_secret({"dsn_env": "SECTUM_TEST_DSN"}, "dsn", "dsn_env")


def test_build_vector_store_pgvector_requires_a_dsn() -> None:
    with pytest.raises(ConfigError, match="missing 'dsn' or 'dsn_env'"):
        build_vector_store(AdapterConfig(kind="pgvector"))


def test_build_cache_redis_constructs_a_redis_cache() -> None:
    from sectum.adapters.cache.redis import RedisCache

    adapter = build_cache(AdapterConfig(kind="redis", host="example", port=6380, prefix="probe"))
    assert isinstance(adapter, RedisCache)
    assert adapter.supports(Capability.TENANT_SCOPED_KEYS)


def test_build_mcp_stdio_constructs_a_stdio_client() -> None:
    from sectum.adapters.mcp.client import StdioMCPClient

    adapter = build_mcp(
        AdapterConfig(kind="stdio", command="echo", args=["hello"], tenant_argument="tenant")
    )
    assert isinstance(adapter, StdioMCPClient)


def test_build_mcp_stdio_requires_a_command() -> None:
    with pytest.raises(ConfigError, match="'command' is required"):
        build_mcp(AdapterConfig(kind="stdio"))


def test_build_mcp_stdio_rejects_non_list_args() -> None:
    with pytest.raises(ConfigError, match="must be a list"):
        build_mcp(AdapterConfig(kind="stdio", command="echo", args="oops"))


def test_build_mcp_http_constructs_an_http_client() -> None:
    from sectum.adapters.mcp.http import HttpMCPClient

    adapter = build_mcp(
        AdapterConfig(
            kind="http",
            url="http://stub.invalid/mcp",
            headers={"Authorization": "Bearer x"},
            timeout=5.0,
            tenant_argument="tenant",
        )
    )
    assert isinstance(adapter, HttpMCPClient)


def test_build_mcp_http_requires_a_url() -> None:
    with pytest.raises(ConfigError, match="'url' is required"):
        build_mcp(AdapterConfig(kind="http"))


def test_build_rag_defaults_to_a_fake() -> None:
    assert isinstance(build_rag(AdapterConfig(kind="fake")), FakeRAGPipeline)


def test_build_rag_rejects_an_unknown_kind() -> None:
    with pytest.raises(ConfigError, match="not yet supported"):
        build_rag(AdapterConfig(kind="not-a-real-kind"))


def test_build_observability_defaults_to_a_fake() -> None:
    assert isinstance(build_observability(AdapterConfig(kind="fake")), FakeObservability)


def test_build_observability_rejects_an_unknown_kind() -> None:
    with pytest.raises(ConfigError, match="not yet supported"):
        build_observability(AdapterConfig(kind="not-a-real-kind"))


def test_build_agent_defaults_to_a_fake() -> None:
    assert isinstance(build_agent(AdapterConfig(kind="fake")), FakeAgent)


def test_build_agent_rejects_an_unknown_kind() -> None:
    with pytest.raises(ConfigError, match="not yet supported"):
        build_agent(AdapterConfig(kind="not-a-real-kind"))


def test_build_adapters_includes_rag_observability_and_agent() -> None:
    bundle = build_adapters(SectumConfig())
    assert isinstance(bundle.rag, FakeRAGPipeline)
    assert isinstance(bundle.observability, FakeObservability)
    assert isinstance(bundle.agent, FakeAgent)


def test_build_rag_http_constructs_an_http_pipeline() -> None:
    from sectum.adapters.rag.http import HttpRAGPipeline

    adapter = build_rag(AdapterConfig(kind="http", url="http://example.com/rag"))
    assert isinstance(adapter, HttpRAGPipeline)


def test_build_rag_http_accepts_headers_and_timeout() -> None:
    from sectum.adapters.rag.http import HttpRAGPipeline

    adapter = build_rag(
        AdapterConfig(
            kind="http",
            url="http://example.com/rag",
            headers={"Authorization": "Bearer x"},
            timeout=5,
        )
    )
    assert isinstance(adapter, HttpRAGPipeline)


def test_build_rag_http_requires_a_url() -> None:
    with pytest.raises(ConfigError, match="'url' is required"):
        build_rag(AdapterConfig(kind="http"))


def test_build_rag_http_rejects_a_non_mapping_headers_field() -> None:
    with pytest.raises(ConfigError, match="must be a mapping"):
        build_rag(AdapterConfig(kind="http", url="http://x", headers="oops"))


def test_build_observability_phoenix_constructs_phoenix() -> None:
    from sectum.adapters.observability.phoenix import PhoenixObservability

    adapter = build_observability(AdapterConfig(kind="phoenix", base_url="http://localhost:6007"))
    assert isinstance(adapter, PhoenixObservability)


def test_build_observability_phoenix_requires_base_url() -> None:
    with pytest.raises(ConfigError, match="'base_url' is required"):
        build_observability(AdapterConfig(kind="phoenix"))


def test_build_agent_http_constructs_an_http_agent() -> None:
    from sectum.adapters.agent.http import HttpAgent

    adapter = build_agent(AdapterConfig(kind="http", url="http://example.com/agent"))
    assert isinstance(adapter, HttpAgent)


def test_build_agent_http_requires_a_url() -> None:
    with pytest.raises(ConfigError, match="'url' is required"):
        build_agent(AdapterConfig(kind="http"))


def test_build_agent_http_rejects_a_non_number_timeout() -> None:
    with pytest.raises(ConfigError, match="must be a number"):
        build_agent(AdapterConfig(kind="http", url="http://x", timeout="five"))


def test_build_agent_langgraph_imports_and_invokes_the_named_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``kind: langgraph`` imports ``module:callable`` and wraps its return value.

    The factory returns any object exposing ``invoke(input, config)``; the
    resolver calls it once and hands the graph to ``LangGraphAgent``.
    """
    import sys
    import types

    from sectum.adapters.agent.langgraph import LangGraphAgent

    class _StubGraph:
        def invoke(self, input: object, config: object | None = None) -> dict[str, object]:
            return {"messages": []}

    module = types.ModuleType("sectum_test_langgraph_factory")
    module.make_graph = lambda: _StubGraph()  # type: ignore[attr-defined]
    module.NOT_A_CALLABLE = 42  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_langgraph_factory", module)

    adapter = build_agent(
        AdapterConfig(
            kind="langgraph",
            factory="sectum_test_langgraph_factory:make_graph",
        )
    )
    assert isinstance(adapter, LangGraphAgent)


def test_build_agent_langgraph_requires_a_factory() -> None:
    with pytest.raises(ConfigError, match="'factory' is required"):
        build_agent(AdapterConfig(kind="langgraph"))


def test_build_agent_langgraph_rejects_a_malformed_factory_path() -> None:
    with pytest.raises(ConfigError, match=r"module\.path:callable"):
        build_agent(AdapterConfig(kind="langgraph", factory="not_dotted"))


def test_build_rag_langchain_imports_and_wraps_the_named_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``kind: langchain`` imports ``module:callable`` and wraps its return value.

    The factory returns any object exposing ``invoke(input)``; the resolver
    calls it once and hands the chain to ``LangChainRAGPipeline``.
    """
    import sys
    import types

    from sectum.adapters.rag.langchain import LangChainRAGPipeline

    class _StubChain:
        def invoke(self, input: object) -> str:
            return "answer"

    module = types.ModuleType("sectum_test_langchain_factory")
    module.make_chain = lambda: _StubChain()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_langchain_factory", module)

    adapter = build_rag(
        AdapterConfig(kind="langchain", factory="sectum_test_langchain_factory:make_chain")
    )
    assert isinstance(adapter, LangChainRAGPipeline)


def test_build_rag_langchain_rejects_a_malformed_factory_path() -> None:
    with pytest.raises(ConfigError, match=r"module\.path:callable"):
        build_rag(AdapterConfig(kind="langchain", factory="not_dotted"))


def test_build_observability_otel_builds_from_a_base_url() -> None:
    from sectum.adapters.observability.otel import OtelObservability

    adapter = build_observability(AdapterConfig(kind="otel", base_url="https://otel.example.com"))
    assert isinstance(adapter, OtelObservability)


def test_build_observability_helicone_builds_from_an_api_key() -> None:
    from sectum.adapters.observability.helicone import HeliconeObservability

    adapter = build_observability(AdapterConfig(kind="helicone", api_key="hc-test-key"))
    assert isinstance(adapter, HeliconeObservability)


def test_build_observability_datadog_builds_from_api_and_application_keys() -> None:
    from sectum.adapters.observability.datadog import DatadogObservability

    adapter = build_observability(
        AdapterConfig(kind="datadog", api_key="dd-test-key", application_key="dd-app-key")
    )
    assert isinstance(adapter, DatadogObservability)


def test_build_model_huggingface_requires_a_base_model_id() -> None:
    # The huggingface branch validates its required fields before importing the
    # heavy transformers/peft stack, so this is deterministic in CI (where the
    # extra is not installed) while still exercising the resolver dispatch.
    with pytest.raises(ConfigError, match="base_model_id"):
        build_model(AdapterConfig(kind="huggingface"))


def test_build_agent_langgraph_rejects_a_missing_factory_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_langgraph_factory_missing")
    monkeypatch.setitem(sys.modules, "sectum_test_langgraph_factory_missing", module)
    with pytest.raises(ConfigError, match="not exported"):
        build_agent(
            AdapterConfig(
                kind="langgraph",
                factory="sectum_test_langgraph_factory_missing:nope",
            )
        )


def test_build_agent_langgraph_rejects_a_non_callable_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_langgraph_factory_non_callable")
    module.NOT_A_CALLABLE = 42  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_langgraph_factory_non_callable", module)
    with pytest.raises(ConfigError, match="not callable"):
        build_agent(
            AdapterConfig(
                kind="langgraph",
                factory="sectum_test_langgraph_factory_non_callable:NOT_A_CALLABLE",
            )
        )


def test_build_agent_langgraph_rejects_an_unimportable_module() -> None:
    with pytest.raises(ConfigError, match="cannot be imported"):
        build_agent(AdapterConfig(kind="langgraph", factory="no_such_module_anywhere:thing"))


def test_build_agent_autogen_imports_and_invokes_the_named_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``kind: autogen`` imports ``module:callable`` and wraps its return value.

    The factory returns a 2-tuple ``(assistant, user_proxy)``; the resolver
    calls it once and hands the pair to ``AutoGenAgent``.
    """
    import sys
    import types

    from sectum.adapters.agent.autogen import AutoGenAgent

    class _StubAssistant:
        name = "stub"

    class _StubProxy:
        def initiate_chat(self, recipient: object, **kwargs: object) -> object:
            return {"chat_history": []}

    module = types.ModuleType("sectum_test_autogen_factory")
    module.make_pair = lambda: (_StubAssistant(), _StubProxy())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_autogen_factory", module)

    adapter = build_agent(
        AdapterConfig(
            kind="autogen",
            factory="sectum_test_autogen_factory:make_pair",
        )
    )
    assert isinstance(adapter, AutoGenAgent)


def test_build_agent_autogen_requires_a_factory() -> None:
    with pytest.raises(ConfigError, match="'factory' is required"):
        build_agent(AdapterConfig(kind="autogen"))


def test_build_agent_autogen_rejects_a_malformed_factory_path() -> None:
    with pytest.raises(ConfigError, match=r"module\.path:callable"):
        build_agent(AdapterConfig(kind="autogen", factory="not_dotted"))


def test_build_agent_autogen_rejects_a_missing_factory_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_autogen_factory_missing")
    monkeypatch.setitem(sys.modules, "sectum_test_autogen_factory_missing", module)
    with pytest.raises(ConfigError, match="not exported"):
        build_agent(
            AdapterConfig(
                kind="autogen",
                factory="sectum_test_autogen_factory_missing:nope",
            )
        )


def test_build_agent_autogen_rejects_a_non_callable_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_autogen_factory_non_callable")
    module.NOT_A_CALLABLE = 42  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_autogen_factory_non_callable", module)
    with pytest.raises(ConfigError, match="not callable"):
        build_agent(
            AdapterConfig(
                kind="autogen",
                factory="sectum_test_autogen_factory_non_callable:NOT_A_CALLABLE",
            )
        )


def test_build_agent_autogen_rejects_an_unimportable_module() -> None:
    with pytest.raises(ConfigError, match="cannot be imported"):
        build_agent(AdapterConfig(kind="autogen", factory="no_such_module_anywhere:thing"))


def test_build_agent_autogen_rejects_a_non_tuple_factory_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_autogen_factory_bad_return")
    module.make_pair = lambda: "not a tuple"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_autogen_factory_bad_return", module)
    with pytest.raises(ConfigError, match="assistant, user_proxy"):
        build_agent(
            AdapterConfig(
                kind="autogen",
                factory="sectum_test_autogen_factory_bad_return:make_pair",
            )
        )


def test_build_agent_autogen_forwards_a_max_turns_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    from sectum.adapters.agent.autogen import AutoGenAgent

    class _StubAssistant:
        name = "stub"

    class _StubProxy:
        def initiate_chat(self, recipient: object, **kwargs: object) -> object:
            return {"chat_history": []}

    module = types.ModuleType("sectum_test_autogen_factory_max_turns")
    module.make_pair = lambda: (_StubAssistant(), _StubProxy())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_autogen_factory_max_turns", module)

    adapter = build_agent(
        AdapterConfig(
            kind="autogen",
            factory="sectum_test_autogen_factory_max_turns:make_pair",
            max_turns=7,
        )
    )
    assert isinstance(adapter, AutoGenAgent)
    assert adapter._max_turns == 7


def test_build_agent_crewai_imports_and_invokes_the_named_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``kind: crewai`` imports ``module:callable`` and wraps its return value.

    The factory returns any object exposing ``kickoff(inputs)``; the resolver
    calls it once and hands the crew to ``CrewAIAgent``.
    """
    import sys
    import types

    from sectum.adapters.agent.crewai import CrewAIAgent

    class _StubCrew:
        def kickoff(self, inputs: dict[str, object]) -> dict[str, object]:
            return {"raw": "", "tasks_output": []}

    module = types.ModuleType("sectum_test_crewai_factory")
    module.make_crew = lambda: _StubCrew()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_crewai_factory", module)

    adapter = build_agent(
        AdapterConfig(
            kind="crewai",
            factory="sectum_test_crewai_factory:make_crew",
        )
    )
    assert isinstance(adapter, CrewAIAgent)


def test_build_agent_crewai_requires_a_factory() -> None:
    with pytest.raises(ConfigError, match="'factory' is required"):
        build_agent(AdapterConfig(kind="crewai"))


def test_build_agent_crewai_rejects_a_malformed_factory_path() -> None:
    with pytest.raises(ConfigError, match=r"module\.path:callable"):
        build_agent(AdapterConfig(kind="crewai", factory="not_dotted"))


def test_build_agent_crewai_rejects_a_missing_factory_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_crewai_factory_missing")
    monkeypatch.setitem(sys.modules, "sectum_test_crewai_factory_missing", module)
    with pytest.raises(ConfigError, match="not exported"):
        build_agent(
            AdapterConfig(
                kind="crewai",
                factory="sectum_test_crewai_factory_missing:nope",
            )
        )


def test_build_agent_crewai_rejects_a_non_callable_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_crewai_factory_non_callable")
    module.NOT_A_CALLABLE = 42  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_crewai_factory_non_callable", module)
    with pytest.raises(ConfigError, match="not callable"):
        build_agent(
            AdapterConfig(
                kind="crewai",
                factory="sectum_test_crewai_factory_non_callable:NOT_A_CALLABLE",
            )
        )


def test_build_agent_crewai_rejects_an_unimportable_module() -> None:
    with pytest.raises(ConfigError, match="cannot be imported"):
        build_agent(AdapterConfig(kind="crewai", factory="no_such_module_anywhere:thing"))


def test_build_agent_crewai_forwards_input_and_tenant_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    from sectum.adapters.agent.crewai import CrewAIAgent

    class _StubCrew:
        def kickoff(self, inputs: dict[str, object]) -> dict[str, object]:
            return {"raw": "", "tasks_output": []}

    module = types.ModuleType("sectum_test_crewai_factory_keys")
    module.make_crew = lambda: _StubCrew()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_crewai_factory_keys", module)

    adapter = build_agent(
        AdapterConfig(
            kind="crewai",
            factory="sectum_test_crewai_factory_keys:make_crew",
            input_key="query",
            tenant_key="customer",
        )
    )
    assert isinstance(adapter, CrewAIAgent)
    assert adapter._input_key == "query"
    assert adapter._tenant_key == "customer"


# ---------------------------------------------------------------------------
# kind: openai-assistants
# ---------------------------------------------------------------------------


def test_build_agent_openai_assistants_imports_and_invokes_the_named_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``kind: openai-assistants`` imports ``module:callable`` and wraps its return value.

    The factory returns a 2-tuple ``(client, assistant_id)``; the resolver
    calls it once and hands the pair to ``OpenAIAssistantsAgent``.
    """
    import sys
    import types

    from sectum.adapters.agent.openai_assistants import OpenAIAssistantsAgent

    class _StubAssistantsClient:
        def create_thread(self) -> str:
            return "thread-stub"

        def add_user_message(self, thread_id: str, content: str) -> None:
            pass

        def run_until_complete(
            self, thread_id: str, assistant_id: str
        ) -> tuple[str, tuple[str, ...]]:
            return ("", ())

    module = types.ModuleType("sectum_test_openai_assistants_factory")
    module.make_pair = lambda: (_StubAssistantsClient(), "assistant-abc")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_openai_assistants_factory", module)

    adapter = build_agent(
        AdapterConfig(
            kind="openai-assistants",
            factory="sectum_test_openai_assistants_factory:make_pair",
        )
    )
    assert isinstance(adapter, OpenAIAssistantsAgent)
    assert adapter._assistant_id == "assistant-abc"


def test_build_agent_openai_assistants_requires_a_factory() -> None:
    with pytest.raises(ConfigError, match="'factory' is required"):
        build_agent(AdapterConfig(kind="openai-assistants"))


def test_build_agent_openai_assistants_rejects_a_malformed_factory_path() -> None:
    with pytest.raises(ConfigError, match=r"module\.path:callable"):
        build_agent(AdapterConfig(kind="openai-assistants", factory="not_dotted"))


def test_build_agent_openai_assistants_rejects_a_missing_factory_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_openai_assistants_factory_missing")
    monkeypatch.setitem(sys.modules, "sectum_test_openai_assistants_factory_missing", module)
    with pytest.raises(ConfigError, match="not exported"):
        build_agent(
            AdapterConfig(
                kind="openai-assistants",
                factory="sectum_test_openai_assistants_factory_missing:nope",
            )
        )


def test_build_agent_openai_assistants_rejects_a_non_callable_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_openai_assistants_factory_non_callable")
    module.NOT_A_CALLABLE = 42  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_openai_assistants_factory_non_callable", module)
    with pytest.raises(ConfigError, match="not callable"):
        build_agent(
            AdapterConfig(
                kind="openai-assistants",
                factory="sectum_test_openai_assistants_factory_non_callable:NOT_A_CALLABLE",
            )
        )


def test_build_agent_openai_assistants_rejects_an_unimportable_module() -> None:
    with pytest.raises(ConfigError, match="cannot be imported"):
        build_agent(
            AdapterConfig(kind="openai-assistants", factory="no_such_module_anywhere:thing")
        )


def test_build_agent_openai_assistants_rejects_a_non_tuple_factory_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_openai_assistants_factory_bad_return")
    module.make_pair = lambda: "not a tuple"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_openai_assistants_factory_bad_return", module)
    with pytest.raises(ConfigError, match=r"\(client, assistant_id\)"):
        build_agent(
            AdapterConfig(
                kind="openai-assistants",
                factory="sectum_test_openai_assistants_factory_bad_return:make_pair",
            )
        )


def test_build_agent_openai_assistants_rejects_a_non_string_assistant_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    class _StubAssistantsClient:
        def create_thread(self) -> str:
            return "t"

        def add_user_message(self, thread_id: str, content: str) -> None:
            pass

        def run_until_complete(
            self, thread_id: str, assistant_id: str
        ) -> tuple[str, tuple[str, ...]]:
            return ("", ())

    module = types.ModuleType("sectum_test_openai_assistants_factory_bad_id")
    module.make_pair = lambda: (_StubAssistantsClient(), 12345)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_openai_assistants_factory_bad_id", module)
    with pytest.raises(ConfigError, match="non-string"):
        build_agent(
            AdapterConfig(
                kind="openai-assistants",
                factory="sectum_test_openai_assistants_factory_bad_id:make_pair",
            )
        )


# ---------------------------------------------------------------------------
# kind: anthropic-tooluse
# ---------------------------------------------------------------------------


def test_build_agent_anthropic_tooluse_imports_and_invokes_the_named_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``kind: anthropic-tooluse`` imports ``module:callable`` and wraps its return value.

    The factory returns the ``_AnthropicClient`` the adapter consumes; the
    resolver calls it once and hands the client to ``AnthropicToolUseAgent``.
    """
    import sys
    import types

    from sectum.adapters.agent.anthropic_tooluse import AnthropicToolUseAgent

    class _StubAnthropicClient:
        def run_turn(self, messages: list[dict[str, object]]) -> tuple[str, tuple[str, ...]]:
            return ("", ())

    module = types.ModuleType("sectum_test_anthropic_tooluse_factory")
    module.make_client = lambda: _StubAnthropicClient()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_anthropic_tooluse_factory", module)

    adapter = build_agent(
        AdapterConfig(
            kind="anthropic-tooluse",
            factory="sectum_test_anthropic_tooluse_factory:make_client",
        )
    )
    assert isinstance(adapter, AnthropicToolUseAgent)


def test_build_agent_anthropic_tooluse_requires_a_factory() -> None:
    with pytest.raises(ConfigError, match="'factory' is required"):
        build_agent(AdapterConfig(kind="anthropic-tooluse"))


def test_build_agent_anthropic_tooluse_rejects_a_malformed_factory_path() -> None:
    with pytest.raises(ConfigError, match=r"module\.path:callable"):
        build_agent(AdapterConfig(kind="anthropic-tooluse", factory="not_dotted"))


def test_build_agent_anthropic_tooluse_rejects_a_missing_factory_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_anthropic_tooluse_factory_missing")
    monkeypatch.setitem(sys.modules, "sectum_test_anthropic_tooluse_factory_missing", module)
    with pytest.raises(ConfigError, match="not exported"):
        build_agent(
            AdapterConfig(
                kind="anthropic-tooluse",
                factory="sectum_test_anthropic_tooluse_factory_missing:nope",
            )
        )


def test_build_agent_anthropic_tooluse_rejects_a_non_callable_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("sectum_test_anthropic_tooluse_factory_non_callable")
    module.NOT_A_CALLABLE = 42  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sectum_test_anthropic_tooluse_factory_non_callable", module)
    with pytest.raises(ConfigError, match="not callable"):
        build_agent(
            AdapterConfig(
                kind="anthropic-tooluse",
                factory="sectum_test_anthropic_tooluse_factory_non_callable:NOT_A_CALLABLE",
            )
        )


def test_build_agent_anthropic_tooluse_rejects_an_unimportable_module() -> None:
    with pytest.raises(ConfigError, match="cannot be imported"):
        build_agent(
            AdapterConfig(kind="anthropic-tooluse", factory="no_such_module_anywhere:thing")
        )


# ---------------------------------------------------------------------------
# unknown-kind rejection for the three resolver families that lacked it
# ---------------------------------------------------------------------------


def test_build_model_rejects_an_unknown_kind() -> None:
    with pytest.raises(ConfigError, match=r"not yet supported"):
        build_model(AdapterConfig(kind="not-a-real-kind"))


def test_build_mcp_rejects_an_unknown_kind() -> None:
    with pytest.raises(ConfigError, match=r"not yet supported"):
        build_mcp(AdapterConfig(kind="not-a-real-kind"))


def test_build_memory_rejects_an_unknown_kind() -> None:
    with pytest.raises(ConfigError, match=r"not yet supported"):
        build_memory(AdapterConfig(kind="not-a-real-kind"))


# ---------------------------------------------------------------------------
# detection-provider resolver: missing-API-key paths
# ---------------------------------------------------------------------------


def test_build_embedder_fake_returns_none() -> None:
    # The fake embedder is the calibrated semantic-similarity stand-in - the
    # resolver returns None so the detection pipeline uses its built-in fake.
    assert build_embedder(EmbedderConfig(kind="fake")) is None


def test_build_embedder_openai_raises_when_api_key_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An operator who configures `kind: openai` without setting OPENAI_API_KEY
    # (or the custom api_key_env they named) must see a typed ConfigError
    # naming the env var - not a confusing OpenAI client error at first call.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        build_embedder(EmbedderConfig(kind="openai"))


def test_build_embedder_openai_raises_when_custom_api_key_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The custom api_key_env name flows into the error message so the
    # operator can immediately spot which env var the resolver looked for.
    monkeypatch.delenv("CUSTOM_OPENAI_KEY", raising=False)
    with pytest.raises(ConfigError, match="CUSTOM_OPENAI_KEY"):
        build_embedder(EmbedderConfig(kind="openai", api_key_env="CUSTOM_OPENAI_KEY"))


def test_build_judge_fake_returns_none() -> None:
    assert build_judge(JudgeConfig(kind="fake")) is None


def test_build_judge_openai_raises_when_api_key_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        build_judge(JudgeConfig(kind="openai"))


def test_build_judge_anthropic_raises_when_api_key_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        build_judge(JudgeConfig(kind="anthropic"))


def test_build_judge_rejects_an_unknown_kind() -> None:
    # The Pydantic Literal type already rejects unknown kinds at validation
    # time; this test pins the behaviour against a future refactor that
    # might drop the validator.
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=r"anthropic|openai|fake"):
        JudgeConfig(kind="not-a-real-kind")


def test_build_embedder_rejects_an_unknown_kind() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=r"openai|fake"):
        EmbedderConfig(kind="not-a-real-kind")
