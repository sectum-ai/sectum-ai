"""Unit tests for the exact/semantic/judge detection pipeline."""

from uuid import UUID

import pytest

from sectum_ai.probes import (
    DetectionPipeline,
    FakeEmbeddingProvider,
    FakeJudge,
    confirmed_findings,
    dedupe_findings,
)
from sectum_ai.probes.detection import (
    JudgeVerdict,
    _canonical_embedding_model,
    _token_windows,
    _tokenize,
    is_cross_principal,
)
from sectum_ai.spec import (
    FindingStatus,
    GroundTruthManifest,
    Marker,
    MarkerType,
    Principal,
    Scenario,
    Severity,
    Substrate,
    Surface,
    SyntheticTenantSpec,
)
from sectum_ai.substrate import build_substrate, default_scenario


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


def test_dedupe_keeps_confirmed_over_an_earlier_unverified_of_the_same_id() -> None:
    # A semantic-only candidate (UNVERIFIED) and a judge-confirmed leak (CONFIRMED)
    # of the same marker on the same surface share a finding_id - the id does not
    # encode status. dedupe must keep the CONFIRMED even when the UNVERIFIED was
    # appended first, or the headline confirmed-leak count silently drops a real
    # leak in favor of the weaker duplicate.
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    observer = substrate.tenants[1].tenant_id
    text = f"retrieved chunk: {_foreign_hard_marker(substrate).plaintext}"
    [confirmed] = pipeline.detect(observer, text, Surface.VECTOR_DB, probe_id="rag-entity-bleed")
    assert confirmed.status is FindingStatus.CONFIRMED
    unverified = confirmed.model_copy(
        update={
            "status": FindingStatus.UNVERIFIED,
            "severity": Severity.INFO,
            "confidence": 0.4,
        }
    )
    assert unverified.finding_id == confirmed.finding_id  # same id, weaker status

    # UNVERIFIED appears first; the status-blind first-wins dedupe would drop the
    # CONFIRMED. The status-aware dedupe keeps it regardless of order.
    deduped = dedupe_findings([unverified, confirmed])
    assert len(deduped) == 1
    assert deduped[0].status is FindingStatus.CONFIRMED
    assert confirmed_findings(deduped) == [confirmed]
    # Symmetric: order must not matter.
    assert dedupe_findings([confirmed, unverified])[0].status is FindingStatus.CONFIRMED


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


def test_cosine_is_a_true_cosine_bounded_by_one() -> None:
    from sectum_ai.probes.detection import _cosine

    # Identical direction is 1.0 regardless of magnitude. A bare dot product would
    # return 25.0 here and overflow Finding.confidence's 0..1 bound.
    assert _cosine((3.0, 4.0), (3.0, 4.0)) == 1.0
    assert _cosine((1.0, 0.0), (0.0, 1.0)) == 0.0  # orthogonal
    assert abs(_cosine((1.0, 0.0), (-1.0, 0.0)) + 1.0) < 1e-9  # opposite direction
    assert _cosine((0.0, 0.0), (1.0, 1.0)) == 0.0  # a zero vector has no direction


def test_semantic_confidence_stays_bounded_with_a_non_unit_embedder() -> None:
    # A real embedder need not return unit vectors. With a true cosine the
    # semantic score stays <= 1.0, so Finding.confidence never overflows its 0..1
    # bound and detection does not crash mid-scan (a bare dot product would).
    class _NonUnitEmbedder:
        def embed(self, text: str) -> tuple[float, ...]:
            magnitude = sum(ord(char) for char in text) or 1
            return (float(magnitude), float(magnitude % 7 + 1), float(magnitude % 5 + 1))

    substrate = _substrate()
    entity = next(
        marker
        for marker in substrate.manifest.markers
        if marker.marker_type is MarkerType.ENTITY_CANARY
        and marker.owner_tenant_id == substrate.tenants[0].tenant_id
    )
    observer = substrate.tenants[1].tenant_id
    pipeline = DetectionPipeline(substrate, embedder=_NonUnitEmbedder(), semantic_threshold=0.0)
    findings = pipeline.detect(observer, f"context {entity.plaintext} trailer", Surface.VECTOR_DB)
    assert findings  # threshold 0.0 lets the candidate through to the judge
    assert all(0.0 <= finding.confidence <= 1.0 for finding in findings)


# --- SECRET_CANARY format detector (the spec, section 6.3: "exact + format") --
#
# Every secret value used below is generated at runtime from the seeded
# substrate (or built by string concatenation), never written as a literal, so
# nothing here trips secret scanning.


def _foreign_secrets(substrate: Substrate, observer: UUID) -> list[Marker]:
    return [
        marker
        for marker in substrate.manifest.markers
        if marker.marker_type is MarkerType.SECRET_CANARY and marker.owner_tenant_id != observer
    ]


def _secret_shape(plaintext: str) -> str:
    if plaintext.startswith("sk-"):
        return "sk-"
    if plaintext.startswith("AKIA"):
        return "AKIA"
    return "SSN"


def test_secret_format_detects_all_three_credential_shapes() -> None:
    # The default scenario plants sk-, AKIA, and SSN-shaped secrets; every one
    # that surfaces in a foreign session is a confirmed critical leak (zero-FN).
    substrate = _substrate()
    observer = substrate.tenants[0].tenant_id
    foreign = _foreign_secrets(substrate, observer)
    assert {_secret_shape(s.plaintext) for s in foreign} == {"sk-", "AKIA", "SSN"}
    pipeline = DetectionPipeline(substrate)
    for secret in foreign:
        found = confirmed_findings(
            pipeline.detect(observer, f"dumped credentials: {secret.plaintext}", Surface.API)
        )
        assert [f.marker_id for f in found] == [secret.marker_id]
        assert found[0].severity is Severity.CRITICAL
        assert found[0].confidence == 1.0


def test_secret_format_recovers_a_secret_wrapped_in_surrounding_bytes() -> None:
    # A credential embedded in a JSON blob (no surrounding whitespace) is still
    # recovered by the format pass - the value-add over a plain exact scan.
    substrate = _substrate()
    observer = substrate.tenants[0].tenant_id
    secret = _foreign_secrets(substrate, observer)[0]
    blob = f'{{"provider":"x","api_key":"{secret.plaintext}","rotated":false}}'
    detected = DetectionPipeline(substrate).detect(observer, blob, Surface.PROMPT_LOGS)
    assert any(f.marker_id == secret.marker_id for f in confirmed_findings(detected))


def test_secret_shaped_string_absent_from_the_manifest_is_not_confirmed() -> None:
    # A credential-shaped string that matches no manifest marker yields no
    # confirmed finding - the zero-false-positive invariant for the format path.
    substrate = _substrate()
    observer = substrate.tenants[0].tenant_id
    decoy = "sk-" + "a" * 44  # shaped like an OpenAI key, but not a planted marker
    found = confirmed_findings(DetectionPipeline(substrate).detect(observer, decoy, Surface.API))
    assert found == []


def test_own_tenant_secret_is_not_a_leak() -> None:
    # A secret observed in its owner's own session is expected, not a leak.
    substrate = _substrate()
    secret = next(
        marker
        for marker in substrate.manifest.markers
        if marker.marker_type is MarkerType.SECRET_CANARY
    )
    found = confirmed_findings(
        DetectionPipeline(substrate).detect(
            secret.owner_tenant_id, f"config: {secret.plaintext}", Surface.API
        )
    )
    assert found == []


def test_secret_evidence_span_is_redacted() -> None:
    # A confirmed secret leak must not carry the verbatim credential into the
    # finding's evidence span (the spec, section 16) - an evidence pack leaves the
    # box in BYOC mode. The marker id ties the finding back to the manifest.
    substrate = _substrate()
    observer = substrate.tenants[0].tenant_id
    secret = _foreign_secrets(substrate, observer)[0]
    found = confirmed_findings(
        DetectionPipeline(substrate).detect(observer, f"leaked: {secret.plaintext}", Surface.API)
    )
    finding = next(f for f in found if f.marker_id == secret.marker_id)
    assert secret.plaintext not in finding.evidence_span
    assert "[redacted]" in finding.evidence_span


class _LyingJudge:
    """A judge that affirms a leak with a span that is NOT in the observation.

    Models the real-LLM failure mode the FP-control backstop exists for: the
    judge is primed with the marker plaintext and parrots it (or hallucinates a
    quote) for an observation that contains no such text.
    """

    def __init__(self, span: str) -> None:
        self._span = span

    def judge(self, observed_text: str, marker: Marker) -> JudgeVerdict:
        return JudgeVerdict(leak=True, rationale="parroted", evidence_span=self._span)


def test_a_judge_yes_with_an_untraceable_span_is_downgraded_to_unverified() -> None:
    # The spec 6.4 FP-control: a semantic/judge leak that cannot be tied back to
    # the observation is downgraded, never CONFIRMED into the signed pack.
    substrate = build_substrate(default_scenario(seed=11))
    marker = next(
        m for m in substrate.manifest.markers if m.marker_type is MarkerType.ENTITY_CANARY
    )
    observer = next(t for t in substrate.tenants if t.tenant_id != marker.owner_tenant_id)
    pipeline = DetectionPipeline(
        substrate,
        FakeEmbeddingProvider(),
        _LyingJudge(span=marker.plaintext),  # parrots the primed plaintext
        0.0,  # let every candidate reach the judge
    )
    text = "a perfectly benign quarterly report about onboarding timelines"
    findings = pipeline.detect(observer.tenant_id, text, Surface.VECTOR_DB, probe_id="p")
    semantic = [f for f in findings if f.marker_id == marker.marker_id]
    assert semantic, "the candidate must be retained as evidence"
    assert all(f.status is FindingStatus.UNVERIFIED for f in semantic)
    assert all("not traceable" in (f.evidence_span or "") for f in semantic)


def test_a_judge_yes_with_a_traceable_span_stays_confirmed() -> None:
    # The backstop must not weaken genuine confirmations: a span actually present
    # in the observation (here the entity itself) keeps CONFIRMED status.
    substrate = build_substrate(default_scenario(seed=11))
    marker = next(
        m for m in substrate.manifest.markers if m.marker_type is MarkerType.ENTITY_CANARY
    )
    observer = next(t for t in substrate.tenants if t.tenant_id != marker.owner_tenant_id)
    pipeline = DetectionPipeline(
        substrate, FakeEmbeddingProvider(), _LyingJudge(span=marker.plaintext), 0.0
    )
    text = f"retrieved context mentions {marker.plaintext} in the account notes"
    findings = pipeline.detect(observer.tenant_id, text, Surface.VECTOR_DB, probe_id="p")
    confirmed = [
        f
        for f in findings
        if f.marker_id == marker.marker_id and f.status is FindingStatus.CONFIRMED
    ]
    assert confirmed, "a traceable affirmation must confirm"


def _entity_substrate(*plaintexts: str) -> Substrate:
    """A minimal substrate carrying foreign ENTITY_CANARY markers (owner _TB)."""
    markers = tuple(_entity(plaintext) for plaintext in plaintexts)
    scenario = Scenario(
        scenario_id="custom",
        seed=1,
        tenants=(
            SyntheticTenantSpec(tenant_id=_TA, display_name="A", industry="x", corpus_size=1),
        ),
    )
    manifest = GroundTruthManifest(manifest_id="m", scenario_hash="h", markers=markers)
    return Substrate(scenario=scenario, tenants=scenario.tenants, documents=(), manifest=manifest)


def test_a_judge_yes_with_an_in_text_but_marker_unrelated_span_is_not_confirmed() -> None:
    # Zero-FP backstop (spec 6.4): a judge may affirm a leak and cite a span that
    # IS present in the observation but is UNRELATED to the marker (a real-but-
    # irrelevant quote, or a primed/hallucinating verdict). With the marker itself
    # absent, that must NOT confirm - the cited evidence has to tie back to THIS
    # marker, not to any phrase the judge happened to quote.
    substrate = _entity_substrate("Project Pinnacle 00002")
    pipeline = DetectionPipeline(
        substrate, FakeEmbeddingProvider(), _LyingJudge(span="quarterly onboarding report"), 0.0
    )
    text = "a perfectly benign quarterly onboarding report about timelines"
    findings = pipeline.detect(_TA, text, Surface.VECTOR_DB, probe_id="p")
    semantic = [f for f in findings if f.marker_id == "e-Project Pinnacle 00002"]
    assert semantic, "the candidate must be retained as UNVERIFIED evidence"
    assert all(f.status is FindingStatus.UNVERIFIED for f in semantic)


def test_a_judge_yes_with_a_paraphrase_span_sharing_a_marker_token_confirms() -> None:
    # The backstop must not over-reject: a paraphrase whose cited span is in the
    # observation AND shares a distinctive token with the marker ("Pinnacle")
    # confirms, even though the full marker plaintext is not verbatim present.
    substrate = _entity_substrate("Project Pinnacle 00002")
    pipeline = DetectionPipeline(
        substrate, FakeEmbeddingProvider(), _LyingJudge(span="the Pinnacle initiative"), 0.0
    )
    text = "the Pinnacle initiative was referenced in the retrieved notes"
    findings = pipeline.detect(_TA, text, Surface.VECTOR_DB, probe_id="p")
    confirmed = [
        f
        for f in findings
        if f.marker_id == "e-Project Pinnacle 00002" and f.status is FindingStatus.CONFIRMED
    ]
    assert confirmed, "a paraphrase span tied to the marker by a shared token must confirm"


def test_a_judge_yes_sharing_only_template_boilerplate_is_not_confirmed() -> None:
    # Zero-FP: every entity canary is "Project <codename>-<serial>", so "project"
    # is shared template boilerplate (in >=2 markers) - NOT distinctive evidence.
    # A judge that cites a "project ..." span absent the distinctive codename/serial
    # must stay UNVERIFIED, even though the span is present in the observation.
    substrate = _entity_substrate("Project Zephyr 00002", "Project Lodestar 00003")
    pipeline = DetectionPipeline(
        substrate, FakeEmbeddingProvider(), _LyingJudge(span="the project is on schedule"), 0.0
    )
    text = "a benign note: the project is on schedule and the budget was approved"
    findings = pipeline.detect(_TA, text, Surface.VECTOR_DB, probe_id="p")
    entity = [
        f for f in findings if f.marker_id is not None and f.marker_id.startswith("e-Project")
    ]
    assert entity, "candidates must be retained as UNVERIFIED evidence"
    assert all(f.status is FindingStatus.UNVERIFIED for f in entity)


def test_a_judge_yes_sharing_a_distinctive_token_still_confirms_in_a_multi_marker_manifest() -> (
    None
):
    # The boilerplate filter must not over-reject: a span sharing the distinctive
    # codename ("Zephyr"), present in the observation, still CONFIRMS its marker
    # even though "project" is boilerplate across the manifest.
    substrate = _entity_substrate("Project Zephyr 00002", "Project Lodestar 00003")
    pipeline = DetectionPipeline(
        substrate, FakeEmbeddingProvider(), _LyingJudge(span="the Zephyr rollout"), 0.0
    )
    text = "the Zephyr rollout came up in the retrieved account notes"
    findings = pipeline.detect(_TA, text, Surface.VECTOR_DB, probe_id="p")
    confirmed = [
        f
        for f in findings
        if f.marker_id == "e-Project Zephyr 00002" and f.status is FindingStatus.CONFIRMED
    ]
    assert confirmed, "a span sharing the distinctive codename must still confirm"


def test_a_judge_yes_sharing_only_the_serial_number_is_not_confirmed() -> None:
    # Zero-FP: the 5-digit serial is low-entropy and collides with everyday numbers.
    # A benign observation carrying that number + a judge "yes" must NOT confirm -
    # a bare serial can never tie a span to a marker on its own.
    substrate = _entity_substrate("Project Zephyr 00002", "Project Lodestar 00003")
    pipeline = DetectionPipeline(
        substrate, FakeEmbeddingProvider(), _LyingJudge(span="project status 00002"), 0.0
    )
    text = "filing the quarterly project status 00002 for the finance team review"
    findings = pipeline.detect(_TA, text, Surface.VECTOR_DB, probe_id="p")
    entity = [
        f for f in findings if f.marker_id is not None and f.marker_id.startswith("e-Project")
    ]
    assert entity, "candidates must be retained as UNVERIFIED evidence"
    assert all(f.status is FindingStatus.UNVERIFIED for f in entity)


def test_a_collided_codename_stays_distinctive_and_a_genuine_leak_confirms() -> None:
    # Zero-FN guard: a codename two markers happen to share is a MINORITY token, not
    # template boilerplate (which recurs across a majority). A genuine leak of that
    # codename - serial paraphrased away - must still CONFIRM.
    substrate = _entity_substrate(
        "Project Halcyon 00001",
        "Project Halcyon 00002",
        "Project Zephyr 00003",
        "Project Lodestar 00004",
        "Project Onyx 00005",
    )
    pipeline = DetectionPipeline(
        substrate, FakeEmbeddingProvider(), _LyingJudge(span="Project Halcyon"), 0.0
    )
    text = "the retrieved competitor record names Project Halcyon as the account owner"
    findings = pipeline.detect(_TA, text, Surface.VECTOR_DB, probe_id="p")
    confirmed = [
        f
        for f in findings
        if f.marker_id in {"e-Project Halcyon 00001", "e-Project Halcyon 00002"}
        and f.status is FindingStatus.CONFIRMED
    ]
    assert confirmed, "a genuine leak of a collided codename must still confirm"


class _CountingEmbedder:
    """Wraps the fake embedder and counts embed() calls (to prove the window cache)."""

    def __init__(self) -> None:
        self._inner = FakeEmbeddingProvider()
        self.calls = 0

    def embed(self, text: str) -> tuple[float, ...]:
        self.calls += 1
        return self._inner.embed(text)


def test_window_embeddings_are_cached_across_markers_in_one_observation() -> None:
    # With several foreign entity markers, every distinct candidate window must be
    # embedded exactly once per observation - the per-observation cache dedupes
    # windows shared across markers (without it the count would be summed per
    # marker, re-embedding the same window text repeatedly).
    substrate = build_substrate(default_scenario(seed=7))
    counting = _CountingEmbedder()
    pipeline = DetectionPipeline(substrate, counting, FakeJudge(), 0.0)
    observer = Principal(tenant_id=substrate.tenants[1].tenant_id)

    text = "a quarterly report mentioning several projects and onboarding timelines"
    observation_tokens = _tokenize(text)
    foreign_entities = [
        marker
        for marker in substrate.manifest.markers
        if marker.marker_type is MarkerType.ENTITY_CANARY and is_cross_principal(marker, observer)
    ]
    assert len(foreign_entities) >= 2, "need >=2 foreign markers to exercise cross-marker caching"
    # The exact set of distinct window texts the semantic stage embeds, derived
    # with the pipeline's own window sizing (one window per marker plaintext len).
    distinct_windows = {
        " ".join(window)
        for marker in foreign_entities
        for window in _token_windows(observation_tokens, len(_tokenize(marker.plaintext)))
    }

    counting.calls = 0  # ignore the construction-time marker-vector embeddings
    pipeline.detect(observer.tenant_id, text, Surface.VECTOR_DB, probe_id="p")

    assert counting.calls == len(distinct_windows)


class _NamedEmbedder:
    """A fake embedder that reports a model_id, to exercise the manifest-model check."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._inner = FakeEmbeddingProvider()

    def embed(self, text: str) -> tuple[float, ...]:
        return self._inner.embed(text)


class _SpyLog:
    """Records the structlog event names a pipeline emits (config-independent)."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def warning(self, event: str, **_kw: object) -> None:
        self.events.append(event)

    def __getattr__(self, _name: str) -> object:
        return lambda *_a, **_k: None


def test_pipeline_warns_when_embedder_differs_from_the_manifest_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The default offline manifest declares "fake-deterministic" in its entity
    # embedding_refs; an embedder naming a different model must warn that the
    # semantic space (and any calibrated threshold) no longer matches.
    spy = _SpyLog()
    monkeypatch.setattr("sectum_ai.probes.detection._log", spy)
    substrate = build_substrate(default_scenario(seed=7))
    DetectionPipeline(substrate, _NamedEmbedder("text-embedding-3-small"), FakeJudge(), 0.0)
    assert "detect.embedding_ref.model_mismatch" in spy.events


def test_pipeline_is_silent_when_embedder_matches_the_manifest_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The default FakeEmbeddingProvider reports model_id "fake-deterministic", which
    # matches the offline manifest, so construction must not warn.
    spy = _SpyLog()
    monkeypatch.setattr("sectum_ai.probes.detection._log", spy)
    substrate = build_substrate(default_scenario(seed=7))
    DetectionPipeline(substrate, FakeEmbeddingProvider(), FakeJudge(), 0.0)
    assert "detect.embedding_ref.model_mismatch" not in spy.events


def test_pipeline_is_silent_on_a_canonical_openai_manifest_and_matching_embedder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression for the inverted check: a real run stamps the canonical
    # "openai:<model>" form into embedding_ref (from embedding_models[0]), so an
    # OpenAI embedder reporting that same canonical model_id must NOT warn - the
    # bare model name previously false-alarmed on this correctly-matched case.
    marker = Marker(
        marker_id="e-canonical",
        marker_type=MarkerType.ENTITY_CANARY,
        owner_tenant_id=_TB,
        plaintext="Project Wintergreen",
        embedding_ref="openai:text-embedding-3-small/0123456789abcdef",
    )
    scenario = Scenario(
        scenario_id="custom",
        seed=1,
        tenants=(
            SyntheticTenantSpec(tenant_id=_TA, display_name="A", industry="x", corpus_size=1),
        ),
    )
    manifest = GroundTruthManifest(manifest_id="m", scenario_hash="h", markers=(marker,))
    substrate = Substrate(
        scenario=scenario, tenants=scenario.tenants, documents=(), manifest=manifest
    )

    matched = _SpyLog()
    monkeypatch.setattr("sectum_ai.probes.detection._log", matched)
    DetectionPipeline(substrate, _NamedEmbedder("openai:text-embedding-3-small"), FakeJudge(), 0.0)
    assert "detect.embedding_ref.model_mismatch" not in matched.events

    # A genuinely different canonical model still warns.
    differ = _SpyLog()
    monkeypatch.setattr("sectum_ai.probes.detection._log", differ)
    DetectionPipeline(substrate, _NamedEmbedder("openai:text-embedding-3-large"), FakeJudge(), 0.0)
    assert "detect.embedding_ref.model_mismatch" in differ.events


def test_pipeline_is_silent_on_a_fake_sweep_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    # The documented offline sweep seeds embedding_models=("fake-mini",...); every
    # fake-* name is the SAME name-agnostic FakeEmbeddingProvider space, so the
    # default fake detector (model_id "fake-deterministic") must NOT warn.
    marker = Marker(
        marker_id="e-fakesweep",
        marker_type=MarkerType.ENTITY_CANARY,
        owner_tenant_id=_TB,
        plaintext="Project Wintergreen",
        embedding_ref="fake-mini/0123456789abcdef",
    )
    scenario = Scenario(
        scenario_id="custom",
        seed=1,
        tenants=(
            SyntheticTenantSpec(tenant_id=_TA, display_name="A", industry="x", corpus_size=1),
        ),
    )
    manifest = GroundTruthManifest(manifest_id="m", scenario_hash="h", markers=(marker,))
    substrate = Substrate(
        scenario=scenario, tenants=scenario.tenants, documents=(), manifest=manifest
    )
    spy = _SpyLog()
    monkeypatch.setattr("sectum_ai.probes.detection._log", spy)
    DetectionPipeline(substrate, FakeEmbeddingProvider(), FakeJudge(), 0.0)
    assert "detect.embedding_ref.model_mismatch" not in spy.events


def test_canonical_embedding_model_buckets_only_the_fakes() -> None:
    assert _canonical_embedding_model("fake-mini") == "fake"
    assert _canonical_embedding_model("fake-deterministic") == "fake"
    assert _canonical_embedding_model("openai:text-embedding-3-small") == (
        "openai:text-embedding-3-small"
    )
    assert _canonical_embedding_model("st:all-MiniLM-L6-v2") == "st:all-MiniLM-L6-v2"


def test_span_traceable_falls_back_to_the_marker_for_a_tokenless_span() -> None:
    # A real judge may affirm a leak but cite a whitespace/punctuation-only span;
    # that has no usable tokens and must fall back to the marker, so a genuine leak
    # present in the text is not lost to UNVERIFIED.
    marker = _entity("Project Wintergreen")
    text = "the retrieved chunk mentions Project Wintergreen in passing"
    assert DetectionPipeline._span_traceable(text, "   ", marker) is True
    assert DetectionPipeline._span_traceable(text, "...", marker) is True
    assert DetectionPipeline._span_traceable(text, "", marker) is True
    # But a marker genuinely absent from the text still does not trace.
    assert DetectionPipeline._span_traceable("unrelated text", "   ", marker) is False
