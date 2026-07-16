"""Tests for the isolation scorecard (``sectum-ai score``, docs/scorecard.md).

The honesty rules are the point of this feature, so they are asserted directly: an
untested class can never be a PASS, coverage drives confidence and never the grade, and
the worst confirmed failure caps the letter.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from sectum_ai.score import CATALOG, METHODOLOGY_VERSION, SEVERITY_WEIGHTS, score_run
from sectum_ai.spec import (
    ClassVerdict,
    Confidence,
    ConfigError,
    Finding,
    FindingStatus,
    Grade,
    RunMetrics,
    RunResult,
    Severity,
    Surface,
)

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


def _finding(probe_id: str, status: FindingStatus = FindingStatus.CONFIRMED) -> Finding:
    return Finding(
        finding_id=f"f-{probe_id}-{status.value}",
        probe_id=probe_id,
        severity=Severity.CRITICAL,
        confidence=1.0,
        status=status,
        owner_tenant_id=_TENANT_B,
        observed_in_tenant_id=_TENANT_A,
        surface=Surface.VECTOR_DB,
    )


def _run(
    *,
    ran: tuple[str, ...],
    findings: tuple[Finding, ...] = (),
    metrics: RunMetrics | None = None,
) -> RunResult:
    now = datetime.now(UTC)
    return RunResult(
        run_id="run-test",
        scenario_hash="s" * 8,
        manifest_hash="m" * 8,
        started_at=now,
        finished_at=now,
        probe_versions=dict.fromkeys(ran, "1.0"),
        findings=findings,
        metrics=metrics or RunMetrics(),
    )


_ALL_PROBES = tuple(probe_id for entry in CATALOG for probe_id in entry.probe_ids)


def test_a_clean_full_run_grades_a_at_high_confidence() -> None:
    card = score_run(_run(ran=_ALL_PROBES))
    assert card.grade is Grade.A
    assert card.confidence is Confidence.HIGH
    assert card.coverage == pytest.approx(1.0)
    assert card.weighted_score == pytest.approx(1.0)
    assert card.capped_by is None
    assert all(c.verdict is ClassVerdict.PASS for c in card.classes)
    assert card.methodology_version == METHODOLOGY_VERSION


def test_an_untested_class_is_never_a_pass() -> None:
    # RULE 1 (the anti-over-claim core): a class whose probe did not run can only be
    # NOT_COVERED. A grade must never imply a check the stack never performed.
    card = score_run(_run(ran=("tenant-boundary-fetch",)))
    boundary = next(c for c in card.classes if c.class_id == 1)
    assert boundary.verdict is ClassVerdict.PASS  # it ran and was clean
    untested = [c for c in card.classes if c.class_id != 1]
    assert untested and all(c.verdict is ClassVerdict.NOT_COVERED for c in untested)
    assert all(c.note for c in untested)  # the gap is explained, never silently absent


def test_untested_classes_lower_confidence_not_the_grade() -> None:
    # RULE 2: a sliver of the catalog, all clean, still grades A - but the confidence
    # (not the letter) is what says the grade rests on almost nothing.
    thin = score_run(_run(ran=("tenant-boundary-fetch",)))
    full = score_run(_run(ran=_ALL_PROBES))
    assert thin.grade is full.grade is Grade.A  # identical letters...
    assert thin.confidence is Confidence.LOW  # ...distinguished only by confidence
    assert full.confidence is Confidence.HIGH
    assert thin.coverage < full.coverage
    assert thin.classes_covered == 1 and full.classes_covered == len(CATALOG)


def test_a_confirmed_critical_failure_caps_the_grade_at_f() -> None:
    # RULE 3: ten of eleven classes pass, but one confirmed critical leak floors it at F
    # - a weighted average must not average away a hole.
    card = score_run(_run(ran=_ALL_PROBES, findings=(_finding("tenant-boundary-fetch"),)))
    assert card.grade is Grade.F
    assert card.capped_by is Severity.CRITICAL
    assert card.weighted_score > 0.5  # the raw average alone would have graded well
    boundary = next(c for c in card.classes if c.class_id == 1)
    assert boundary.verdict is ClassVerdict.FAIL and boundary.confirmed_findings == 1


def test_a_confirmed_high_failure_caps_the_grade_at_d() -> None:
    card = score_run(_run(ran=_ALL_PROBES, findings=(_finding("rag-poisoning"),)))
    assert card.grade is Grade.D
    assert card.capped_by is Severity.HIGH


def test_a_medium_only_failure_caps_at_c() -> None:
    card = score_run(_run(ran=_ALL_PROBES, findings=(_finding("kv-cache-timing"),)))
    assert card.grade is Grade.C
    assert card.capped_by is Severity.MEDIUM


def test_an_unverified_finding_is_not_a_failure() -> None:
    # Only manifest-CONFIRMED findings fail a class; a candidate must not tank a grade.
    card = score_run(
        _run(
            ran=_ALL_PROBES,
            findings=(_finding("tenant-boundary-fetch", FindingStatus.UNVERIFIED),),
        )
    )
    assert card.grade is Grade.A
    assert card.capped_by is None


def test_grading_a_run_that_exercised_nothing_is_refused() -> None:
    # Grading nothing would emit a letter that means nothing, and F would falsely read
    # as "failed" when the truth is "never tested".
    with pytest.raises(ConfigError, match="nothing to grade"):
        score_run(_run(ran=()))


def test_class_2_headline_carries_its_wilson_interval_and_sample_size() -> None:
    card = score_run(
        _run(
            ran=_ALL_PROBES,
            metrics=RunMetrics(
                retrieval_pivot_rate=0.812,
                retrieval_pivot_rate_ci=(0.681, 0.898),
                retrieval_pivot_n=48,
                retrieval_pivot_k=39,
            ),
        )
    )
    bleed = next(c for c in card.classes if c.class_id == 2)
    assert bleed.headline is not None
    # the rate is never shown as a bare point estimate
    assert "81.2% RPR" in bleed.headline
    assert "95% CI" in bleed.headline and "n=48" in bleed.headline


def test_every_catalog_class_appears_and_weights_are_declared() -> None:
    card = score_run(_run(ran=_ALL_PROBES))
    assert [c.class_id for c in card.classes] == [e.class_id for e in CATALOG]
    # Class 11 (erasure, a control check with its own attestation) and Class 12 (the
    # evidence chain) are deliberately not isolation-catalog classes.
    assert 11 not in {c.class_id for c in card.classes}
    assert 12 not in {c.class_id for c in card.classes}
    assert all(SEVERITY_WEIGHTS[e.severity] > 0 for e in CATALOG)
