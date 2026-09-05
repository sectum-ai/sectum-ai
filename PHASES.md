# Build phases and acceptance

Sectum AI was built in six phases (the engineering spec, §14), each closed by a
STOP-and-summarize against its acceptance criteria. This file is the durable
record of that gate: what each phase committed to, and where the evidence lives.
Status as of the current `main` (the phase gates below closed at v0.1.0; every
release since has added to them — see the CHANGELOG for what each one shipped).

| Phase | Acceptance criterion | Status | Evidence |
|---|---|---|---|
| **0 — Repo foundation** | `uv sync` works; CI green; `SECURITY.md` with a disclosure policy; branch protection documented | ✅ Met | `.github/workflows/`, `SECURITY.md`, `CONTRIBUTING.md` |
| **1 — Marker substrate** | reproducibility invariant (same seed → identical manifest); zero-FP (no manifest marker ⇒ never a confirmed finding); 4-tenant scenario with shared entities | ✅ Met | `tests/invariants/test_reproducibility.py` (incl. a pinned golden manifest hash), `tests/invariants/test_properties.py`, `tests/unit/test_detection.py` |
| **2 — Adapters v1 + Probe interface** | adapter contract tests for all fakes + pgvector/Chroma live via docker-compose; `sectum-ai adapters` lists capabilities | ✅ Met | fake contract tests pass, `sectum-ai adapters` works, and the live docker-compose backends (pgvector, Chroma, Weaviate, Redis, Phoenix) are exercised by the dedicated **Integration** CI job — gated by an HTTP readiness poll so a backend cannot silently self-skip (`.github/workflows/ci.yml`). Closed by **P6**. |
| **3 — Wedge + flagship + evidence** | `examples/retrieval-pivot` emits an RPR; `examples/erasure-attestation` produces a signed PDF that `sectum-ai verify` validates; tampering fails verify | ✅ Met | `tests/e2e/test_examples.py`, `tests/invariants/test_sample_packs_verify.py`, `tests/unit/test_cli_erasure.py` |
| **4 — Killer demo + remaining v1 probes** | a clean machine reproduces the headline demo from `README` in <10 min; docs build and deploy | ✅ Met | `examples/retrieval-pivot/run.sh`, `mkdocs build --strict` in CI, the Pages deploy workflow |
| **5 — Hardening + remaining classes** | full suite runs against the demo stack; baseline compare detects an injected regression (e.g. swap embedding model → RPR change flagged) | ✅ Met | full suite ✅ (`sectum-ai probe`); regression detection ✅ (`tests/unit/test_baseline.py`, `test_diff.py`, `test_cli_pipeline.py::test_baseline_compare_flags_an_injected_regression`); the embedding-strength gradient and the model-swap → regression path are proven (`test_sweep.py`); and the **full-CLI** path is now closed — `scenario.embedding_models` is configurable end to end and `tests/unit/test_cli_pipeline.py::test_full_cli_sweep_records_per_model_rpr` seeds two embedding models and asserts `probe` records the per-model Retrieval-Pivot Rate with the expected gradient (P5). |

## Known follow-ons

Tracked in the post-release next-scope roadmap (the strategic review):

- **P5** — ✅ shipped: the provider-agnostic embedding interface, the real-provider sweep, and the `scenario.embedding_models` config wiring (`sectum-ai seed --embedding-model`), which closed the Phase-5 *full-CLI* model-swap criterion above.
- **P6** — ✅ shipped: the docker-compose integration-CI job (the **Integration** workflow job), which closed the Phase-2 live-backend criterion above.
- **P7** — ✅ shipped: a `BackupAdapter` (the seventh erasure hiding place); live search-index (OpenSearch) and eval-set (LangSmith Datasets) connectors shipped; a Zep memory connectors remain a follow-on.

This record is updated whenever a phase criterion changes status.
