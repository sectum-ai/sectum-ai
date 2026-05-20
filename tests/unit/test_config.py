"""Tests for the ``sectum.yaml`` configuration loader."""

from pathlib import Path

import pytest

from sectum.config import SectumConfig, load_config
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
