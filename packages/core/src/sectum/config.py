"""Read and validate ``sectum.yaml`` (the engineering spec, section 10).

The CLI flag ``--config sectum.yaml`` loads a ``SectumConfig``: a typed view
of the configuration that ``sectum init`` scaffolds. Explicit CLI flags
override the values the config supplies, and the config supplies values the
built-in defaults would otherwise use.

Credentials never appear inline in the file. Adapter blocks reference
environment variables (for example ``dsn_env: SECTUM_PGVECTOR_DSN``) so the
adapter resolver looks them up at run time.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sectum.spec import ConfigError


class ScenarioConfig(BaseModel):
    """Scenario settings driving substrate generation."""

    model_config = ConfigDict(extra="forbid")

    seed: int = 2026
    corpus_profile: str = "demo"


class AdapterConfig(BaseModel):
    """One adapter's configuration: a kind plus any backend-specific fields.

    The resolver dispatches on ``kind`` (for example ``fake``, ``pgvector``,
    ``chroma``, ``redis``) and reads backend-specific fields from the extra
    keys (for example ``host``, ``port``, ``dsn_env``).
    """

    model_config = ConfigDict(extra="allow")

    kind: str


class EvidenceConfig(BaseModel):
    """Evidence-chain anchoring settings."""

    model_config = ConfigDict(extra="forbid")

    timestamper: Literal["local", "rfc3161"] = "local"
    tsa_url: str | None = None
    rekor_url: str | None = None


class SectumConfig(BaseModel):
    """The parsed ``sectum.yaml`` configuration."""

    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioConfig = Field(default_factory=ScenarioConfig)
    workdir: Path = Path(".sectum")
    adapters: dict[str, AdapterConfig] = Field(default_factory=dict)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)


def load_config(path: Path) -> SectumConfig:
    """Load and validate a ``sectum.yaml`` configuration file.

    Raises:
        ConfigError: if the file is missing, contains malformed YAML, or fails
            schema validation.
    """
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {path}: {error}") from error
    if raw is None:
        return SectumConfig()
    if not isinstance(raw, dict):
        raise ConfigError(f"config file must be a YAML mapping: {path}")
    try:
        return SectumConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(f"invalid config in {path}: {error}") from error
