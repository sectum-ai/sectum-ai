"""Tests for the Class 2 embedding-model sweep (the engineering spec, section 7)."""

import pytest

from sectum_ai.adapters import FakeVectorStore
from sectum_ai.baseline import compare_metrics
from sectum_ai.cli.app import _per_model_rpr
from sectum_ai.spec import RunMetrics, Scenario
from sectum_ai.substrate import build_substrate, default_scenario
from sectum_ai.sweep import embedding_model_sweep, model_recall

_MODELS = ("fake-mini", "fake-base", "fake-strong")


def _scenario_with_models(*models: str, seed: int = 2026) -> Scenario:
    return default_scenario(seed=seed).model_copy(update={"embedding_models": models})


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


def test_per_model_rpr_uses_real_providers_even_on_a_non_fake_intent() -> None:
    # Two real (hashing) providers -> the genuine cosine sweep, recorded whatever
    # the production store is. This is the P5 fix: the per-model gradient no longer
    # vanishes off the in-memory fake.
    substrate = build_substrate(_scenario_with_models("hash-32", "hash-256"))
    rates = _per_model_rpr(substrate, FakeVectorStore())
    assert set(rates) == {"hash-32", "hash-256"}
    assert rates["hash-32"] < rates["hash-256"]


def test_per_model_rpr_falls_back_to_the_recall_illustration_for_fake_names() -> None:
    substrate = build_substrate(_scenario_with_models(*_MODELS))
    rates = _per_model_rpr(substrate, FakeVectorStore())
    assert rates["fake-mini"] < rates["fake-base"] < rates["fake-strong"]


def test_per_model_rpr_is_empty_for_a_single_model() -> None:
    substrate = build_substrate(_scenario_with_models("hash-256"))
    assert _per_model_rpr(substrate, FakeVectorStore()) == {}


def test_a_mixed_config_says_which_models_it_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    # `fake-*` names carry a modelled recall, not real vectors, so they cannot be
    # compared against a real provider - but they were dropped SILENTLY. An
    # operator who configured three models saw a two-model gradient with nothing
    # saying the third was excluded, which is the config not being honoured
    # without being told.
    substrate = build_substrate(_scenario_with_models("hash-32", "hash-256", "fake-mini"))
    rates = _per_model_rpr(substrate, FakeVectorStore())
    assert set(rates) == {"hash-32", "hash-256"}  # the real pair still compares
    output = capsys.readouterr().out
    assert "fake-mini" in output
    assert "excluded from the embedding-model gradient" in output


def test_one_real_model_among_fakes_is_not_reported_as_a_gradient(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The two-model guard counted CONFIGURED names, not comparable ones, so this
    # config produced a single-entry "gradient" - a comparison of one model
    # against nothing, recorded into the run's metrics as if it were a sweep.
    substrate = build_substrate(_scenario_with_models("hash-256", "fake-mini"))
    assert _per_model_rpr(substrate, FakeVectorStore()) == {}
    output = capsys.readouterr().out
    assert "two or more real embedding models" in output
