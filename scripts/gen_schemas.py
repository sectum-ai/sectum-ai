#!/usr/bin/env python
"""Generate the committed JSON Schema artifacts for the Sectum AI data models
(the engineering spec, section 9: "publish JSON Schema in ``sectum-ai-spec``").

The Pydantic models in ``sectum_ai.spec.models`` remain authoritative; this writes
their exported JSON Schema to ``sectum/spec/schemas/*.schema.json`` so the
distribution ships machine-readable, version-pinned schemas that external
tooling can consume without importing Python. Each artifact is a standalone
document carrying a ``$schema`` dialect and a version-pinned ``$id``.
``tests/unit/test_schema_export.py`` fails if a committed artifact drifts from
the models — regenerate after any model change.

Run from the repo root:  ``uv run python scripts/gen_schemas.py``
"""

from __future__ import annotations

from pathlib import Path

from sectum_ai.spec import SCHEMA_VERSION
from sectum_ai.spec.schema import SCHEMA_DIR, write_json_schemas


def main() -> int:
    written = write_json_schemas(SCHEMA_DIR)
    root = Path.cwd()
    for path in written:
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        print(f"wrote {rel}")
    print(f"\n{len(written)} JSON Schema artifacts generated (schema_version {SCHEMA_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
