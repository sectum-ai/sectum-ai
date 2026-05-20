"""Tests for the ``sectum.yaml`` configuration loader."""

from pathlib import Path

import pytest

from sectum.adapters import (
    Capability,
    FakeCache,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeVectorStore,
)
from sectum.config import (
    AdapterConfig,
    SectumConfig,
    build_adapters,
    build_cache,
    build_mcp,
    build_memory,
    build_model,
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


def test_build_vector_store_rejects_an_unwired_kind() -> None:
    with pytest.raises(ConfigError, match="not yet supported"):
        build_vector_store(AdapterConfig(kind="pgvector"))


def test_build_cache_fake_with_a_tenant_scoping_knob() -> None:
    isolated = build_cache(AdapterConfig(kind="fake"))
    assert isolated.supports(Capability.TENANT_SCOPED_KEYS)
    shared = build_cache(AdapterConfig(kind="fake", tenant_scoped=False))
    assert not shared.supports(Capability.TENANT_SCOPED_KEYS)


def test_build_cache_rejects_an_unwired_kind() -> None:
    with pytest.raises(ConfigError, match="not yet supported"):
        build_cache(AdapterConfig(kind="redis"))


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
