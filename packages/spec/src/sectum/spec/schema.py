"""JSON Schema export for the Sectum AI data models (the engineering spec, section 9)."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from sectum.spec import models

_EXPORTED: tuple[type[BaseModel], ...] = (
    models.Scenario,
    models.Marker,
    models.CorpusDocument,
    models.GroundTruthManifest,
    models.Substrate,
    models.ProbeStep,
    models.Observation,
    models.Finding,
    models.RunResult,
    models.EvidencePack,
)


def json_schemas() -> dict[str, dict[str, Any]]:
    """Return a mapping of model name to its JSON Schema."""
    return {model.__name__: model.model_json_schema() for model in _EXPORTED}


def write_json_schemas(dest: Path) -> list[Path]:
    """Write one ``<ModelName>.schema.json`` file per model into ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, schema in json_schemas().items():
        path = dest / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written
