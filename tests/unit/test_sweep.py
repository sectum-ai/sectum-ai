"""Tests for the Class 2 embedding-model sweep (the engineering spec, section 7)."""

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
