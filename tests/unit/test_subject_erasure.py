"""Tests for A3 Phase 0 - the by-id data-subject erasure probe."""

from uuid import UUID

from sectum_ai.adapters import FakeCache, FakeModel, FakeObservability, FakeVectorStore
from sectum_ai.probes import SubjectErasureProbe, SubjectManifest
from sectum_ai.spec import CoverageVerdict, Surface
from sectum_ai.substrate import build_substrate, default_scenario


def _populated_store() -> tuple[FakeVectorStore, UUID, str]:
    substrate = build_substrate(default_scenario(seed=2026))
    tenant = substrate.tenants[0].tenant_id
    docs = [doc for doc in substrate.documents if doc.tenant_id == tenant]
    store = FakeVectorStore()
    store.upsert(tenant, docs)
    return store, tenant, docs[0].doc_id


def test_subject_erasure_is_erased_when_every_supplied_id_is_gone() -> None:
    store, tenant, _present = _populated_store()
    # Only ids that were never in the store (the deletion already removed them).
    manifest = SubjectManifest(
        subject_ref="user-1", records={Surface.VECTOR_DB: ("deleted-1", "deleted-2")}
    )
    report = SubjectErasureProbe(vector=store).verify(tenant, manifest)
    surfaces = {s.surface: s for s in report.surfaces}
    assert surfaces[Surface.VECTOR_DB].markers_before == 2
    assert surfaces[Surface.VECTOR_DB].residual_after == 0
    assert report.coverage()[Surface.VECTOR_DB] is CoverageVerdict.ERASED
    assert report.erased
    assert report.findings == ()


def test_subject_erasure_is_residual_when_a_record_remains() -> None:
    store, tenant, present = _populated_store()
    manifest = SubjectManifest(
        subject_ref="user-2", records={Surface.VECTOR_DB: (present, "deleted-1")}
    )
    report = SubjectErasureProbe(vector=store).verify(tenant, manifest)
    surfaces = {s.surface: s for s in report.surfaces}
    assert surfaces[Surface.VECTOR_DB].markers_before == 2
    assert surfaces[Surface.VECTOR_DB].residual_after == 1  # the still-present id
    assert report.coverage()[Surface.VECTOR_DB] is CoverageVerdict.RESIDUAL
    assert report.genuine_residual
    assert not report.erased
    assert len(report.findings) == 1
    assert report.findings[0].surface is Surface.VECTOR_DB


def test_subject_erasure_covers_the_cache_surface_by_key() -> None:
    store, tenant, _present = _populated_store()
    cache = FakeCache()
    cache.set(tenant, "live-key", "value")
    manifest = SubjectManifest(
        subject_ref="user-3",
        records={Surface.SEMANTIC_CACHE: ("live-key", "evicted-key")},
    )
    report = SubjectErasureProbe(vector=store, cache=cache).verify(tenant, manifest)
    cache_surface = {s.surface: s for s in report.surfaces}[Surface.SEMANTIC_CACHE]
    assert cache_surface.markers_before == 2
    assert cache_surface.residual_after == 1  # "live-key" is still present
    assert report.coverage()[Surface.SEMANTIC_CACHE] is CoverageVerdict.RESIDUAL


def test_subject_erasure_surface_with_no_supplied_ids_is_not_covered() -> None:
    store, tenant, _present = _populated_store()
    # Cache adapter configured, but the manifest supplies no cache ids.
    manifest = SubjectManifest(subject_ref="user-4", records={Surface.VECTOR_DB: ("deleted-1",)})
    report = SubjectErasureProbe(vector=store, cache=FakeCache()).verify(tenant, manifest)
    assert report.coverage()[Surface.SEMANTIC_CACHE] is CoverageVerdict.NOT_COVERED
    assert Surface.SEMANTIC_CACHE not in {s.surface for s in report.surfaces}


def test_subject_erasure_surface_without_an_adapter_is_not_covered_not_erased() -> None:
    # ids supplied for the cache, but no cache adapter to check them: the surface
    # must read NOT_COVERED, never a vacuous ERASED (it was not actually verified).
    store, tenant, _present = _populated_store()
    manifest = SubjectManifest(
        subject_ref="user-5", records={Surface.SEMANTIC_CACHE: ("some-key",)}
    )
    report = SubjectErasureProbe(vector=store).verify(tenant, manifest)
    assert report.coverage()[Surface.SEMANTIC_CACHE] is CoverageVerdict.NOT_COVERED
    assert report.surfaces == ()  # nothing was verifiable


def test_subject_erasure_unsupported_surface_is_not_covered() -> None:
    # A surface with no by-id primitive (agent memory) cannot be verified by id.
    store, tenant, _present = _populated_store()
    manifest = SubjectManifest(
        subject_ref="user-6",
        records={Surface.VECTOR_DB: ("deleted-1",), Surface.AGENT_MEMORY: ("mem-1",)},
    )
    report = SubjectErasureProbe(vector=store).verify(tenant, manifest)
    assert report.coverage()[Surface.AGENT_MEMORY] is CoverageVerdict.NOT_COVERED


def test_subject_erasure_residual_finding_carries_no_subject_content() -> None:
    # The manifest holds ids only; a residual finding must reference the record id
    # and subject ref, never subject PII content.
    store, tenant, present = _populated_store()
    manifest = SubjectManifest(subject_ref="user-7", records={Surface.VECTOR_DB: (present,)})
    report = SubjectErasureProbe(vector=store).verify(tenant, manifest)
    finding = report.findings[0]
    assert finding.marker_id == present
    assert "user-7" in finding.evidence_span
    assert present in finding.evidence_span


def _content_phrase() -> tuple[FakeVectorStore, UUID, str]:
    substrate = build_substrate(default_scenario(seed=2026))
    tenant = substrate.tenants[0].tenant_id
    docs = [doc for doc in substrate.documents if doc.tenant_id == tenant]
    store = FakeVectorStore()
    store.upsert(tenant, docs)
    # A phrase drawn from a real document's content, so a semantic query surfaces it.
    return store, tenant, " ".join(docs[0].content.split()[:4])


def test_subject_erasure_fingerprint_flags_residual_content() -> None:
    store, tenant, phrase = _content_phrase()
    manifest = SubjectManifest(
        subject_ref="u-fp1", records={}, fingerprints={Surface.VECTOR_DB: (phrase,)}
    )
    report = SubjectErasureProbe(vector=store).verify(tenant, manifest)
    surface = {s.surface: s for s in report.surfaces}[Surface.VECTOR_DB]
    assert surface.markers_before == 1
    assert surface.residual_after == 1  # the subject's content still surfaces
    assert report.coverage()[Surface.VECTOR_DB] is CoverageVerdict.RESIDUAL
    # The finding stores a hash of the phrase, never the raw content (no PII).
    finding = report.findings[0]
    assert phrase not in finding.evidence_span
    assert "fingerprint" in finding.finding_id


def test_subject_erasure_fingerprint_erased_when_content_absent() -> None:
    store, tenant, _phrase = _content_phrase()
    manifest = SubjectManifest(
        subject_ref="u-fp2",
        records={},
        fingerprints={Surface.VECTOR_DB: ("zzxq nonexistent 90218 phrase",)},
    )
    report = SubjectErasureProbe(vector=store).verify(tenant, manifest)
    assert report.coverage()[Surface.VECTOR_DB] is CoverageVerdict.ERASED
    assert report.erased


def test_subject_erasure_combines_id_and_content_into_one_verdict() -> None:
    store, tenant, phrase = _content_phrase()
    manifest = SubjectManifest(
        subject_ref="u-fp3",
        records={Surface.VECTOR_DB: ("already-deleted-id",)},
        fingerprints={Surface.VECTOR_DB: (phrase,)},
    )
    report = SubjectErasureProbe(vector=store).verify(tenant, manifest)
    surface = {s.surface: s for s in report.surfaces}[Surface.VECTOR_DB]
    assert surface.markers_before == 2  # one id + one content fingerprint
    assert surface.residual_after == 1  # id gone, but content still surfaces
    assert report.coverage()[Surface.VECTOR_DB] is CoverageVerdict.RESIDUAL


def test_subject_erasure_fingerprint_content_never_reaches_the_evidence_pack() -> None:
    # The strongest PII guarantee: even when a fingerprint phrase surfaces (so a
    # finding is emitted), the raw content must appear nowhere in the signed
    # evidence pack or its in-toto statement - only its hash.
    import json
    from datetime import UTC, datetime

    from sectum_ai.evidence import build_evidence_pack, control_mappings, to_in_toto_statement
    from sectum_ai.probes import confirmed_findings
    from sectum_ai.spec import RunMetrics, RunResult, canonical_hash

    store, tenant, phrase = _content_phrase()
    report = SubjectErasureProbe(vector=store).verify(
        tenant,
        SubjectManifest(
            subject_ref="leak", records={}, fingerprints={Surface.VECTOR_DB: (phrase,)}
        ),
    )
    assert report.findings, "the phrase must surface so there is a finding to leak-check"
    run = RunResult(
        run_id="erasure-subject-leak",
        scenario_hash="0" * 64,
        manifest_hash=canonical_hash(build_substrate(default_scenario(seed=2026)).manifest),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        adapter_versions={},
        probe_versions={},
        findings=report.findings,
        metrics=RunMetrics(
            confirmed_findings=len(confirmed_findings(report.findings)),
            erasure_coverage={s.value: v.value for s, v in report.coverage().items()},
        ),
    )
    manifest = build_substrate(default_scenario(seed=2026)).manifest
    pack = build_evidence_pack(run, manifest, control_mappings=control_mappings())
    assert phrase not in pack.model_dump_json()
    assert phrase not in json.dumps(to_in_toto_statement(pack))


def test_subject_erasure_verifies_tracing_by_id() -> None:
    tenant = UUID(int=1)
    obs = FakeObservability()
    trace_id = obs.record(tenant, "proj", "a trace about the subject")
    manifest = SubjectManifest(
        subject_ref="u-tr", records={Surface.TRACING: (trace_id, "deleted-trace")}
    )
    report = SubjectErasureProbe(observability=obs).verify(tenant, manifest)
    surface = {s.surface: s for s in report.surfaces}[Surface.TRACING]
    assert surface.markers_before == 2
    assert surface.residual_after == 1  # the recorded trace id is still present
    assert report.coverage()[Surface.TRACING] is CoverageVerdict.RESIDUAL


def test_subject_erasure_tracing_not_covered_without_by_id_support() -> None:
    # An observability adapter without a by-id fetch (fetch_trace raises) must read
    # NOT_COVERED, never a false ERASED.
    class _NoFetch(FakeObservability):
        def fetch_trace(self, tenant: UUID, trace_id: str) -> None:
            raise NotImplementedError

    tenant = UUID(int=1)
    manifest = SubjectManifest(subject_ref="u-tr2", records={Surface.TRACING: ("t1",)})
    report = SubjectErasureProbe(observability=_NoFetch()).verify(tenant, manifest)
    assert report.coverage()[Surface.TRACING] is CoverageVerdict.NOT_COVERED
    assert report.surfaces == ()


def test_subject_erasure_dedupes_repeated_ids() -> None:
    # A manifest that repeats an id counts it once (distinct markers_before) and
    # emits a single finding, so finding_ids stay unique (no colliding OSCAL UUIDs).
    store, tenant, present = _populated_store()
    manifest = SubjectManifest(
        subject_ref="user-8", records={Surface.VECTOR_DB: (present, present, "deleted-1")}
    )
    report = SubjectErasureProbe(vector=store).verify(tenant, manifest)
    surface = {s.surface: s for s in report.surfaces}[Surface.VECTOR_DB]
    assert surface.markers_before == 2  # (present, deleted-1) - the duplicate counts once
    assert surface.residual_after == 1  # only `present` still exists
    assert len(report.findings) == 1
    assert len({f.finding_id for f in report.findings}) == 1


def _model_with_memorized_phrase() -> tuple[FakeModel, UUID, str]:
    tenant = UUID(int=7)
    phrase = "Maria Chen lives at 12 Elm Street"
    model = FakeModel()
    model.train_adapter(tenant, [phrase])  # the model memorized the subject's content
    return model, tenant, phrase


def test_subject_erasure_model_fingerprint_flags_residual_memorization() -> None:
    model, tenant, phrase = _model_with_memorized_phrase()
    manifest = SubjectManifest(
        subject_ref="u-m1", records={}, fingerprints={Surface.MODEL_ADAPTER: (phrase,)}
    )
    report = SubjectErasureProbe(model=model).verify(tenant, manifest)
    surface = {s.surface: s for s in report.surfaces}[Surface.MODEL_ADAPTER]
    assert surface.markers_before == 1
    assert surface.residual_after == 1  # the model still reproduces the subject's content
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.RESIDUAL
    # The finding stores a hash of the phrase, never the raw content (no PII).
    finding = report.findings[0]
    assert phrase not in finding.evidence_span
    assert "fingerprint" in finding.finding_id
    assert finding.surface is Surface.MODEL_ADAPTER


def test_subject_erasure_model_fingerprint_erased_when_forgotten() -> None:
    model, tenant, phrase = _model_with_memorized_phrase()
    model.delete(tenant)  # the customer's erasure retired the tenant's adapter
    manifest = SubjectManifest(
        subject_ref="u-m2", records={}, fingerprints={Surface.MODEL_ADAPTER: (phrase,)}
    )
    report = SubjectErasureProbe(model=model).verify(tenant, manifest)
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.ERASED
    assert report.erased


def test_subject_erasure_model_serving_only_is_not_covered() -> None:
    # A serving-only model (no per-tenant adapter / shared-weights training) memorized
    # nothing, so the model surface reads NOT_COVERED - never a vacuous ERASED - and
    # inference is never invoked (the capability gate short-circuits before infer).
    class _ServingOnly(FakeModel):
        def __init__(self) -> None:
            super().__init__()
            self.capabilities = frozenset()  # a stateless inference endpoint

        def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
            raise AssertionError("a serving-only model must not be probed for memorization")

    tenant = UUID(int=7)
    manifest = SubjectManifest(
        subject_ref="u-m3", records={}, fingerprints={Surface.MODEL_ADAPTER: ("Maria Chen",)}
    )
    report = SubjectErasureProbe(model=_ServingOnly()).verify(tenant, manifest)
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.NOT_COVERED
    assert Surface.MODEL_ADAPTER not in {s.surface for s in report.surfaces}


_EXTRACTION_PHRASE = "patient dana lin diagnosis reference code ZX90210QQ"


def test_subject_erasure_model_fingerprint_detects_prefix_continuation() -> None:
    # A real autoregressive model does not ECHO the prompt - it CONTINUES it - so the
    # whole-phrase probe finds nothing (the prompt is stripped from the completion).
    # The probe must also try prefix->suffix extraction: prompt with the phrase's
    # leading half and catch the sensitive trailing half regurgitated. This locks
    # that detection path deterministically, without a real model.
    class _Continuation(FakeModel):
        def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
            # Regurgitate the memorized remainder for a leading slice of the phrase;
            # never echo the whole phrase back.
            if prompt and prompt != _EXTRACTION_PHRASE and _EXTRACTION_PHRASE.startswith(prompt):
                return _EXTRACTION_PHRASE[len(prompt) :] + " and further clinical notes"
            return "an unrelated model continuation"

    report = SubjectErasureProbe(model=_Continuation()).verify(
        UUID(int=7),
        SubjectManifest(
            subject_ref="u-m4",
            records={},
            fingerprints={Surface.MODEL_ADAPTER: (_EXTRACTION_PHRASE,)},
        ),
    )
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.RESIDUAL
    assert report.findings and "fingerprint" in report.findings[0].finding_id


def test_subject_erasure_model_fingerprint_clean_when_not_regurgitated() -> None:
    # A model that neither echoes nor regurgitates the suffix reads ERASED: the
    # prefix-continuation probe does not false-positive on an unrelated continuation.
    class _NoRecall(FakeModel):
        def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
            return "an unrelated model continuation with nothing sensitive"

    report = SubjectErasureProbe(model=_NoRecall()).verify(
        UUID(int=7),
        SubjectManifest(
            subject_ref="u-m5",
            records={},
            fingerprints={Surface.MODEL_ADAPTER: (_EXTRACTION_PHRASE,)},
        ),
    )
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.ERASED


def test_subject_erasure_model_fingerprint_single_token_uses_whole_phrase_only() -> None:
    # A single-token fingerprint has no prefix/suffix to split, so only whole-phrase
    # recall applies; an unrecalled single token reads ERASED.
    class _NoRecall(FakeModel):
        def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
            return "an unrelated continuation"

    report = SubjectErasureProbe(model=_NoRecall()).verify(
        UUID(int=7),
        SubjectManifest(
            subject_ref="u-m6", records={}, fingerprints={Surface.MODEL_ADAPTER: ("ZX90210QQ",)}
        ),
    )
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.ERASED
