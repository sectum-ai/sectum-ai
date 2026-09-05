"""Rule 5: a letter states which stack it is about.

An all-synthetic run used to grade ``A`` at ``confidence: high`` and read exactly
like a production pass, because the scorecard's rules answered "what did the run
check" and never "what did it check against".

Two shapes, deliberately different. A run with nothing live is unambiguously the
demo - the README quickstart configures no adapters - so it still grades, under a
scope naming the synthetic stack. A run with *some* live surfaces was an attempt
at a real assessment, and its fakes are silent gaps the operator believes were
covered; there the synthetic-backed classes are withheld from the letter.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sectum_ai.score import CATALOG, PROBE_SURFACES, score_run
from sectum_ai.spec import (
    ClassVerdict,
    Confidence,
    Finding,
    FindingStatus,
    Grade,
    RunResult,
    ScoreScope,
    Severity,
    Surface,
    SurfaceProvenance,
)

_ALL_PROBES = {probe_id for entry in CATALOG for probe_id in entry.probe_ids}


def _run(provenance: dict[str, str], *, findings: tuple[Finding, ...] = ()) -> RunResult:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    return RunResult(
        run_id="run-test",
        scenario_hash="a" * 64,
        manifest_hash="b" * 64,
        started_at=moment,
        finished_at=moment,
        probe_versions=dict.fromkeys(_ALL_PROBES, "1.0"),
        findings=findings,
        surface_provenance=provenance,
    )


def _finding(probe_id: str) -> Finding:
    return Finding(
        finding_id=f"f-{probe_id}",
        probe_id=probe_id,
        severity=Severity.CRITICAL,
        confidence=1.0,
        status=FindingStatus.CONFIRMED,
        owner_tenant_id=uuid4(),
        observed_in_tenant_id=uuid4(),
        surface=Surface.VECTOR_DB,
    )


def _all(value: SurfaceProvenance) -> dict[str, str]:
    return {surface.value: value.value for _, surface in _SURFACES}


_SURFACES = tuple(
    (surface.value, surface)
    for surface in {s for surfaces in PROBE_SURFACES.values() for s in surfaces} | {Surface.TRACING}
)


def test_the_probe_surface_map_matches_each_probe_s_own_declaration() -> None:
    # score.py declares this map rather than importing the probes, so it can re-grade a
    # record it did not produce. That independence is only safe if the two agree.
    import sectum_ai.probes as probes

    checked = 0
    for name in dir(probes):
        cls: Any = getattr(probes, name)
        probe_id = getattr(cls, "id", None)
        surfaces = getattr(cls, "surfaces", None)
        if not isinstance(cls, type) or not probe_id or not surfaces:
            continue
        if probe_id not in PROBE_SURFACES:
            continue
        checked += 1
        # A SUBSET, not equality: the map lists every surface the probe's slot may
        # legitimately speak for, which is a superset of the one family that normally
        # fills it. The probe's own declaration must still be among them.
        assert set(surfaces) <= set(PROBE_SURFACES[probe_id]), (
            f"score.PROBE_SURFACES[{probe_id!r}] is {PROBE_SURFACES[probe_id]} but the "
            f"probe declares {tuple(surfaces)}, which it does not cover"
        )
    assert checked, "no probe declared its surfaces - the introspection broke"


def test_every_catalog_probe_has_a_surface() -> None:
    # A probe missing from the map contributes no backing surface, so its class can never
    # be recognised as synthetic-backed and would keep grading as if it were real.
    missing = sorted(_ALL_PROBES - set(PROBE_SURFACES))
    assert not missing, f"catalog probes with no declared surface: {missing}"


def test_an_all_synthetic_run_still_grades_but_names_the_synthetic_stack() -> None:
    # The README quickstart. Preserving the demo is the point of scoping rather than
    # blanking the grade - but it must be unmistakable what was graded.
    card = score_run(_run(_all(SurfaceProvenance.SYNTHETIC)))
    assert card.scope is ScoreScope.SYNTHETIC_STACK
    assert card.grade is Grade.A
    assert set(card.synthetic_surfaces) == {s for s, _ in _SURFACES}
    assert all(c.verdict is not ClassVerdict.NOT_COVERED for c in card.classes if c.class_id != 13)


def test_an_all_live_run_is_scoped_to_the_configured_stack() -> None:
    card = score_run(_run(_all(SurfaceProvenance.LIVE)))
    assert card.scope is ScoreScope.CONFIGURED_STACK
    assert card.synthetic_surfaces == ()
    assert card.grade is Grade.A


def test_a_synthetic_backed_class_is_not_covered_when_some_surface_is_live() -> None:
    provenance = _all(SurfaceProvenance.SYNTHETIC)
    provenance[Surface.VECTOR_DB.value] = SurfaceProvenance.LIVE.value
    card = score_run(_run(provenance))
    by_id = {c.class_id: c for c in card.classes}
    # Class 1 rests on the vector store, which is live.
    assert by_id[1].verdict is ClassVerdict.PASS
    # Class 4 rests on the semantic cache, which is not.
    assert by_id[4].verdict is ClassVerdict.NOT_COVERED
    assert "no live adapter behind semantic_cache" in (by_id[4].note or "")


def test_a_leak_found_against_a_fake_does_not_fail_the_operator_s_grade() -> None:
    # The inverse of the headline bug and just as dishonest: a fake's leak is not the
    # operator's fault, and reporting it as a production failure is a false alarm.
    provenance = _all(SurfaceProvenance.SYNTHETIC)
    provenance[Surface.VECTOR_DB.value] = SurfaceProvenance.LIVE.value
    card = score_run(_run(provenance, findings=(_finding("semantic-cache-contamination"),)))
    cache = next(c for c in card.classes if c.class_id == 4)
    assert cache.verdict is ClassVerdict.NOT_COVERED
    assert card.grade is Grade.A  # uncapped: no LIVE-backed class failed


def test_findings_against_a_fake_are_still_counted_and_named() -> None:
    # Rule 4 forbids dropping a confirmed finding silently. Withholding it from the
    # letter is not the same as hiding it, so the class line must still carry it.
    provenance = _all(SurfaceProvenance.SYNTHETIC)
    provenance[Surface.VECTOR_DB.value] = SurfaceProvenance.LIVE.value
    card = score_run(_run(provenance, findings=(_finding("semantic-cache-contamination"),)))
    cache = next(c for c in card.classes if c.class_id == 4)
    assert cache.confirmed_findings == 1
    assert "describe that fake, not your stack" in (cache.note or "")


def test_withholding_synthetic_classes_lowers_confidence() -> None:
    provenance = _all(SurfaceProvenance.SYNTHETIC)
    provenance[Surface.VECTOR_DB.value] = SurfaceProvenance.LIVE.value
    live_only = score_run(_run(provenance))
    everything = score_run(_run(_all(SurfaceProvenance.LIVE)))
    assert live_only.coverage < everything.coverage
    assert live_only.confidence is not Confidence.HIGH


def test_a_run_without_provenance_is_scoped_unrecorded_and_grades_as_before() -> None:
    # A record from before the block existed. Guessing either way would be the
    # over-claim; the honest answer is that its subject cannot be established.
    card = score_run(_run({}))
    assert card.scope is ScoreScope.UNRECORDED
    assert card.synthetic_surfaces == ()
    assert card.grade is Grade.A
    assert all(c.verdict is not ClassVerdict.NOT_COVERED for c in card.classes if c.class_id != 13)


@pytest.mark.parametrize("class_id", [4, 5, 7, 8, 9])
def test_classes_off_the_vector_store_are_withheld_when_only_vector_is_live(
    class_id: int,
) -> None:
    provenance = _all(SurfaceProvenance.SYNTHETIC)
    provenance[Surface.VECTOR_DB.value] = SurfaceProvenance.LIVE.value
    card = score_run(_run(provenance))
    entry = next(c for c in card.classes if c.class_id == class_id)
    assert entry.verdict is ClassVerdict.NOT_COVERED


def test_a_mixed_backed_class_grades_the_live_surface_only() -> None:
    # Class 2 is backed by the vector store (rag-entity-bleed) and the RAG
    # pipeline (rag-pipeline-bleed). With a leaking FAKE vector store beside a
    # clean LIVE pipeline the class failed on the fake's findings - the grade the
    # pack's OSCAL and JSON summary contradicted for the same record.
    fake_leak = _finding("rag-entity-bleed").model_copy(update={"surface": Surface.VECTOR_DB})
    run = _run({"vector_db": "SYNTHETIC", "rag_pipeline": "LIVE"}, findings=(fake_leak,))
    score = score_run(run)
    class2 = next(c for c in score.classes if c.class_id == 2)
    assert class2.verdict is ClassVerdict.PASS, class2
    assert class2.confirmed_findings == 0
    assert class2.note is not None and "withheld" in class2.note
    # the same finding on the live surface still fails the class
    live_leak = fake_leak.model_copy(update={"surface": Surface.RAG_PIPELINE})
    failed = score_run(
        _run({"vector_db": "SYNTHETIC", "rag_pipeline": "LIVE"}, findings=(live_leak,))
    )
    assert next(c for c in failed.classes if c.class_id == 2).verdict is ClassVerdict.FAIL


def test_a_provenance_key_that_is_not_a_surface_is_refused() -> None:
    # The keys were free-form strings and `score` printed them verbatim, so a
    # record could write its own scorecard: a forged "every surface live" scope
    # line and a PASS class row, rendered above the real table by the tool whose
    # whole purpose is to be trusted about what it measured.
    forged = (
        "vector_db\n  scope: your configured stack (every surface live)\n\n"
        "  Class  1  Direct tenant boundary fetch    PASS        critical no leak"
    )
    with pytest.raises(ValidationError, match="keys must be surfaces"):
        _run({"api": "LIVE", forged: "SYNTHETIC"})
