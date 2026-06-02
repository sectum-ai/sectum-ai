# Build phases and acceptance

Sectum AI was built in six phases (the engineering spec, §14), each closed by a
STOP-and-summarize against its acceptance criteria. This file is the durable
record of that gate: what each phase committed to, and where the evidence lives.
Status as of v0.1.0 plus the post-release hardening on `main`.

| Phase | Acceptance criterion | Status | Evidence |
|---|---|---|---|
| **0 — Repo foundation** | `uv sync` works; CI green; `SECURITY.md` with a disclosure policy; branch protection documented | ✅ Met | `.github/workflows/`, `SECURITY.md`, `CONTRIBUTING.md` |
| **1 — Marker substrate** | reproducibility invariant (same seed → identical manifest); zero-FP (no manifest marker ⇒ never a confirmed finding); 4-tenant scenario with shared entities | ✅ Met | `tests/invariants/test_reproducibility.py` (incl. a pinned golden manifest hash), `tests/invariants/test_properties.py`, `tests/unit/test_detection.py` |
| **2 — Adapters v1 + Probe interface** | adapter contract tests for all fakes + pgvector/Chroma live via docker-compose; `sectum adapters` lists capabilities | ⚠️ Partial | fake contract tests pass and `sectum adapters` works; the **live docker-compose backends are not yet exercised in CI** (the 12 integration tests self-skip offline) — closed by **P6** |
| **3 — Wedge + flagship + evidence** | `examples/retrieval-pivot` emits an RPR; `examples/erasure-attestation` produces a signed PDF that `sectum verify` validates; tampering fails verify | ✅ Met | `tests/e2e/test_examples.py`, `tests/invariants/test_sample_packs_verify.py`, `tests/unit/test_cli_erasure.py` |
| **4 — Killer demo + remaining v1 probes** | a clean machine reproduces the headline demo from `README` in <10 min; docs build and deploy | ✅ Met | `examples/retrieval-pivot/run.sh`, `mkdocs build --strict` in CI, the Pages deploy workflow |
| **5 — Hardening + remaining classes** | full suite runs against the demo stack; baseline compare detects an injected regression (e.g. swap embedding model → RPR change flagged) | ⚠️ Partial | full suite ✅ (`sectum probe`); regression detection ✅ (`tests/unit/test_baseline.py`, `test_diff.py`, `test_cli_pipeline.py::test_baseline_compare_flags_an_injected_regression`); the embedding-strength **gradient** is proven (`test_sweep.py::test_stronger_embeddings_leak_more`) and the **model-swap → regression** path is proven end to end (`test_sweep.py::test_embedding_model_swap_is_flagged_as_a_regression`). A **full-CLI** model-swap run needs multi-embedding-model config (the sweep runs only with >1 model, not yet CLI-configurable) — closed by **P5** |

## Known follow-ons

Tracked in the post-release next-scope roadmap (the strategic review):

- **P5** — multi-embedding-model config + a live-provider sweep, which also unlocks the Phase-5 *full-CLI* model-swap regression E2E.
- **P6** — a docker-compose integration-CI job + a live-adapter contract conformance suite (closes the Phase-2 live-backend criterion).
- **P7** — field-complete erasure: a `BackupAdapter` plus live search-index / eval-set adapters.

This record is updated whenever a phase criterion changes status.
