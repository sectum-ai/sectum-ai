"""Tests for the isolation scorecard (``sectum-ai score``, docs/scorecard.md).

The honesty rules are the point of this feature, so they are asserted directly: an
untested class can never be a PASS; coverage drives confidence and never the grade; the
worst failing class's weight band caps the letter; and every confirmed finding lands in a
class or the run is refused.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from sectum_ai.score import (
    CATALOG,
    METHODOLOGY_VERSION,
    SEVERITY_WEIGHTS,
    _confidence_for,
    _grade_for,
    score_run,
)
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
    # Every finding is CRITICAL-severity regardless of its class's band, and that mismatch
    # is load-bearing: rule 3 caps on the CLASS's band, so a MEDIUM-band class carrying a
    # CRITICAL finding is what proves the cap ignores finding.severity. "Tidying" this to
    # match each class's band would leave test_a_medium_only_failure_caps_at_c passing
    # against the very bug it exists to catch.
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
    # The scorecard is what binds a letter to a record; a blank run_id binds it to nothing.
    assert card.run_id == "run-test"


def test_the_digest_binds_every_field_of_the_record() -> None:
    # The binding is only worth what it covers, and the CLI test that checks it recomputes
    # with run_digest ITSELF - so it cannot notice the digest quietly ceasing to cover a
    # field. A digest over everything-but-metrics passed that assertion while two records
    # whose flagship RPR differed 47x carried an identical digest, and a third party
    # comparing digests would conclude "same record". Compare scorecards, never recompute.
    base = _run(ran=_ALL_PROBES)
    baseline = score_run(base).run_digest
    variants: dict[str, dict[str, Any]] = {
        "run_id": {"run_id": "run-other"},
        "scenario_hash": {"scenario_hash": "z" * 8},
        "manifest_hash": {"manifest_hash": "z" * 8},
        "finished_at": {"finished_at": base.finished_at + timedelta(seconds=1)},
        "adapter_versions": {"adapter_versions": {"fake-vector": "9.9"}},
        "probe_versions": {"probe_versions": {**base.probe_versions, "extra-probe": "1.0"}},
        "findings": {"findings": (_finding("rag-poisoning", FindingStatus.UNVERIFIED),)},
        "metrics": {
            "metrics": RunMetrics(
                retrieval_pivot_rate=0.958, retrieval_pivot_k=46, retrieval_pivot_n=48
            )
        },
    }
    for field, update in variants.items():
        assert score_run(base.model_copy(update=update)).run_digest != baseline, (
            f"run_digest does not bind {field}: two different records share one identifier"
        )


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
    # the raw average alone is 36/41 - a B - so only the band cap produces the F
    assert card.weighted_score == pytest.approx(36 / 41)
    boundary = next(c for c in card.classes if c.class_id == 1)
    assert boundary.verdict is ClassVerdict.FAIL and boundary.confirmed_findings == 1


def test_a_confirmed_high_failure_caps_the_grade_at_d() -> None:
    card = score_run(_run(ran=_ALL_PROBES, findings=(_finding("rag-poisoning"),)))
    assert card.grade is Grade.D
    assert card.capped_by is Severity.HIGH


def test_a_medium_only_failure_caps_at_c() -> None:
    # The finding is CRITICAL-severity but Class 5 is a MEDIUM-band class, so this pins
    # what rule 3 keys on: the class's published band, never the finding's severity.
    # Keying on finding.severity would grade this F.
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


def _bleed_headline(metrics: RunMetrics) -> str:
    card = score_run(_run(ran=_ALL_PROBES, metrics=metrics))
    headline = next(c for c in card.classes if c.class_id == 2).headline
    assert headline is not None
    return headline


def test_class_2_headline_carries_its_wilson_interval_and_sample_size() -> None:
    # The record's asserted rate and interval AGREE with its counts here, so this pins the
    # honest case only. Anything that distinguishes recompute-from-counts from
    # relay-the-claim belongs in the two tests below - this fixture deliberately cannot,
    # and said so falsely until they existed: 39/48 = 0.8125 renders 81.2% either way.
    headline = _bleed_headline(
        RunMetrics(
            retrieval_pivot_rate=0.8125,
            retrieval_pivot_rate_ci=(0.681, 0.898),
            retrieval_pivot_n=48,
            retrieval_pivot_k=39,
        )
    )
    assert "81.2% RPR" in headline
    assert "95% CI 68.1%-89.8%" in headline and "n=48" in headline


def test_class_2_headline_keeps_its_interval_on_a_clean_zero_rate_run() -> None:
    # k=0 of n=48 is the clean-stack success path: the flagship RPR is 0.0%, falsy but not
    # None. A truthiness check for the recomputed rate in place of `is not None` would strip
    # the Wilson CI and n from exactly the result whose sample size matters most, reducing an
    # honest "0.0% over 48 tries (CI <= 7.4%)" to a bare "0.0%". Pin the interval, not just
    # the rate; every other Class-2 headline test uses k > 0.
    assert _bleed_headline(RunMetrics(retrieval_pivot_k=0, retrieval_pivot_n=48)) == (
        "0.0% RPR (95% CI 0.0%-7.4%, n=48)"
    )


def test_class_2_counts_free_headline_renders_a_clean_zero_rate() -> None:
    # The no-counts branch (n=0): a record carrying a rate but no binomial counts - an older
    # pre-counts record `score` re-grades - is shown as it recorded itself. A clean 0.0 rate is
    # falsy but not None, so a truthiness check would drop the flagship RPR headline entirely.
    # This is a distinct branch from the k=0 counts path pinned just above (which recomputes).
    assert _bleed_headline(RunMetrics(retrieval_pivot_rate=0.0)) == "0.0% RPR"


def test_class_2_headline_recomputes_the_rate_from_the_counts_not_the_records_claim() -> None:
    # Rule 4's logic applied to the headline: the counts are evidence, the rate is the
    # record's claim about itself. A record whose counts say 46 of 48 while its rate field
    # says 0.1% must be reported at 95.8% - the alternative prints a rate that its own
    # interval excludes, sourced from the party under scrutiny.
    headline = _bleed_headline(
        RunMetrics(
            retrieval_pivot_rate=0.001,
            retrieval_pivot_rate_ci=(0.0009, 0.0011),
            retrieval_pivot_k=46,
            retrieval_pivot_n=48,
        )
    )
    assert headline.startswith("95.8% RPR")  # the counts win, not the asserted 0.1%


def test_class_2_recomputes_its_interval_rather_than_relaying_the_records() -> None:
    # The attack _headline's docstring names: truthful counts, a fabricated interval. A
    # relayed (0.9579, 0.9581) prints as a ~200x-too-tight `95% CI 95.8%-95.8%` and reads
    # exactly like an interval we computed. Wilson on 46/48 is 86.0%-98.8%; assert the
    # VALUES, since asserting the substring "95% CI" is what let this survive.
    headline = _bleed_headline(
        RunMetrics(
            retrieval_pivot_rate=0.958,
            retrieval_pivot_rate_ci=(0.9579, 0.9581),
            retrieval_pivot_k=46,
            retrieval_pivot_n=48,
        )
    )
    assert "95% CI 86.0%-98.8%" in headline
    assert "95.8%-95.8%" not in headline


def test_a_total_leak_is_graded_not_refused_as_incoherent() -> None:
    # The boundary the incoherence check must NOT cross. k == n is the worst possible
    # stack - every benign cross-tenant query surfaced a foreign marker - and it is a
    # perfectly coherent record. Refusing it (exit 3, "impossible") would let the very
    # worst result escape its F by having the tool blame the record instead of grading it.
    headline = _bleed_headline(
        RunMetrics(retrieval_pivot_k=48, retrieval_pivot_n=48, retrieval_pivot_rate=1.0)
    )
    assert headline.startswith("100.0% RPR")
    assert "95% CI 92.6%-100.0%" in headline


def test_a_count_of_one_of_zero_is_refused_not_believed() -> None:
    # The other side of that boundary, and the case a loosened check walks straight past:
    # 1 of 0 is impossible, and the record pairs it with a clean 0.0% rate it wants
    # believed. Refuse, rather than fall through to the record's own claim.
    with pytest.raises(ConfigError, match="incoherent"):
        score_run(
            _run(
                ran=_ALL_PROBES,
                metrics=RunMetrics(
                    retrieval_pivot_k=1, retrieval_pivot_n=0, retrieval_pivot_rate=0.0
                ),
            )
        )


def test_an_incoherent_count_is_refused_not_quietly_believed() -> None:
    # A record could opt OUT of the counts-recompute by corrupting its own counts: k > n
    # made _rate_from_counts give up, falling back to the rate and interval the record
    # asserts - so a doctored run printed a 94x-too-tight interval as fact, over an n=48
    # that lent it plausibility, and k=99 was never shown. The incoherent record must not
    # get to choose being believed; refuse it the way rule 4 refuses an unattributable
    # finding.
    with pytest.raises(ConfigError, match="incoherent"):
        score_run(
            _run(
                ran=_ALL_PROBES,
                metrics=RunMetrics(
                    retrieval_pivot_rate=0.125,
                    retrieval_pivot_rate_ci=(0.124, 0.126),
                    retrieval_pivot_k=99,
                    retrieval_pivot_n=48,
                ),
            )
        )


def test_class_2_without_a_ci_still_shows_its_rate() -> None:
    # RunMetrics carries the rate and its interval independently, so a third-party or
    # older record can hold a rate that was never given one. The flagship RPR must still
    # reach the scorecard - dropping it would hide the headline number - and it is shown
    # exactly as recorded rather than wearing an interval this grader invented.
    card = score_run(_run(ran=_ALL_PROBES, metrics=RunMetrics(retrieval_pivot_rate=0.954)))
    bleed = next(c for c in card.classes if c.class_id == 2)
    assert bleed.headline == "95.4% RPR"


def test_every_catalog_class_appears_and_weights_are_declared() -> None:
    card = score_run(_run(ran=_ALL_PROBES))
    assert [c.class_id for c in card.classes] == [e.class_id for e in CATALOG]
    # Class 11 (erasure, a control check with its own attestation) and Class 12 (the
    # evidence chain) are deliberately not isolation-catalog classes.
    assert 11 not in {c.class_id for c in card.classes}
    assert 12 not in {c.class_id for c in card.classes}
    # No class carries the zero-weight INFO band - the invariant that keeps score_run's
    # zero-covered-weight refusal an unreachable guard rather than a live path.
    assert all(SEVERITY_WEIGHTS[e.severity] > 0 for e in CATALOG)


_HIGH_PROBES = (
    "rag-poisoning",
    "semantic-cache-contamination",
    "embedding-inversion",
    "lora-cross-tenant",
    "ikea-extraction",
)


def test_the_final_grade_is_the_worse_of_the_weighted_grade_and_the_cap() -> None:
    # The cap is a FLOOR, not the answer. Over a run that covered only high-band
    # classes, failing most of them drags the weighted score under 0.50 -> a base grade
    # of F, which is worse than the high-band cap (D), so F wins.
    card = score_run(_run(ran=_HIGH_PROBES, findings=tuple(_finding(p) for p in _HIGH_PROBES[:4])))
    assert card.capped_by is Severity.HIGH  # the cap alone would have said D...
    assert card.weighted_score < 0.5
    assert card.grade is Grade.F  # ...but the weighted grade is worse, so it governs


def test_under_full_coverage_non_critical_failures_cannot_outweigh_the_cap() -> None:
    # A property of the published weights worth pinning: the five critical classes carry
    # 25 of the catalog's 41, so failing EVERY high- and medium-band class still leaves
    # the weighted score above 0.50. The severity cap - not the average - is what makes
    # those failures bite, which is exactly why rule 3 exists.
    non_critical = (*_HIGH_PROBES, "kv-cache-timing")
    card = score_run(_run(ran=_ALL_PROBES, findings=tuple(_finding(p) for p in non_critical)))
    assert card.weighted_score == pytest.approx(25 / 41)  # the criticals alone hold it up
    assert card.capped_by is Severity.HIGH
    assert card.grade is Grade.D


def test_a_multi_probe_class_is_covered_when_any_of_its_probes_ran() -> None:
    # Class 2 drives two probes; running only the vector-store one still covers the
    # class, and the record names only the probe that actually ran.
    card = score_run(_run(ran=("rag-entity-bleed",)))
    bleed = next(c for c in card.classes if c.class_id == 2)
    assert bleed.verdict is ClassVerdict.PASS
    assert bleed.probe_ids == ("rag-entity-bleed",)  # not the un-run sibling


def test_a_failure_in_one_class_does_not_fail_another() -> None:
    # Findings are attributed by probe id; a Class 1 leak must not tank Class 2.
    card = score_run(_run(ran=_ALL_PROBES, findings=(_finding("tenant-boundary-fetch"),)))
    assert next(c for c in card.classes if c.class_id == 1).verdict is ClassVerdict.FAIL
    others = [c for c in card.classes if c.class_id != 1]
    assert all(c.verdict is ClassVerdict.PASS for c in others)
    assert all(c.confirmed_findings == 0 for c in others)


def test_coverage_drives_the_confidence_band() -> None:
    # All three bands as they are reachable through score_run. The published boundaries
    # themselves (0.85, 0.60) cannot land exactly - coverage is an integer over 41 - so
    # they are pinned at the helper by test_confidence_thresholds_match_the_published_table.
    full = score_run(_run(ran=_ALL_PROBES))
    assert full.coverage == pytest.approx(1.0) and full.confidence is Confidence.HIGH
    # The five critical classes and nothing else: 25/41 = 0.61 -> medium.
    criticals = score_run(
        _run(
            ran=(
                "tenant-boundary-fetch",
                "rag-entity-bleed",
                "agent-tool-hijack",
                "memory-contamination",
                "multimodal-rag-bleed",
            )
        )
    )
    assert criticals.coverage == pytest.approx(25 / 41)
    assert criticals.confidence is Confidence.MEDIUM
    # The two critical RAG classes plus a high one: 5+5+3 = 13/41 = 0.32 -> low.
    thin = score_run(_run(ran=("tenant-boundary-fetch", "rag-entity-bleed", "rag-poisoning")))
    assert thin.coverage < 0.60 and thin.confidence is Confidence.LOW


def test_a_fixed_run_recomputes_to_a_fixed_letter() -> None:
    # docs/scorecard.md promises a third party re-grading the same run lands on the same
    # letter. Asserting score_run(x) == score_run(x) cannot fail for ANY deterministic
    # implementation (it passes against a grader that always returns A), so pin the
    # actual values instead - this is the recomputation contract.
    card = score_run(_run(ran=_ALL_PROBES, findings=(_finding("rag-poisoning"),)))
    assert card.grade is Grade.D
    assert card.capped_by is Severity.HIGH
    assert card.weighted_score == pytest.approx(38 / 41)
    assert card.coverage == pytest.approx(1.0)
    assert card.confidence is Confidence.HIGH


def test_headlines_render_the_other_classes_rates() -> None:
    card = score_run(
        _run(
            ran=_ALL_PROBES,
            metrics=RunMetrics(
                poisoning_bleed_delta=0.5,
                inversion_reconstruction_rate=0.25,
                extraction_efficiency=0.181,
            ),
        )
    )
    by_id = {c.class_id: c for c in card.classes}
    assert by_id[3].headline is not None and "50.0%" in by_id[3].headline
    assert by_id[6].headline is not None and "25.0%" in by_id[6].headline
    assert by_id[10].headline is not None and "18.1%" in by_id[10].headline
    # A class with no headline rate simply has none - never a fabricated 0.
    assert by_id[1].headline is None


def test_the_counts_free_classes_render_a_clean_zero_rate_headline() -> None:
    # 0.0 is a real measured rate on a clean run - falsy but not None. A truthiness check in
    # place of `is not None` on the rate would drop the headline on exactly the passing run,
    # so each counts-free class must still render its 0.0%. The test above uses only non-zero
    # rates; this pins the zero boundary (Class 2's two arms - the k=0 counts path and the
    # counts-free rate path - are pinned by the two _bleed_headline tests above).
    card = score_run(
        _run(
            ran=_ALL_PROBES,
            metrics=RunMetrics(
                poisoning_bleed_delta=0.0,
                inversion_reconstruction_rate=0.0,
                extraction_efficiency=0.0,
            ),
        )
    )
    by_id = {c.class_id: c for c in card.classes}
    assert by_id[3].headline == "0.0% poisoning bleed"
    assert by_id[6].headline == "0.0% reconstruction"
    assert by_id[10].headline == "0.0% extraction efficiency"


def test_a_class_that_did_not_run_carries_no_headline_or_findings() -> None:
    # An untested class must not borrow the run's metrics and look measured.
    card = score_run(
        _run(
            ran=("tenant-boundary-fetch",),
            metrics=RunMetrics(
                retrieval_pivot_rate=0.9, retrieval_pivot_rate_ci=(0.8, 0.95), retrieval_pivot_n=48
            ),
        )
    )
    bleed = next(c for c in card.classes if c.class_id == 2)
    assert bleed.verdict is ClassVerdict.NOT_COVERED
    assert bleed.headline is None
    assert bleed.confirmed_findings == 0


def test_a_confirmed_finding_fails_its_class_even_if_probe_versions_omits_the_probe() -> None:
    # RULE 4 (regression): a confirmed finding is itself proof its probe ran. Trusting
    # probe_versions alone let a run whose bookkeeping disagreed with its own findings
    # grade A while printing PASS for the class that leaked - the grader was throwing
    # away contradicting evidence it already held. Re-grading a record you did not
    # produce is this command's purpose, so the findings are the authority.
    run = _run(
        # every probe recorded EXCEPT the one that leaked; the class stays "covered"
        # through its sibling probe, which is what made the old bug print PASS.
        ran=tuple(p for p in _ALL_PROBES if p != "rag-pipeline-bleed"),
        findings=(_finding("rag-pipeline-bleed"),),
    )
    card = score_run(run)
    bleed = next(c for c in card.classes if c.class_id == 2)
    assert bleed.verdict is ClassVerdict.FAIL
    assert bleed.confirmed_findings == 1
    assert card.grade is Grade.F
    assert card.capped_by is Severity.CRITICAL


def test_a_confirmed_finding_alone_covers_an_otherwise_unrecorded_class() -> None:
    # The same rule at the extreme: probe_versions is empty, but a confirmed finding
    # proves its probe ran - so the class is FAIL (not NOT_COVERED) and is graded.
    card = score_run(_run(ran=(), findings=(_finding("tenant-boundary-fetch"),)))
    boundary = next(c for c in card.classes if c.class_id == 1)
    assert boundary.verdict is ClassVerdict.FAIL
    assert card.grade is Grade.F


def test_a_confirmed_finding_the_catalog_cannot_attribute_is_refused() -> None:
    # RULE 4 (regression): a probe added or renamed without updating CATALOG must fail
    # loudly. Dropping the finding silently graded A on a confirmed critical leak.
    with pytest.raises(ConfigError, match="catalog is stale"):
        score_run(_run(ran=_ALL_PROBES, findings=(_finding("prompt-log-bleed"),)))


def test_an_unattributable_unverified_finding_does_not_block_grading() -> None:
    # Only CONFIRMED findings are load-bearing; an unverified candidate from an unknown
    # probe must not refuse a whole run.
    card = score_run(
        _run(
            ran=_ALL_PROBES,
            findings=(_finding("prompt-log-bleed", FindingStatus.UNVERIFIED),),
        )
    )
    assert card.grade is Grade.A


def test_the_catalog_covers_every_adversarial_probe_in_the_registry() -> None:
    # Pins CATALOG against the LIVE probe registry, so adding/renaming a probe fails
    # here instead of silently making its class permanently NOT_COVERED (or, worse,
    # dropping its findings). The two erasure workflows are deliberately out of scope:
    # they are control checks with their own attestation, not isolation classes.
    from typing import Any, cast

    from sectum_ai import probes

    registry_ids = {
        str(cast(Any, obj).id)
        for name in probes.__all__
        if isinstance(obj := getattr(probes, name), type)
        and getattr(obj, "id", None)
        and hasattr(obj, "owasp_llm")
    }
    catalog_ids = {probe_id for entry in CATALOG for probe_id in entry.probe_ids}
    out_of_scope = {"gdpr-erasure-verification", "gdpr-subject-erasure-verification"}
    assert catalog_ids <= registry_ids, (
        f"catalog names probes that do not exist: {catalog_ids - registry_ids}"
    )
    assert registry_ids - out_of_scope == catalog_ids, (
        "every adversarial probe must be scored: "
        f"missing from CATALOG={registry_ids - out_of_scope - catalog_ids}"
    )


def test_the_published_total_catalog_weight_is_41() -> None:
    # docs/scorecard.md publishes "Total catalog weight: 41" and derives every coverage
    # figure from it; pin it so adding a class fails CI instead of falsifying the page.
    assert sum(SEVERITY_WEIGHTS[entry.severity] for entry in CATALOG) == 41


def test_the_catalog_matches_the_published_methodology() -> None:
    # docs/scorecard.md publishes these exact values, and promises that a scorecard
    # stamped v1.2 always recomputes to the same letter. The other tests compare the
    # output to the implementation's own constants, so both sides move together and a
    # silent change to what a published grade MEANS stays green. This pins the contract:
    # changing the catalog, a weight, or a threshold must break here and force a
    # METHODOLOGY_VERSION bump (and a docs update) rather than sliding through.
    assert METHODOLOGY_VERSION == "1.2"
    assert [(entry.class_id, entry.severity) for entry in CATALOG] == [
        (1, Severity.CRITICAL),
        (2, Severity.CRITICAL),
        (3, Severity.HIGH),
        (4, Severity.HIGH),
        (5, Severity.MEDIUM),
        (6, Severity.HIGH),
        (7, Severity.CRITICAL),
        (8, Severity.CRITICAL),
        (9, Severity.HIGH),
        (10, Severity.HIGH),
        (13, Severity.CRITICAL),
    ]
    assert SEVERITY_WEIGHTS[Severity.CRITICAL] == 5
    assert SEVERITY_WEIGHTS[Severity.HIGH] == 3
    assert SEVERITY_WEIGHTS[Severity.MEDIUM] == 1


@pytest.mark.parametrize(
    ("weighted", "expected"),
    [
        (1.0, Grade.A),
        (0.95, Grade.A),  # the boundary is inclusive
        (0.9499, Grade.B),
        (0.85, Grade.B),
        (0.8499, Grade.C),
        (0.70, Grade.C),
        (0.6999, Grade.D),
        (0.50, Grade.D),
        (0.4999, Grade.F),
        (0.0, Grade.F),
    ],
)
def test_grade_thresholds_match_the_published_table(weighted: float, expected: Grade) -> None:
    # The A/B and B/C rows of the published table are unreachable through score_run (any
    # weighted < 1.0 requires a failure, which caps at C or worse and swallows the base
    # grade), so the table can only be pinned at the helper. Without this, flipping a
    # published `>=` to `>` is invisible.
    assert _grade_for(weighted) is expected


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [
        (1.0, Confidence.HIGH),
        (0.85, Confidence.HIGH),  # inclusive
        (0.8499, Confidence.MEDIUM),
        (0.60, Confidence.MEDIUM),  # inclusive
        (0.5999, Confidence.LOW),
        (0.0, Confidence.LOW),
    ],
)
def test_confidence_thresholds_match_the_published_table(
    coverage: float, expected: Confidence
) -> None:
    # Coverage is covered_weight/41 with an integer numerator, so it can never land
    # exactly on 0.85 (34.85) or 0.60 (24.6): the published boundaries are unreachable
    # via score_run and can only be pinned here.
    assert _confidence_for(coverage) is expected


def test_the_d_f_grade_boundary_is_inclusive_at_exactly_0_50() -> None:
    # The one boundary observable through the public API: four high-band classes, two
    # failing -> 6/12 = exactly 0.50, and the high-band cap (D) is not worse than the
    # base grade, so the threshold itself decides the letter. '>' would grade F.
    card = score_run(
        _run(
            ran=(
                "rag-poisoning",
                "semantic-cache-contamination",
                "embedding-inversion",
                "lora-cross-tenant",
            ),
            findings=(_finding("rag-poisoning"), _finding("semantic-cache-contamination")),
        )
    )
    assert card.weighted_score == pytest.approx(0.50)
    assert card.capped_by is Severity.HIGH
    assert card.grade is Grade.D
