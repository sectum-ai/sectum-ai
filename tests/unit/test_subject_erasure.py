"""Tests for A3 Phase 0 - the by-id data-subject erasure probe."""

from uuid import UUID

from sectum_ai.adapters import (
    FakeCache,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeSearchIndex,
    FakeVectorStore,
)
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
            # Regurgitate the memorized remainder for a leading slice of the phrase
            # (the trained tenant only); never echo the whole phrase back.
            if (
                tenant == UUID(int=7)
                and prompt
                and prompt != _EXTRACTION_PHRASE
                and _EXTRACTION_PHRASE.startswith(prompt)
            ):
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


_MEMORY_PHRASE = "Maria Chen lives at 12 Elm Street"


def test_subject_erasure_memory_fingerprint_flags_residual_content() -> None:
    # The subject's content still lives in the agent-memory store (a failed/soft
    # deletion): a keyword recall surfaces it, so the surface reads RESIDUAL.
    tenant = UUID(int=8)
    memory = FakeMemory()
    memory.remember(tenant, _MEMORY_PHRASE)
    manifest = SubjectManifest(
        subject_ref="u-mem1", records={}, fingerprints={Surface.AGENT_MEMORY: (_MEMORY_PHRASE,)}
    )
    report = SubjectErasureProbe(memory=memory).verify(tenant, manifest)
    surface = {s.surface: s for s in report.surfaces}[Surface.AGENT_MEMORY]
    assert surface.markers_before == 1
    assert surface.residual_after == 1
    assert report.coverage()[Surface.AGENT_MEMORY] is CoverageVerdict.RESIDUAL
    # Data-minimized: the finding carries a hash of the phrase, never the raw PII.
    finding = report.findings[0]
    assert _MEMORY_PHRASE not in finding.evidence_span
    assert "fingerprint" in finding.finding_id
    assert finding.surface is Surface.AGENT_MEMORY


def test_subject_erasure_memory_fingerprint_erased_when_purged() -> None:
    # The customer's erasure purged the tenant's memory: a recall surfaces nothing,
    # so the surface reads ERASED.
    tenant = UUID(int=8)
    memory = FakeMemory()
    memory.remember(tenant, _MEMORY_PHRASE)
    memory.delete(tenant)  # a real (hard) purge
    manifest = SubjectManifest(
        subject_ref="u-mem2", records={}, fingerprints={Surface.AGENT_MEMORY: (_MEMORY_PHRASE,)}
    )
    report = SubjectErasureProbe(memory=memory).verify(tenant, manifest)
    assert report.coverage()[Surface.AGENT_MEMORY] is CoverageVerdict.ERASED
    assert report.erased


def test_subject_erasure_memory_soft_delete_leaves_residue() -> None:
    # A soft-delete memory store acknowledges the purge but keeps the entries, so
    # the subject's content still surfaces - the Class 8/11 residue.
    tenant = UUID(int=8)
    memory = FakeMemory(soft_delete=True)
    memory.remember(tenant, _MEMORY_PHRASE)
    memory.delete(tenant)  # acknowledged, but the entry survives
    manifest = SubjectManifest(
        subject_ref="u-mem3", records={}, fingerprints={Surface.AGENT_MEMORY: (_MEMORY_PHRASE,)}
    )
    report = SubjectErasureProbe(memory=memory).verify(tenant, manifest)
    assert report.coverage()[Surface.AGENT_MEMORY] is CoverageVerdict.RESIDUAL


def test_subject_erasure_memory_not_covered_without_fingerprints() -> None:
    # A memory adapter is configured, but the manifest supplies no memory fingerprint:
    # the surface reads NOT_COVERED, never a vacuous ERASED.
    tenant = UUID(int=8)
    manifest = SubjectManifest(
        subject_ref="u-mem4", records={}, fingerprints={Surface.VECTOR_DB: ("anything",)}
    )
    report = SubjectErasureProbe(vector=FakeVectorStore(), memory=FakeMemory()).verify(
        tenant, manifest
    )
    assert report.coverage()[Surface.AGENT_MEMORY] is CoverageVerdict.NOT_COVERED
    assert Surface.AGENT_MEMORY not in {s.surface for s in report.surfaces}


_SEARCH_PHRASE = "quarterly revenue projection for account Northwind"


def test_subject_erasure_search_fingerprint_flags_residual_content() -> None:
    # The subject's content still lives in the derived full-text search index: a
    # search surfaces it, so the surface reads RESIDUAL.
    tenant = UUID(int=9)
    search = FakeSearchIndex()
    search.index(tenant, _SEARCH_PHRASE)
    manifest = SubjectManifest(
        subject_ref="u-si1", records={}, fingerprints={Surface.SEARCH_INDEX: (_SEARCH_PHRASE,)}
    )
    report = SubjectErasureProbe(search_index=search).verify(tenant, manifest)
    surface = {s.surface: s for s in report.surfaces}[Surface.SEARCH_INDEX]
    assert surface.markers_before == 1
    assert surface.residual_after == 1
    assert report.coverage()[Surface.SEARCH_INDEX] is CoverageVerdict.RESIDUAL
    finding = report.findings[0]
    assert _SEARCH_PHRASE not in finding.evidence_span
    assert "fingerprint" in finding.finding_id
    assert finding.surface is Surface.SEARCH_INDEX


def test_subject_erasure_search_fingerprint_erased_when_purged() -> None:
    # The customer's erasure dropped the tenant's documents from the index: a search
    # surfaces nothing, so the surface reads ERASED.
    tenant = UUID(int=9)
    search = FakeSearchIndex()
    search.index(tenant, _SEARCH_PHRASE)
    search.delete(tenant)
    manifest = SubjectManifest(
        subject_ref="u-si2", records={}, fingerprints={Surface.SEARCH_INDEX: (_SEARCH_PHRASE,)}
    )
    report = SubjectErasureProbe(search_index=search).verify(tenant, manifest)
    assert report.coverage()[Surface.SEARCH_INDEX] is CoverageVerdict.ERASED
    assert report.erased


def test_subject_erasure_search_soft_delete_leaves_residue() -> None:
    # A soft-delete search index acknowledges the drop but keeps the documents
    # searchable - the Class 11 residue in the tenth hiding place.
    tenant = UUID(int=9)
    search = FakeSearchIndex(soft_delete=True)
    search.index(tenant, _SEARCH_PHRASE)
    search.delete(tenant)
    manifest = SubjectManifest(
        subject_ref="u-si3", records={}, fingerprints={Surface.SEARCH_INDEX: (_SEARCH_PHRASE,)}
    )
    report = SubjectErasureProbe(search_index=search).verify(tenant, manifest)
    assert report.coverage()[Surface.SEARCH_INDEX] is CoverageVerdict.RESIDUAL


def test_subject_erasure_search_not_covered_without_fingerprints() -> None:
    # A search-index adapter is configured, but the manifest supplies no search
    # fingerprint: the surface reads NOT_COVERED, never a vacuous ERASED.
    tenant = UUID(int=9)
    manifest = SubjectManifest(
        subject_ref="u-si4", records={}, fingerprints={Surface.VECTOR_DB: ("anything",)}
    )
    report = SubjectErasureProbe(vector=FakeVectorStore(), search_index=FakeSearchIndex()).verify(
        tenant, manifest
    )
    assert report.coverage()[Surface.SEARCH_INDEX] is CoverageVerdict.NOT_COVERED
    assert Surface.SEARCH_INDEX not in {s.surface for s in report.surfaces}


class _MemorizingModel(FakeModel):
    """A real autoregressive model: it CONTINUES a prompt, it never echoes it.

    The tenant's adapter has memorized ``secret``, so a prompt that is a proper
    prefix of it comes back completed with the remainder - the textbook
    extraction signal. Any other tenant answers from the base weights.
    """

    def __init__(self, secret: str, tenant: UUID | None = None) -> None:
        super().__init__()
        self._secret = secret
        self._tenant = tenant if tenant is not None else UUID(int=0xA)

    def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
        if (
            tenant == self._tenant
            and prompt
            and self._secret.startswith(prompt)
            and prompt != self._secret
        ):
            return self._secret[len(prompt) :]
        return "I cannot help with that."


def test_a_memorized_single_token_subject_is_not_attested_erased() -> None:
    # A subject fingerprint is often ONE token - an email address, an account
    # number, a national id - which is exactly what an erasure request turns on.
    # The prefix-continuation detector split on whitespace and gave up below two
    # tokens, while the whole-phrase detector never matches on a real model (it
    # continues rather than echoes). Both were inert, so the model surface
    # attested ERASED for a subject the model still regurgitates on demand - a
    # false erasure claim in the GDPR wedge. Cutting mid-token catches it.
    target = UUID(int=0xA)
    for secret in ("alice.brown@example.com", "ACCT-90013455512"):
        model = _MemorizingModel(secret)
        # premise: the model demonstrably still holds it
        half = len(secret) // 2
        assert model.infer(target, secret[:half]) == secret[half:]
        assert SubjectErasureProbe._content_recalled(model, target, secret)


def test_a_forgotten_single_token_subject_still_reads_clean() -> None:
    # The zero-FP side: cutting mid-token must not turn every single-token
    # fingerprint into a residual. A model that memorized something else answers
    # nothing useful, and the surface stays clean.
    target = UUID(int=0xA)
    model = _MemorizingModel("someone.else@example.com")
    assert not SubjectErasureProbe._content_recalled(model, target, "alice.brown@example.com")


def test_a_one_character_fingerprint_has_nothing_to_split() -> None:
    # Degenerate input must not crash or claim a residual: there is no prefix to
    # prompt with, so the honest answer is the whole-phrase test's result.
    target = UUID(int=0xA)
    assert not SubjectErasureProbe._content_recalled(_MemorizingModel("x"), target, "x")


class _GenericModel(FakeModel):
    """A base model with no subject data: it completes what any model completes."""

    def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
        if "@" in prompt and not prompt.endswith("@example.com"):
            return "@example.com"
        if prompt.split() and prompt.split()[-1].istitle():
            return "Smith"
        return "I cannot help with that."


def test_a_generic_completion_is_not_residual_memorization() -> None:
    # The prefix-continuation check had no control arm: "@example.com" after any
    # local part and "Smith" after "John" counted as recall, so a model that was
    # never trained on the subject signed a CONFIRMED HIGH residual (confidence
    # 1.0) for their email and their name.
    target = UUID(int=0xA)
    model = _GenericModel()
    assert not SubjectErasureProbe._content_recalled(model, target, "alice.brown@example.com")
    # A two-token name has no trailing part long enough to be evidence either way:
    # the model surface does not check it, and reads NOT_COVERED rather than a
    # verdict a guess could produce.
    assert SubjectErasureProbe._continuation_split("John Smith") is None
    report = SubjectErasureProbe(model=model).verify(
        target,
        SubjectManifest(
            subject_ref="u-g1", records={}, fingerprints={Surface.MODEL_ADAPTER: ("John Smith",)}
        ),
    )
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.NOT_COVERED


def test_an_email_is_cut_inside_its_local_part() -> None:
    # Cutting at the midpoint of "alice.brown@example.com" left the bare domain as
    # the suffix; the cut now keeps subject-specific characters on both sides.
    split = SubjectErasureProbe._continuation_split("alice.brown@example.com")
    assert split is not None
    prefix, suffix = split
    assert "@" not in prefix and suffix.endswith("@example.com") and suffix != "@example.com"
    # and a model that genuinely memorized the address is still caught (the
    # scrambled control prefix does not reproduce it).
    memorized = _MemorizingModel("alice.brown@example.com")
    assert SubjectErasureProbe._content_recalled(
        memorized, UUID(int=0xA), "alice.brown@example.com"
    )


def test_a_non_latin_subject_is_still_caught() -> None:
    # The ASCII-only scramble left a Cyrillic / CJK prefix identical to the
    # subject's, so the control arm vetoed every genuine recall: a memorized
    # non-Latin subject attested ERASED on the model surface.
    from sectum_ai.probes._recall import scramble

    target = UUID(int=0xA)
    for secret in ("Иван Петрович Сидоров", "田中太郎 東京都千代田区", "Γιώργος Παπαδόπουλος"):
        assert scramble(secret.split()[0]) not in (None, secret.split()[0])
        assert SubjectErasureProbe._content_recalled(_MemorizingModel(secret), target, secret)
    assert scramble("x²y") is not None  # a superscript digit is not int()-able


def test_world_knowledge_is_not_the_tenants_residual() -> None:
    # A base model completes "Barack" -> "Hussein Obama" for any tenant; the
    # scrambled-prefix control cannot see that, so a public-figure fingerprint
    # signed a CONFIRMED HIGH residual memorization by the tenant's adapter.
    class _WorldModel(FakeModel):
        def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
            return "Hussein Obama" if prompt.endswith("Barack") else "I cannot help with that."

    target = UUID(int=0xA)
    assert not SubjectErasureProbe._content_recalled(_WorldModel(), target, "Barack Hussein Obama")
    # ... while a tenant-specific recall (base answers nothing) still counts.
    assert SubjectErasureProbe._content_recalled(
        _MemorizingModel("Barack Hussein Obama"), target, "Barack Hussein Obama"
    )


def test_unverifiable_fingerprints_make_the_surface_not_covered() -> None:
    # Fingerprints the split refused were dropped silently and the surface still
    # read ERASED "for the subject" on the ones that survived.
    report = SubjectErasureProbe(model=_MemorizingModel("nothing here")).verify(
        UUID(int=0xA),
        SubjectManifest(
            subject_ref="u-u1",
            records={},
            fingerprints={Surface.MODEL_ADAPTER: ("John Smith", "Ana Li", _EXTRACTION_PHRASE)},
        ),
    )
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.NOT_COVERED
    assert report.unverifiable == {Surface.MODEL_ADAPTER: 2}


def test_an_echoing_base_model_is_not_residual_memorization() -> None:
    # The whole-phrase branch had no control: a chatty base that restates the
    # prompt ('I have no record matching "John Smith"') signed a RESIDUAL for a
    # tenant that trained nothing, and a hard delete then read as a failure.
    class _EchoingBase(FakeModel):
        def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
            return f'I have no record matching "{prompt}".'

    target = UUID(int=0xA)
    assert not SubjectErasureProbe._content_recalled(_EchoingBase(), target, _EXTRACTION_PHRASE)
    report = SubjectErasureProbe(model=_EchoingBase()).verify(
        target,
        SubjectManifest(
            subject_ref="u-e1",
            records={},
            fingerprints={Surface.MODEL_ADAPTER: (_EXTRACTION_PHRASE,)},
        ),
    )
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.ERASED
    # ... while a genuine per-tenant echo (the base answers nothing) still counts.
    model, tenant, phrase = _model_with_memorized_phrase()
    assert SubjectErasureProbe._content_recalled(model, tenant, phrase)


def test_unverifiable_fingerprints_do_not_hide_a_residual_one() -> None:
    # One unverifiable phrase used to suppress the scan of every verifiable one:
    # the DPO was told "not checked" about content the model still reproduced.
    secret = _EXTRACTION_PHRASE
    report = SubjectErasureProbe(model=_MemorizingModel(secret)).verify(
        UUID(int=0xA),
        SubjectManifest(
            subject_ref="u-u2",
            records={},
            fingerprints={Surface.MODEL_ADAPTER: ("John Smith", secret)},
        ),
    )
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.RESIDUAL
    assert report.unverifiable == {Surface.MODEL_ADAPTER: 1}
    assert report.findings and "fingerprint" in report.findings[0].finding_id


def test_an_echo_on_shared_weights_is_not_recall_either() -> None:
    # The scrambled control searched for the ORIGINAL phrase in the scrambled
    # prompt's completion, so an echoing model always passed it, and on shared
    # weights (no base-tenant control) the echo signed a CONFIRMED HIGH residual
    # and a Class 11 erasure failure.
    class _EchoingShared(FakeModel):
        def __init__(self) -> None:
            super().__init__(adapter_bleed=True)

        def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
            return f'I have no record matching "{prompt}".'

    target = UUID(int=0xA)
    assert not SubjectErasureProbe._content_recalled(_EchoingShared(), target, _EXTRACTION_PHRASE)


def test_a_full_similarity_page_without_the_phrase_is_not_erased() -> None:
    # The vector fingerprint check was a top-k similarity query: a stored subject
    # document ranked past k read as absent, and the surface attested ERASED.
    from sectum_ai.probes._recall import FINGERPRINT_QUERY_K
    from sectum_ai.spec import CorpusDocument

    store = FakeVectorStore()
    tenant = UUID(int=0xA)
    phrase = "maria chen clinical intake note reference"
    docs = [
        CorpusDocument(
            doc_id=f"sib-{i}",
            tenant_id=tenant,
            doc_type="note",
            title="maria chen clinical intake note",
            content="maria chen clinical intake note filler",
        )
        for i in range(FINGERPRINT_QUERY_K + 5)
    ]
    docs.append(
        CorpusDocument(
            doc_id="subject", tenant_id=tenant, doc_type="note", title="zz", content=phrase
        )
    )
    store.upsert(tenant, docs)
    report = SubjectErasureProbe(vector=store).verify(
        tenant,
        SubjectManifest(
            subject_ref="u-v1", records={}, fingerprints={Surface.VECTOR_DB: (phrase,)}
        ),
    )
    assert report.coverage()[Surface.VECTOR_DB] is not CoverageVerdict.ERASED
    assert report.unverifiable.get(Surface.VECTOR_DB, 0) == 1 or report.findings


def test_world_knowledge_on_shared_weights_is_unverifiable_not_residual() -> None:
    # The base-knowledge control is "the same prompt as a tenant that trained
    # nothing", which a shared-weights model does not have: a model that trained
    # nothing and completes "Sherlock Holmes" -> "221B Baker Street" signed a
    # CONFIRMED HIGH residual at confidence 1.0 in a DSR attestation.
    class _WorldKnowledge(FakeModel):
        def __init__(self) -> None:
            super().__init__(adapter_bleed=True)  # SHARED_WEIGHTS

        def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
            return "221B Baker Street, London" if prompt.startswith("Sherlock") else "no idea"

    report = SubjectErasureProbe(model=_WorldKnowledge()).verify(
        UUID(int=0xA),
        SubjectManifest(
            subject_ref="u-w1",
            records={},
            fingerprints={Surface.MODEL_ADAPTER: ("Sherlock Holmes 221B Baker Street",)},
        ),
    )
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.NOT_COVERED
    assert report.findings == ()
