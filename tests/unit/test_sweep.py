"""Tests for the Class 2 embedding-model sweep (the engineering spec, section 7)."""

from sectum.baseline import compare_metrics
from sectum.spec import RunMetrics
from sectum.substrate import build_substrate, default_scenario
from sectum.sweep import embedding_model_sweep, model_recall

_MODELS = ("fake-mini", "fake-base", "fake-strong")


def test_sweep_reports_a_rate_per_model() -> None:
    rates = embedding_model_sweep(build_substrate(default_scenario(seed=2026)), _MODELS)
    assert set(rates) == set(_MODELS)


def test_stronger_embeddings_leak_more() -> None:
    # The Retrieval-Pivot Rate rises with embedding strength (section 7).
    rates = embedding_model_sweep(build_substrate(default_scenario(seed=2026)), _MODELS)
    assert rates["fake-mini"] < rates["fake-base"] < rates["fake-strong"]
    # Full recall surfaces every cross-tenant pivot document.
    assert rates["fake-strong"] == 1.0


def test_sweep_is_deterministic() -> None:
    substrate = build_substrate(default_scenario(seed=7))
    assert embedding_model_sweep(substrate, _MODELS) == embedding_model_sweep(substrate, _MODELS)


def test_model_recall_mapping() -> None:
    assert model_recall("fake-mini") == 0.2
    assert model_recall("fake-base") == 0.5
    assert model_recall("fake-strong") == 1.0
    # an unconfigured (e.g. real) model name defaults to full recall
    assert model_recall("text-embedding-3-large") == 1.0


def test_embedding_model_swap_is_flagged_as_a_regression() -> None:
    # Phase-5 acceptance (the spec, §14): swapping to a stronger embedding model
    # raises the Retrieval-Pivot Rate, and the regression gate flags it. Chains the
    # per-model sweep into compare_metrics end to end (PHASES.md, Phase 5).
    substrate = build_substrate(default_scenario(seed=2026))
    weak = embedding_model_sweep(substrate, ("fake-mini",))
    strong = embedding_model_sweep(substrate, ("fake-strong",))
    assert strong["fake-strong"] > weak["fake-mini"]
    baseline = RunMetrics(retrieval_pivot_rate_by_model=weak)
    current = RunMetrics(retrieval_pivot_rate_by_model=strong)
    assert compare_metrics(baseline, current).regressed
