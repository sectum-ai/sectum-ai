"""Tests for the JSON Schema export (the engineering spec, section 9)."""

import json
from pathlib import Path

from sectum_ai.spec import SCHEMA_VERSION, json_schemas, write_json_schemas
from sectum_ai.spec.schema import SCHEMA_DIR, schema_id, serialize_schema


def test_write_json_schemas_writes_one_file_per_model(tmp_path: Path) -> None:
    paths = write_json_schemas(tmp_path)
    assert paths
    assert len(paths) == len(json_schemas())
    for path in paths:
        assert path.exists()
        assert json.loads(path.read_text())["type"] == "object"


def test_write_json_schemas_creates_a_missing_destination(tmp_path: Path) -> None:
    dest = tmp_path / "schemas" / "out"
    written = write_json_schemas(dest)
    assert dest.is_dir()
    assert all(path.parent == dest for path in written)


def test_committed_artifacts_match_the_models() -> None:
    """The committed ``schemas/`` artifacts must equal a fresh export.

    Regenerate with ``uv run python scripts/gen_schemas.py`` after any model change.
    """
    expected = json_schemas()
    committed = {p.name.removesuffix(".schema.json") for p in SCHEMA_DIR.glob("*.schema.json")}
    assert committed == set(expected), "committed schema set drifted from the models"
    for name, schema in expected.items():
        path = SCHEMA_DIR / f"{name}.schema.json"
        assert path.read_text(encoding="utf-8") == serialize_schema(schema), (
            f"{path.name} is stale; run scripts/gen_schemas.py"
        )


def test_each_schema_is_a_self_describing_versioned_document() -> None:
    for name, schema in json_schemas().items():
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == schema_id(name)
        assert SCHEMA_VERSION in schema["$id"]


def test_run_metrics_and_control_mapping_are_published() -> None:
    """The headline-metric block and the §18 control table are part of the
    published spec surface, not just internal models."""
    assert {"RunMetrics", "ControlMapping"} <= set(json_schemas())
