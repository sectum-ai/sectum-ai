"""JSON Schema export for the Sectum AI data models (the engineering spec, section 9).

The Pydantic models in :mod:`sectum_ai.spec.models` are authoritative. This module
projects them to standalone, version-pinned JSON Schema documents so external
tooling (dashboards, validators, other languages) can consume the spec without
importing Python. The committed artifacts live in :data:`SCHEMA_DIR` and ship in
the wheel; ``scripts/gen_schemas.py`` regenerates them and
``tests/unit/test_schema_export.py`` fails if one drifts from the models.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from sectum_ai.spec import models
from sectum_ai.spec.models import SCHEMA_VERSION

_DIALECT = "https://json-schema.org/draft/2020-12/schema"
"""The JSON Schema dialect Pydantic v2 emits; declared in each artifact's ``$schema``."""

_ID_BASE = "https://schemas.sectum.ai"
"""Base URI for a model's ``$id``; the schema version pins the artifact revision."""

_EXPORTED: tuple[type[BaseModel], ...] = (
    models.Scenario,
    models.Marker,
    models.CorpusDocument,
    models.GroundTruthManifest,
    models.Substrate,
    models.ProbeStep,
    models.Observation,
    models.Finding,
    models.RunMetrics,
    models.RunResult,
    models.ControlMapping,
    models.EvidencePack,
    models.ClassScore,
    models.IsolationScore,
)

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
"""Directory of committed, packaged JSON Schema artifacts (one file per model)."""


def schema_id(name: str) -> str:
    """Return the stable, version-pinned ``$id`` URI for a model's JSON Schema."""
    return f"{_ID_BASE}/{SCHEMA_VERSION}/{name}.schema.json"


def json_schemas() -> dict[str, dict[str, Any]]:
    """Return a mapping of model name to its JSON Schema.

    Each schema carries a ``$schema`` dialect and a version-pinned ``$id`` so the
    exported artifacts are self-describing, standalone JSON Schema documents.
    """
    schemas: dict[str, dict[str, Any]] = {}
    for model in _EXPORTED:
        schema: dict[str, Any] = {"$schema": _DIALECT, "$id": schema_id(model.__name__)}
        schema.update(model.model_json_schema())
        schemas[model.__name__] = schema
    return schemas


def serialize_schema(schema: dict[str, Any]) -> str:
    """Render a schema in the canonical on-disk form (sorted keys, trailing newline).

    The single source of truth for the artifact byte layout, so the generator and
    the drift test agree without duplicating the format.
    """
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write_json_schemas(dest: Path) -> list[Path]:
    """Write one ``<ModelName>.schema.json`` file per model into ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, schema in json_schemas().items():
        path = dest / f"{name}.schema.json"
        path.write_text(serialize_schema(schema), encoding="utf-8")
        written.append(path)
    return written
