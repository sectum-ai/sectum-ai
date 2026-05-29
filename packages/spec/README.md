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

- Documentation: <https://docs.sectum.ai>
- Source: <https://github.com/sectum-ai/sectum-ai>

Apache-2.0.
