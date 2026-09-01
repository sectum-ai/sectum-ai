"""Classes 6 and 13 run only where their mechanism exists.

Both describe a *vector-space* effect. Class 6 reconstructs a foreign entity
from a partial fragment and reports it as ``AML.T0024.001 Invert ML Model``;
Class 13 is the Retrieval Pivot through a shared multi-modal embedding space.

A store that matches on substrings can return a whole document for a fragment
query with no embedding involved. Ungated, that keyword hit was recorded as
embedding inversion - a real result attributed to a mechanism the backend does
not have - and, worse, a store finding nothing scored the class ``PASS``: credit
for a check that could not be performed. Both directions are the prime
directive's failure mode, so the probes are skipped instead, which scores
``NOT_COVERED``.
"""

from typing import Any

import pytest

from sectum_ai.adapters import Capability, FakeVectorStore
from sectum_ai.adapters.base import VectorStoreAdapter
from sectum_ai.cli.app import _skip_inapplicable
from sectum_ai.config import AdapterBundle, build_adapters
from sectum_ai.probes import EmbeddingInversionProbe, MultimodalRagBleedProbe
from sectum_ai.spec import ClassVerdict

_GATED = ("embedding-inversion", "multimodal-rag-bleed")


class KeywordStore(FakeVectorStore):
    """A store whose ``query`` is not embedding-backed (an app's own search API)."""

    semantic_retrieval = False


def _bundle(vector: VectorStoreAdapter) -> AdapterBundle:
    from sectum_ai.config import SectumConfig

    bundle = build_adapters(SectumConfig())
    return AdapterBundle(
        vector=vector,
        cache=bundle.cache,
        model=bundle.model,
        mcp=bundle.mcp,
        memory=bundle.memory,
        rag=bundle.rag,
        observability=bundle.observability,
        agent=bundle.agent,
    )


def test_every_shipped_vector_store_reports_the_capability_by_default() -> None:
    # Defaulted on the family base rather than declared per adapter, so the eight
    # live stores and the fake cannot individually forget it - a miss would drop
    # two classes to NOT_COVERED for that backend with nothing to catch it.
    assert FakeVectorStore().supports(Capability.SEMANTIC_RETRIEVAL)
    assert VectorStoreAdapter.semantic_retrieval is True


def test_opting_out_drops_only_that_capability() -> None:
    store = KeywordStore()
    assert not store.supports(Capability.SEMANTIC_RETRIEVAL)
    assert store.supports(Capability.PER_TENANT_NAMESPACE)


@pytest.mark.parametrize("probe", [EmbeddingInversionProbe, MultimodalRagBleedProbe])
def test_both_classes_declare_the_gate(probe: Any) -> None:
    assert probe.requires_any_capability == (Capability.SEMANTIC_RETRIEVAL,)


def test_a_semantic_store_still_runs_both_classes() -> None:
    # Behaviour-preserving for every backend shipping today.
    suite = (EmbeddingInversionProbe(None), MultimodalRagBleedProbe(None))
    runnable, skipped = _skip_inapplicable(suite, _bundle(FakeVectorStore()))
    assert {p.id for p in runnable} == set(_GATED)
    assert skipped == []


def test_a_keyword_store_skips_both_classes_with_a_stated_reason() -> None:
    suite = (EmbeddingInversionProbe(None), MultimodalRagBleedProbe(None))
    runnable, skipped = _skip_inapplicable(suite, _bundle(KeywordStore()))
    assert runnable == ()
    assert {probe_id for probe_id, _ in skipped} == set(_GATED)
    assert all(reason == Capability.SEMANTIC_RETRIEVAL.value for _, reason in skipped)


def test_a_skipped_class_scores_not_covered_never_pass() -> None:
    """The point of the gate: silence must not read as a clean result.

    A skipped probe is absent from ``probe_versions``, and scorecard rule 1 turns
    that into NOT_COVERED. Ungated, the same run recorded PASS for a class whose
    mechanism the backend does not have.
    """
    from datetime import UTC, datetime

    from sectum_ai.score import score_run
    from sectum_ai.spec import RunResult

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    run = RunResult(
        run_id="r",
        scenario_hash="a" * 64,
        manifest_hash="b" * 64,
        started_at=moment,
        finished_at=moment,
        # tenant-boundary ran; the two gated probes did not.
        probe_versions={"tenant-boundary-fetch": "1.0"},
    )
    by_id = {c.class_id: c for c in score_run(run).classes}
    assert by_id[6].verdict is ClassVerdict.NOT_COVERED
    assert by_id[13].verdict is ClassVerdict.NOT_COVERED
    assert by_id[1].verdict is ClassVerdict.PASS
