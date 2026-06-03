# sectum-ai-spec

Shared data models and JSON Schema for [Sectum AI](https://github.com/sectum-ai/sectum-ai),
the multi-tenant AI verification toolkit.

This distribution holds the Pydantic v2 models and exported JSON Schema that
every other Sectum package builds on — `Scenario`, `Marker`,
`GroundTruthManifest`, `ProbeStep`, `Observation`, `Finding`, `RunResult`, and
`EvidencePack` — plus the typed error hierarchy (`SectumError` and friends).
It is the lowest layer in the package graph and depends on nothing else in the
family.

```sh
pip install sectum-ai-spec
```

Most users install the umbrella package [`sectum-ai`](https://pypi.org/project/sectum-ai/)
instead, which pulls this in automatically.

## JSON Schema

Every model is also published as a standalone JSON Schema document under
`sectum_ai/spec/schemas/<Model>.schema.json` (shipped in the wheel). Each carries a
`$schema` dialect (draft 2020-12) and a version-pinned `$id`
(`https://schemas.sectum.ai/<schema_version>/<Model>.schema.json`), so external
tooling can validate Sectum artifacts without importing Python:

```python
from sectum_ai.spec import json_schemas
from sectum_ai.spec.schema import SCHEMA_DIR  # the committed, packaged artifacts

finding_schema = json_schemas()["Finding"]
```

The Pydantic models are authoritative; the schemas are generated from them.
Regenerate after a model change with `uv run python scripts/gen_schemas.py`
(a test fails if a committed artifact drifts). The `schema_version` field
versions the models — bump it for a backward-incompatible change, then regenerate.

- Documentation: <https://docs.sectum.ai>
- Source: <https://github.com/sectum-ai/sectum-ai>

Apache-2.0.
