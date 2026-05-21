"""Tests for the JSON Schema export (the engineering spec, section 9)."""

import json
from pathlib import Path

from sectum.spec import json_schemas, write_json_schemas


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
