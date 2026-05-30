"""Unit tests for the exact/semantic/judge detection pipeline."""

from uuid import UUID

from sectum.probes import DetectionPipeline, FakeJudge, confirmed_findings, dedupe_findings
from sectum.spec import (
    FindingStatus,
    GroundTruthManifest,
    Marker,
    MarkerType,
    Scenario,
    Severity,
    Substrate,
    Surface,
    SyntheticTenantSpec,
)
from sectum.substrate import build_substrate, default_scenario


def _substrate() -> Substrate:
    return build_substrate(default_scenario(seed=55))


def _foreign_hard_marker(substrate: Substrate) -> Marker:
    """A hard canary owned by the first tenant (foreign to every other tenant)."""
    owner = substrate.tenants[0].tenant_id
    return next(
        marker
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == owner and marker.marker_type is MarkerType.HARD_CANARY
    )


def test_foreign_hard_canary_is_a_confirmed_critical_leak() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    owner = substrate.tenants[0].tenant_id
    observer = substrate.tenants[1].tenant_id
    hard = next(
        marker
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == owner and marker.marker_type is MarkerType.HARD_CANARY
    )
    findings = confirmed_findings(
        pipeline.detect(observer, f"retrieved chunk: {hard.plaintext}", Surface.VECTOR_DB)
    )
    assert len(findings) == 1
    assert findings[0].marker_id == hard.marker_id
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].confidence == 1.0
    assert findings[0].owner_tenant_id == owner
    assert findings[0].observed_in_tenant_id == observer


def test_foreign_entity_canary_is_detected_inside_a_long_observation() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    owner = substrate.tenants[2].tenant_id
    observer = substrate.tenants[3].tenant_id
    entity = next(
        marker
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == owner and marker.marker_type is MarkerType.ENTITY_CANARY
    )
    padded = "routine context line. " * 60 + entity.plaintext + " followed by trailing notes."
    findings = confirmed_findings(pipeline.detect(observer, padded, Surface.RAG_PIPELINE))
    assert [finding.marker_id for finding in findings] == [entity.marker_id]
    assert findings[0].severity is Severity.HIGH


def test_each_tenant_owns_six_markers_two_of_each_type() -> None:
    substrate = _substrate()
    for tenant in substrate.tenants:
        owned = [
            marker
            for marker in substrate.manifest.markers
            if marker.owner_tenant_id == tenant.tenant_id
        ]
        assert len(owned) == 6
        for marker_type in MarkerType:
            assert sum(1 for marker in owned if marker.marker_type is marker_type) == 2


def test_dedupe_collapses_repeated_detections_within_a_probe() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    observer = substrate.tenants[1].tenant_id
    text = f"retrieved chunk: {_foreign_hard_marker(substrate).plaintext}"
    twice = [
        *pipeline.detect(observer, text, Surface.MCP, probe_id="agent-tool-hijack"),
        *pipeline.detect(observer, text, Surface.MCP, probe_id="agent-tool-hijack"),
    ]
    assert len(twice) == 2
    assert len(dedupe_findings(twice)) == 1


def test_dedupe_keeps_the_same_leak_found_by_different_probes() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    observer = substrate.tenants[1].tenant_id
    text = f"retrieved chunk: {_foreign_hard_marker(substrate).plaintext}"
    across = [
        *pipeline.detect(observer, text, Surface.VECTOR_DB, probe_id="tenant-boundary-fetch"),
        *pipeline.detect(observer, text, Surface.MODEL_ADAPTER, probe_id="lora-cross-tenant"),
    ]
    assert len(dedupe_findings(across)) == 2


# --- Cluster-2 hardening regression tests (zero-FP / zero-FN) ----------------

_TA = UUID(int=0xA)
_TB = UUID(int=0xB)


def _entity(plaintext: str, owner: UUID = _TB) -> Marker:
    return Marker(
        marker_id=f"e-{plaintext}",
        marker_type=MarkerType.ENTITY_CANARY,
        owner_tenant_id=owner,
        plaintext=plaintext,
    )


def _hard(plaintext: str, owner: UUID = _TB) -> Marker:
    return Marker(
        marker_id=f"h-{plaintext}",
        marker_type=MarkerType.HARD_CANARY,
        owner_tenant_id=owner,
        plaintext=plaintext,
    )


_ZWSP = "​"  # zero-width space


def _fullwidth(text: str) -> str:
    """ASCII -> the NFKC-foldable full-width forms (built from escapes, not raw glyphs)."""
    out = []
    for char in text:
        if "A" <= char <= "Z":
            out.append(chr(0xFF21 + ord(char) - ord("A")))
        elif "0" <= char <= "9":
            out.append(chr(0xFF10 + ord(char) - ord("0")))
        elif char == "-":
            out.append(chr(0xFF0D))  # fullwidth hyphen-minus
        else:
            out.append(char)
    return "".join(out)


def _pipeline_over(*markers: Marker) -> DetectionPipeline:
    """A pipeline over a minimal substrate carrying exactly ``markers``."""
    scenario = Scenario(
        scenario_id="custom",
        seed=1,
        tenants=(
            SyntheticTenantSpec(tenant_id=_TA, display_name="A", industry="x", corpus_size=1),
        ),
    )
    manifest = GroundTruthManifest(manifest_id="m", scenario_hash="h", markers=markers)
    substrate = Substrate(
        scenario=scenario, tenants=scenario.tenants, documents=(), manifest=manifest
    )
    return DetectionPipeline(substrate)


# A1 - the judge confirms ordered-and-close, not unordered token coverage.
# Tested on the judge directly so the semantic threshold can't make the
# assertion pass for the wrong reason.


def test_judge_does_not_confirm_a_reordered_token_permutation() -> None:
    # Every token of "Project Onyx-00002" is present, but out of order: the
    # entity is not actually here, so a set-coverage judge would fabricate a leak.
    marker = _entity("Project Onyx-00002")
    assert not FakeJudge().judge("the project board, item 00002, by Onyx", marker).leak


def test_judge_confirms_a_contiguous_phrase() -> None:
    marker = _entity("Project Onyx-00002")
    assert FakeJudge().judge("we saw Project Onyx-00002 here", marker).leak


def test_judge_confirms_a_lightly_paraphrased_phrase() -> None:
    # A real leak that paraphrases ("Project (internal) Onyx-00002") keeps the
    # tokens in order but interposes a word; it must still confirm (zero-FN).
    marker = _entity("Project Onyx-00002")
    assert FakeJudge().judge("Project (internal) Onyx-00002", marker).leak


def test_judge_does_not_confirm_a_benign_token_coincidence() -> None:
    # The entity reuses common words ("project", a 5-digit serial); a benign
    # sentence that mentions them in order but spread apart is not the entity
    # surfacing. The deterministic judge errs toward precision (zero-FP); heavier
    # genuine paraphrase is the production LLM judge's job.
    marker = _entity("Project Onyx-00002")
    assert not FakeJudge().judge("our project ships onyx units; lot 00002 next", marker).leak
    assert not FakeJudge().judge("invoice project line onyx tier 00002 seats", marker).leak


def test_judge_interposed_budget_is_exactly_one_token() -> None:
    # Pin the calibration constant so a future change is a conscious one: one
    # interposed token confirms, two does not.
    marker = _entity("alpha bravo")
    assert FakeJudge().judge("alpha x bravo", marker).leak
    assert not FakeJudge().judge("alpha x y bravo", marker).leak


def test_judge_handles_a_single_token_entity() -> None:
    # A one-token ENTITY_CANARY must not crash the ordered-span matcher and must
    # confirm only when the token is actually present.
    marker = _entity("Onyx")
    assert FakeJudge().judge("the leaked Onyx file appeared", marker).leak
    assert not FakeJudge().judge("nothing relevant in this line", marker).leak


def test_judge_does_not_confirm_when_tokens_are_scattered_too_far() -> None:
    # Tokens in order but spread across an unrelated span are a coincidence,
    # not the entity surfacing.
    marker = _entity("Project Onyx-00002")
    scattered = "project " + "filler " * 8 + "onyx " + "more " * 4 + "00002"
    assert not FakeJudge().judge(scattered, marker).leak


def test_pipeline_keeps_a_high_similarity_reordered_entity_unverified() -> None:
    # End-to-end zero-FP guard: a reordered window has the same token multiset as
    # the marker, so it scores cosine 1.0 and clears the semantic threshold - the
    # judge MUST be what blocks it, leaving the candidate UNVERIFIED rather than
    # CONFIRMED. A regression that confirmed on similarity alone (or reverted the
    # judge to set-overlap) would turn this into a confirmed false positive.
    pipeline = _pipeline_over(_entity("Project Onyx-00002"))
    findings = pipeline.detect(_TA, "board note: 00002 Onyx Project", Surface.RAG_PIPELINE)
    assert confirmed_findings(findings) == []
    assert [f.status for f in findings] == [FindingStatus.UNVERIFIED]


def test_judge_confirms_despite_casing_and_punctuation() -> None:
    marker = _entity("Project Onyx-00002")
    assert FakeJudge().judge("...PROJECT   Onyx,  00002!!...", marker).leak


# A3 - the exact scan is case / NFKC / zero-width insensitive, but does not
# over-normalize into a false positive.


def test_exact_scan_detects_a_recased_canary() -> None:
    pipeline = _pipeline_over(_hard("SECTUM-CANARY-AB23CD"))
    found = confirmed_findings(pipeline.detect(_TA, "saw sectum-canary-ab23cd", Surface.TRACING))
    assert len(found) == 1


def test_exact_scan_detects_a_fullwidth_canary() -> None:
    # A surface that stored the canary in full-width (NFKC-foldable) form must
    # still be caught - exercises the NFKC branch specifically.
    fullwidth = _fullwidth("SECTUM-CANARY-AB23CD")
    pipeline = _pipeline_over(_hard("SECTUM-CANARY-AB23CD"))
    found = confirmed_findings(pipeline.detect(_TA, f"leak {fullwidth} here", Surface.TRACING))
    assert len(found) == 1


def test_exact_scan_detects_a_zero_width_split_canary() -> None:
    pipeline = _pipeline_over(_hard("SECTUM-CANARY-AB23CD"))
    split = f"SECTUM-CANARY-{_ZWSP}AB23CD"
    found = confirmed_findings(pipeline.detect(_TA, f"value {split} here", Surface.TRACING))
    assert len(found) == 1


def test_exact_scan_does_not_match_a_similar_but_different_canary() -> None:
    # Normalization must not collapse two distinct canaries into a false match.
    pipeline = _pipeline_over(_hard("SECTUM-CANARY-AB23CD"))
    assert pipeline.detect(_TA, "token SECTUM-CANARY-AB23CE here", Surface.TRACING) == []


def test_exact_scan_has_no_false_positive_on_benign_text() -> None:
    pipeline = _pipeline_over(_hard("SECTUM-CANARY-AB23CD"))
    assert pipeline.detect(_TA, "nothing sensitive in this line", Surface.TRACING) == []


def test_zero_width_only_canary_does_not_match_everything() -> None:
    # A plaintext that survives min_length=1 but normalizes to empty must not
    # substring-match every observation (the empty-needle guard).
    pipeline = _pipeline_over(_hard(_ZWSP + _ZWSP))
    assert pipeline.detect(_TA, "completely unrelated benign text", Surface.TRACING) == []


# A4 - finding_id carries the surface, so one marker on two surfaces is two
# leaks; same marker + same surface + same probe still collapses.


def test_same_marker_on_two_surfaces_one_probe_are_distinct() -> None:
    pipeline = _pipeline_over(_hard("SECTUM-CANARY-AB23CD"))
    text = "retrieved SECTUM-CANARY-AB23CD"
    vector = pipeline.detect(_TA, text, Surface.VECTOR_DB, probe_id="p")[0]
    model = pipeline.detect(_TA, text, Surface.MODEL_ADAPTER, probe_id="p")[0]
    assert vector.finding_id != model.finding_id
    assert len(dedupe_findings([vector, model])) == 2


def test_same_marker_same_surface_same_probe_collapses() -> None:
    pipeline = _pipeline_over(_hard("SECTUM-CANARY-AB23CD"))
    text = "retrieved SECTUM-CANARY-AB23CD"
    twice = [
        pipeline.detect(_TA, text, Surface.VECTOR_DB, probe_id="p")[0],
        pipeline.detect(_TA, text, Surface.VECTOR_DB, probe_id="p")[0],
    ]
    assert len(dedupe_findings(twice)) == 1
