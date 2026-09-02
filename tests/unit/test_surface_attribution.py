"""Provenance and grading agree with the adapter about which surface it is.

#305 stopped the runner stamping `Surface.VECTOR_DB` onto every `vector.*`
observation and read the adapter instead - but only in ``runner.py``.
``surface_provenance`` carried the identical coupling: liveness came off the
adapter instance while the *key* came from a static slot -> surface map. An
adapter declaring a different surface would therefore have produced findings
labelled one way and a provenance block keyed another, inside one signed record.

The scorecard is the third place the same fact is needed, and it cannot read the
adapter at all - it re-grades a record it did not produce. So when a run names a
surface the catalog cannot tie to a class, it fails closed (rule 6) rather than
grading a verdict about a system it cannot identify.
"""

from datetime import UTC, datetime

import pytest

from sectum_ai.adapters import FakeVectorStore
from sectum_ai.config import (
    _BUNDLE_SLOTS,
    AdapterBundle,
    SectumConfig,
    build_adapters,
    surface_provenance,
)
from sectum_ai.score import score_run
from sectum_ai.spec import (
    ClassVerdict,
    ConfigError,
    RunResult,
    Surface,
    SurfaceProvenance,
)

_ALL_PROBES = (
    "tenant-boundary-fetch",
    "rag-entity-bleed",
    "semantic-cache-contamination",
)


class ApiBackedStore(FakeVectorStore):
    """An application's own resource API filling the vector slot - a supported case."""

    surface = Surface.API


class MisdeclaredStore(FakeVectorStore):
    """A slot filled by something the catalog cannot place at all.

    ``prompt_logs`` is a real surface that no probe's slot speaks for, so a run
    reporting it against the vector slot is exactly the case rule 6 exists for.
    """

    surface = Surface.PROMPT_LOGS


def _bundle(vector: FakeVectorStore) -> AdapterBundle:
    base = build_adapters(SectumConfig())
    return AdapterBundle(
        vector=vector,
        cache=base.cache,
        model=base.model,
        mcp=base.mcp,
        memory=base.memory,
        rag=base.rag,
        observability=base.observability,
        agent=base.agent,
    )


def _run(provenance: dict[str, str]) -> RunResult:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    return RunResult(
        run_id="r",
        scenario_hash="a" * 64,
        manifest_hash="b" * 64,
        started_at=moment,
        finished_at=moment,
        probe_versions=dict.fromkeys(_ALL_PROBES, "1.0"),
        surface_provenance=provenance,
    )


def test_provenance_keys_come_from_the_adapter() -> None:
    provenance = surface_provenance(_bundle(ApiBackedStore()))
    assert Surface.API.value in provenance
    assert Surface.VECTOR_DB.value not in provenance


def test_provenance_is_unchanged_for_every_adapter_shipping_today() -> None:
    # The swap from a static map to the adapter must be behaviour-preserving: each
    # family base declares exactly the surface the old map assigned to its slot.
    bundle = build_adapters(SectumConfig())
    provenance = surface_provenance(bundle)
    assert set(provenance) == {getattr(bundle, slot).surface.value for slot in _BUNDLE_SLOTS}
    assert set(provenance) == {
        Surface.VECTOR_DB.value,
        Surface.SEMANTIC_CACHE.value,
        Surface.MODEL_ADAPTER.value,
        Surface.MCP.value,
        Surface.AGENT_MEMORY.value,
        Surface.RAG_PIPELINE.value,
        Surface.TRACING.value,
        Surface.AGENT_FRAMEWORK.value,
    }


def test_every_bundle_slot_is_covered() -> None:
    import dataclasses

    assert set(_BUNDLE_SLOTS) == {f.name for f in dataclasses.fields(AdapterBundle)}


def test_a_class_run_against_an_unaccountable_surface_is_not_covered() -> None:
    # Rule 6: the vector-slot classes ran against a surface no probe's slot speaks
    # for, so the catalog cannot say what the result describes.
    provenance = surface_provenance(_bundle(MisdeclaredStore()))
    by_id = {c.class_id: c for c in score_run(_run(provenance)).classes}
    assert by_id[1].verdict is ClassVerdict.NOT_COVERED
    assert "cannot" in (by_id[1].note or "")
    # The cache class is unaffected: its surface is accounted for.
    assert by_id[4].verdict is ClassVerdict.PASS


def test_an_ordinary_run_is_graded_exactly_as_before() -> None:
    provenance = surface_provenance(build_adapters(SectumConfig()))
    by_id = {c.class_id: c for c in score_run(_run(provenance)).classes}
    assert by_id[1].verdict is ClassVerdict.PASS
    assert by_id[4].verdict is ClassVerdict.PASS


def test_a_record_with_no_provenance_is_exempt_from_rule_6() -> None:
    # A run produced before the block existed. Absence is not evidence of a
    # mismatch, so it grades as it always did rather than collapsing to
    # NOT_COVERED across the board.
    by_id = {c.class_id: c for c in score_run(_run({})).classes}
    assert by_id[1].verdict is ClassVerdict.PASS


def test_the_note_states_only_what_the_scorecard_knows() -> None:
    # The run records WHICH surfaces it exercised, not which one backed this class.
    # Naming the others would imply exactly the attribution rule 6 refuses to make.
    provenance = surface_provenance(_bundle(MisdeclaredStore()))
    entry = next(c for c in score_run(_run(provenance)).classes if c.class_id == 1)
    note = entry.note or ""
    assert "expected one of api, vector_db" in note
    assert "none of which" in note
    # The unrelated surfaces this run happened to exercise must not appear.
    assert Surface.AGENT_MEMORY.value not in note
    assert Surface.MCP.value not in note


def test_a_run_whose_every_class_is_unattributable_refuses_to_grade() -> None:
    # Rule 6 can withhold everything. A letter over zero covered classes would mean
    # nothing, and `F` would read as "failed" when the truth is "cannot attribute" -
    # the same reason score_run refuses a run that exercised no class at all.
    provenance = surface_provenance(_bundle(MisdeclaredStore()))
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    run = RunResult(
        run_id="r",
        scenario_hash="a" * 64,
        manifest_hash="b" * 64,
        started_at=moment,
        finished_at=moment,
        probe_versions={"tenant-boundary-fetch": "1.0"},
        surface_provenance=provenance,
    )
    with pytest.raises(ConfigError, match="nothing to grade"):
        score_run(run)


def test_rule_6_outranks_the_synthetic_withholding_of_rule_5() -> None:
    # Both could apply to an all-fake API-backed run. "We cannot identify what this
    # describes" is the stronger statement, and it must not be masked by the
    # softer "this was a fake" note.
    provenance = surface_provenance(_bundle(MisdeclaredStore()))
    provenance[Surface.SEMANTIC_CACHE.value] = SurfaceProvenance.LIVE.value
    entry = next(c for c in score_run(_run(provenance)).classes if c.class_id == 1)
    assert entry.verdict is ClassVerdict.NOT_COVERED
    assert "attribute" in (entry.note or "")
