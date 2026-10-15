"""The exact then semantic then judge leak-detection pipeline (the engineering spec, section 6.4).

A leak is a marker owned by tenant X observed in tenant Y's session. Detection
runs cheapest-and-most-certain first:

1. Exact scan for HARD_CANARY plaintext, and a credential-format scan for
   SECRET_CANARY (the spec, section 6.3: "exact + format detector"): a
   cross-tenant hit is a confirmed critical leak (confidence 1.0).
2. Semantic similarity against foreign ENTITY_CANARY markers yields candidates.
3. A calibrated judge adjudicates each candidate.

Manifest-grounded by construction: every finding ties back to a manifest
marker. A finding is ``CONFIRMED`` on an exact/format hit, on a foreign entity
whose plaintext is literally present in the observation (a leak by observation,
which no judge verdict can unmake), or on a judge verdict whose cited evidence
is traceable to the marker. That bounds confirmations to the manifest's own
markers; it is not a claim that every confirmation is correct, since a semantic
confirmation still rests on the configured judge. Text containing no manifest
marker can never produce a confirmed finding (the engineering spec, section 6.4;
tested as an invariant).
"""

import hashlib
import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sectum_ai.spec import (
    Finding,
    FindingStatus,
    Marker,
    MarkerType,
    Observation,
    Principal,
    ProbeStep,
    Severity,
    SharedEntity,
    Substrate,
    Surface,
    get_logger,
    normalize_for_match,
    ordered_within_span,
    residual_present,
    tokenize,
)

_log = get_logger(__name__)

_OWASP_MULTI_TENANT = "LLM08:2025"

# The conservative semantic-similarity gate that suits the deterministic fake
# embedder; the back-compatible default when no per-model preset applies (the
# engineering spec, section 6.4: "default conservative").
DEFAULT_SEMANTIC_THRESHOLD = 0.62

# Per-embedding-model semantic-threshold presets: sensible per-model STARTING
# POINTS, not a substitute for calibration. ``semantic_threshold: auto`` resolves
# to one of these by the configured embedder model. Today the config exposes the
# ``fake`` and ``openai`` embedder kinds, so ``auto`` reaches the ``openai:*``
# entries (and the fake's default); the ``st:*`` presets apply when those models
# are calibrated or swept by name (``sectum-ai calibrate --embedder st:<model>``),
# since ``EmbeddingModel`` produces the same ``st:<model>`` / ``openai:<model>``
# canonical names. Only ``openai:text-embedding-3-small`` (~0.80) is grounded in a
# real run, where the gate had to be raised from the 0.62 default to avoid
# flooding the judge (a stronger model packs unrelated text closer together); the
# others are conservative starting points. The exact F1-maximising, zero-FP gate
# depends on your substrate and model, so run ``sectum-ai calibrate --embedder
# <kind:model>`` to derive the right value rather than trusting the preset.
MODEL_THRESHOLDS: dict[str, float] = {
    "st:all-MiniLM-L6-v2": 0.55,
    "st:all-mpnet-base-v2": 0.60,
    "openai:text-embedding-3-small": 0.80,
    "openai:text-embedding-3-large": 0.78,
}


def resolve_semantic_threshold(model_name: str | None) -> float:
    """Resolve the calibrated semantic threshold for an embedder ``model_name``.

    Returns the per-model preset from :data:`MODEL_THRESHOLDS` when the model is
    known, else falls back to :data:`DEFAULT_SEMANTIC_THRESHOLD` and logs a
    warning so an unrecognised model never silently runs the wrong gate. A
    ``None`` name (no model configured, i.e. the fake embedder) resolves to the
    conservative default without a warning - the fake's gate is intentionally the
    default. This backs the ``semantic_threshold: auto`` config form; an explicit
    numeric threshold bypasses it entirely (back-compat).
    """
    if model_name is None:
        return DEFAULT_SEMANTIC_THRESHOLD
    preset = MODEL_THRESHOLDS.get(model_name)
    if preset is not None:
        return preset
    _log.warning(
        "detect.semantic_threshold.unknown_model",
        model=model_name,
        fallback=DEFAULT_SEMANTIC_THRESHOLD,
    )
    return DEFAULT_SEMANTIC_THRESHOLD


# Credential shapes for the SECRET_CANARY format detector (the spec, section
# 6.3: "exact + format detector"). They mirror the shapes the substrate plants
# (``sectum_ai.substrate.markers``): an OpenAI-style ``sk-`` key, an AWS access-key
# id, and a non-issuable US SSN shape (9xx area). The format pass recovers a
# secret embedded in surrounding bytes that a plain substring scan could miss.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\b9\d{2}-\d{2}-\d{4}\b"),
)


def redact_secret(plaintext: str) -> str:
    """Mask a secret canary for an evidence artifact (the spec, sections 6.3 and 16).

    An audit pack and the evidence JSON leave the box (BYOC mode), so they must
    not reproduce a credential verbatim - that would itself be the disclosure the
    report documents. Keep only a short leading hint so a reader can tell the
    credential *class* (an ``sk-`` key, an ``AKIA`` id, a 9xx SSN); the finding's
    ``marker_id`` ties it back to the access-controlled manifest for the full
    value. The elision also stops the rendered artifact from tripping a secret
    scanner: the ``...`` immediately after the hint breaks every credential regex.
    """
    return f"{plaintext[:4]}...[redacted]"


# How many foreign tokens may sit *between* a marker's tokens and still count
# as the entity surfacing. A real leak lightly paraphrases ("Project (internal)
# Onyx-00002"), so a strictly contiguous run would miss it - but the entity
# reuses common words ("project", a 5-digit serial), so a wide budget would
# admit a benign coincidence ("our project ships onyx units; lot 00002 next").
# One interposed token is the conservative floor: it catches the canonical
# paraphrase without fabricating a leak. Heavier paraphrase is left to the
# production LLM judge, which adjudicates meaning rather than token order; the
# deterministic fake judge errs toward precision (a false "leak found" is worse
# for a verification product than a missed subtle rephrase).
_MAX_INTERPOSED_TOKENS = 1

# The fixed lexical scaffolding of the substrate's entity-canary template -
# "Project <codename>-<serial>" (sectum_ai.substrate.markers). It is shared by
# every entity canary, so it is never distinctive evidence of one marker, and the
# FP-control demotes it when deciding whether a judge's cited span ties back to a
# marker. Held here as a constant rather than imported, to avoid a probes->core
# import cycle (core imports probes); a unit test pins it in sync with the
# generator's template. Demoting it must not depend on manifest size: a purely
# statistical "recurs across markers" test cannot identify the scaffolding from a
# single-entity-marker manifest, which would otherwise let a judge confirm a leak
# on the bare template word alone.
_ENTITY_TEMPLATE_TOKENS = frozenset({"project"})


def is_cross_principal(marker: Marker, observer: Principal) -> bool:
    """Whether ``marker`` is foreign to the observing principal (ADR-0006).

    Cross-tenant is always a leak. Within one tenant, the marker is foreign only
    to a user-scoped observer whose user differs from the marker's owner user; a
    tenant-level observer (or a tenant-level marker) is never crossed - the
    tenant owns all its users' data. User isolation is verified default-deny:
    any cross-user appearance is a leak, since the intended-sharing policy model
    is deferred (ADR-0006).

    Detection uses this to decide which markers are foreign to an observer;
    probe planning uses it to decide which principals to issue a step from.
    """
    if marker.owner_tenant_id != observer.tenant_id:
        return True
    if observer.user_id is None or marker.owner_user_id is None:
        return False
    return marker.owner_user_id != observer.user_id


def cross_principal_observers(
    markers: Iterable[Marker], principals: Iterable[Principal]
) -> list[Principal]:
    """The principals to whom at least one of ``markers`` is foreign.

    A probe issues its attack, query, or read step from these principals and no
    others. A step from a principal the target secret is not foreign to tests
    nothing that principal could not already see, so it can neither surface a leak
    nor honestly count as a cross-principal check - recording a probe on the
    strength of such steps grades its class a vacuous PASS (``docs/scorecard.md``,
    rule 1). When no principal is foreign to any target, this is empty and the
    probe should plant and query nothing, leaving its class ``NOT_COVERED``.
    """
    target = list(markers)
    return [p for p in principals if any(is_cross_principal(m, p) for m in target)]


def markers_naming_entity(substrate: Substrate, entity: SharedEntity) -> list[Marker]:
    """The manifest markers carried by corpus documents that name ``entity``.

    The organic-bleed probes query for a shared entity, not a specific marker, so
    the entity's foreignness to an observer is the foreignness of the canaries
    planted in the documents that mention it. ``SharedEntity`` carries no owner, so
    the link runs through the corpus: a pivot document names its entity in its body
    and carries its marker, and the document maps back to the manifest via
    ``marker_ids``. Pair with :func:`cross_principal_observers` to gate a query on a
    foreign canary for the entity actually existing.
    """
    named = {
        marker_id
        for document in substrate.documents
        if entity.value in document.content
        for marker_id in document.marker_ids
    }
    return [marker for marker in substrate.manifest.markers if marker.marker_id in named]


class EmbeddingProvider(Protocol):
    """Embeds text into a fixed-dimension vector."""

    def embed(self, text: str) -> tuple[float, ...]:
        """Return the embedding vector for ``text``."""
        ...


@dataclass(frozen=True)
class JudgeVerdict:
    """A judge's adjudication of a semantic leak candidate.

    ``evidence_span`` is the verbatim slice of the observation the judge cites
    as proof that the foreign entity surfaces (the engineering spec, section
    6.4: the judge returns ``{leak, evidence_span, rationale}``). It is the
    empty string when the judge declines to point at a span, and the detection
    pipeline carries it into ``Finding.evidence_span`` for the audit pack.
    """

    leak: bool
    rationale: str
    evidence_span: str = ""


class Judge(Protocol):
    """Adjudicates whether a semantic candidate is a genuine cross-tenant leak."""

    def judge(self, observed_text: str, marker: Marker) -> JudgeVerdict:
        """Return a verdict on whether ``observed_text`` leaks ``marker``."""
        ...


@dataclass(frozen=True)
class DetectionProviders:
    """The embedder, judge, and threshold a probe's detection pipeline should use.

    All fields default to the offline, deterministic fakes; a run configures real
    providers (see ``sectum_ai.probes.providers``) by passing this bundle through to
    each probe. A probe given no bundle behaves exactly as before.
    """

    embedder: "EmbeddingProvider | None" = None
    judge: "Judge | None" = None
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD

    def pipeline(self, substrate: Substrate) -> "DetectionPipeline":
        """Build a detection pipeline for ``substrate`` with these providers."""
        return DetectionPipeline(substrate, self.embedder, self.judge, self.semantic_threshold)


_EMPTY_EVIDENCE = (
    "cross-principal fetch returned 200-empty, not an explicit deny - "
    "negative authorization is unproven (the 200-empty vs 403 ambiguity)"
)
_EMPTY_REMEDIATION = (
    "return an explicit authorization error (e.g. 403) for cross-tenant "
    "object fetches rather than a 200 with an empty body"
)


class DetectingProbe:
    """Base for probes that run the detection pipeline.

    It carries the detection providers so a configured run threads a real
    embedder and judge through to every probe's detection; constructed with no
    argument it uses the deterministic fakes, so existing behavior is unchanged.
    Subclasses call ``self._providers.pipeline(substrate)`` in ``detect``.
    """

    # Declared by every concrete probe (the `Probe` protocol in `base.py`); named
    # here so the shared finding builders below can stamp them.
    id: str
    owasp_llm: str
    atlas_techniques: tuple[str, ...]
    nist_rmf: tuple[str, ...]

    # Secondary OWASP LLM Top 10 mapping (the spec §18: "LLM02/LLM06 secondary").
    # Every leakage probe also evidences Sensitive Information Disclosure; the
    # agent/tool probes override this to Excessive Agency (LLM06).
    owasp_secondary: tuple[str, ...] = ("LLM02:2025",)

    def __init__(self, providers: DetectionProviders | None = None) -> None:
        self._providers = providers if providers is not None else DetectionProviders()

    def _observer(self, step: ProbeStep, substrate: Substrate) -> Principal | None:
        """The principal this step acted as, or ``None`` if the substrate has none."""
        return next(
            (
                principal
                for principal in substrate.principals()
                if principal.tenant_id == step.actor_tenant_id
                and principal.user_id == step.actor_user_id
            ),
            None,
        )

    def _empty_ambiguity_finding(
        self,
        step: ProbeStep,
        observation: Observation,
        substrate: Substrate,
        *,
        marker: Marker | None,
        evidence: str = _EMPTY_EVIDENCE,
        remediation: str = _EMPTY_REMEDIATION,
        atlas: tuple[str, ...] | None = None,
    ) -> Finding | None:
        """The UNVERIFIED 200-empty finding for a cross-principal by-id read.

        Class 1's rule, and it belongs to every by-id read, not to one of them.
        ``AccessOutcome.DENIED`` is produced by no code path - the runner can only
        emit RETURNED or EMPTY - so "nothing came back" never means "the deny was
        enforced". The vector fetch said so and its two structural siblings, a
        foreign ``cache.get`` and a foreign ``mcp.invoke`` of another principal's
        resource key, did not: Classes 4 and 7 carried Class 1's evidence with
        none of its caveat, passing with an empty note.

        Each probe addresses its own marker (a planted doc id, a cache key, a
        resource key); what must not diverge is the finding, so that is here.

        ``evidence``/``remediation`` default to the 200-empty wording the three
        by-id reads share. Class 7's agent-framework probe overrides them because
        its read is ambiguous for a DIFFERENT reason - the framework answers in
        prose either way, so nothing was 200-empty - and a caveat that misstates
        what was observed is the over-claim it exists to prevent.
        """
        observer = self._observer(step, substrate)
        if observer is None or marker is None or not is_cross_principal(marker, observer):
            return None
        user_suffix = f"-{observer.user_id.hex}" if observer.user_id is not None else ""
        return Finding(
            finding_id=(
                f"finding-{self.id}-empty-{marker.marker_id}-"
                f"{observer.tenant_id.hex}{user_suffix}-{observation.surface.value}"
            ),
            probe_id=self.id,
            severity=Severity.INFO,
            confidence=0.0,
            status=FindingStatus.UNVERIFIED,
            owner_tenant_id=marker.owner_tenant_id,
            observed_in_tenant_id=observer.tenant_id,
            owner_user_id=marker.owner_user_id,
            observed_in_user_id=observer.user_id,
            surface=observation.surface,
            marker_id=marker.marker_id,
            evidence_span=evidence,
            owasp_llm=self.owasp_llm,
            owasp_secondary=self.owasp_secondary,
            # The caller's narrowing, where it has one. `AgentToolHijackProbe`
            # narrows the stamp per SUB-PROBE on its leak path - ADR-0009 adopted
            # `AML.T0051.001` for the description-injection sub-probe only, because
            # "stamping them with it would claim an attack the probe never
            # performed, in a field that ships as signed evidence" - and this
            # helper hard-coded the probe's full footprint. Measured on a real
            # `probe; report`: all 24 occurrences of `AML.T0051.001` in the signed
            # evidence sat on 200-empty notes, which observed nothing and injected
            # nothing, and none on a leak. `evidence` and `remediation` are already
            # parameterized here for exactly this reason; `atlas` was the field
            # that was not.
            atlas=self.atlas_techniques if atlas is None else atlas,
            nist=self.nist_rmf,
            remediation_pointer=remediation,
        )

    def _marker_by_id(self, substrate: Substrate, marker_id: str | None) -> Marker | None:
        return next(
            (m for m in substrate.manifest.markers if m.marker_id == marker_id),
            None,
        )


class FakeEmbeddingProvider:
    """Deterministic hashing-trick embedding for tests and offline runs.

    Not semantically meaningful beyond lexical overlap, but fully deterministic:
    identical text always embeds identically, and texts sharing tokens have
    non-zero cosine similarity.
    """

    dim = 96
    # Mirrors the substrate's _DEFAULT_EMBEDDING_MODEL: a manifest seeded offline
    # records this model in each entity marker's embedding_ref, so a default fake
    # run matches and the pipeline's embedding-model check stays silent.
    model_id = "fake-deterministic"

    def embed(self, text: str) -> tuple[float, ...]:
        """Return a unit-normalized hashing-trick vector for ``text``."""
        vector = [0.0] * self.dim
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dim] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(value / norm for value in vector)


class FakeJudge:
    """Deterministic judge: a leak requires the full marker phrase to be present.

    This keeps the zero-false-positive invariant intact - text that does not
    actually contain the foreign entity is never adjudicated as a leak.
    """

    def judge(self, observed_text: str, marker: Marker) -> JudgeVerdict:
        """Confirm only when the marker's tokens appear in order, close together.

        Token *coverage* is not enough: a benign sentence that reuses the marker's
        words in another order (``the project board, item 00002, by Onyx7K2QF``)
        covers every token of ``Project Onyx7K2QF-00002`` without containing the
        entity, so a set-overlap test would fabricate a leak. But a strict
        contiguous run is too strict the other way - a real leak that paraphrases
        (``Project (internal) Onyx7K2QF-00002``) would be missed. The tokens must therefore appear
        in order within a short span (a few interposed words allowed), which keeps
        the zero-false-positive invariant while not missing light paraphrase, and
        stays robust to spacing, casing, and punctuation.
        """
        marker_tokens = tokenize(marker.plaintext)
        if not marker_tokens:
            return JudgeVerdict(leak=False, rationale="empty marker", evidence_span="")
        if ordered_within_span(tokenize(observed_text), marker_tokens, _MAX_INTERPOSED_TOKENS):
            # On a confirmed leak the fake judge cites the marker plaintext as
            # the evidence span - the same slice the audit-pack PDF quotes.
            return JudgeVerdict(
                leak=True,
                rationale="marker tokens present in order in the observation",
                evidence_span=marker.plaintext,
            )
        return JudgeVerdict(
            leak=False,
            rationale="marker tokens not present in order within a short span",
            evidence_span="",
        )


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Cosine similarity of two equal-length vectors, in [-1, 1].

    Normalizes by the product of L2 norms, so a real (non-unit) embedder cannot
    yield a score above 1.0 - a bare dot product can, and that would overflow the
    ``Finding.confidence`` 0..1 bound and crash finding construction. The fake
    embedder already returns unit vectors, so this leaves its scores unchanged. A
    zero-norm vector has no direction, so its similarity is defined as 0.0.
    """
    dot = sum(x * y for x, y in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _token_windows(tokens: list[str], size: int) -> Iterator[list[str]]:
    """Yield contiguous token windows of ``size`` (or the whole list if shorter)."""
    if size <= 0 or len(tokens) <= size:
        yield tokens
        return
    for start in range(len(tokens) - size + 1):
        yield tokens[start : start + size]


def confirmed_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Return only the confirmed findings (the headline count)."""
    return [finding for finding in findings if finding.status is FindingStatus.CONFIRMED]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}


def _finding_strength(finding: Finding) -> tuple[int, int, float]:
    """Rank a finding so dedupe keeps the strongest of a shared finding id.

    A CONFIRMED leak must always outrank an UNVERIFIED candidate - it is what the
    headline ``confirmed_findings`` count reports - so status is the primary key;
    ties break on severity then confidence.
    """
    status_rank = 1 if finding.status is FindingStatus.CONFIRMED else 0
    return (status_rank, _SEVERITY_RANK.get(finding.severity, 0), finding.confidence)


def dedupe_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Collapse findings that share a finding id, keeping the strongest.

    The same cross-tenant leak - a marker observed in a tenant - can be detected
    by more than one probe step: a confused-deputy and a token-passthrough
    lookup that both resolve the same resource, or repeated adapter recalls.
    Each detection builds a Finding with the same id; the run record keeps one.

    When the duplicates disagree on status - a semantic-only UNVERIFIED candidate
    and a judge-CONFIRMED leak of the same marker on the same surface, which share
    a finding id because the id does not encode status - the CONFIRMED one is kept
    (then higher severity, then higher confidence). A real leak is therefore never
    dropped from the headline count in favor of an earlier UNVERIFIED duplicate.
    First-seen order is preserved.

    The TECHNIQUE lists are unioned rather than taken from the winner - but only
    across duplicates that reached the SAME verdict - because they are a property
    of the sub-probe that detected the leak and the id does not encode the
    sub-probe. `AgentToolHijackProbe` stamps `AML.T0051.001` only
    on its description-injection sub-probe (ADR-0009); that sub-probe's step is
    planned last and all four tie on status, severity and confidence, so it always
    lost. Against a server exploitable BOTH ways - the realistic case - the pack
    reported the leak and never recorded that ingested tool metadata also reached
    it, which is a different remediation. Splitting the id by sub-probe would
    inflate the confirmed-leak count instead; one leak stays one finding, carrying
    every technique that reached it.
    """
    best: dict[str, Finding] = {}
    order: list[str] = []
    for finding in findings:
        existing = best.get(finding.finding_id)
        if existing is None:
            best[finding.finding_id] = finding
            order.append(finding.finding_id)
            continue
        winner, loser = (
            (finding, existing)
            if _finding_strength(finding) > _finding_strength(existing)
            else (existing, finding)
        )
        # Only ACROSS THE SAME VERDICT. A technique describes what the detection
        # that reached this verdict did, so merging across them claims the loser's
        # attack succeeded: a CONFIRMED leak found by a `lookup` sub-probe, merged
        # with the injection sub-probe's UNVERIFIED non-finding for the same
        # resource, came out stamped `AML.T0051.001` - "the tool-description
        # injection worked here" - over an attempt that found nothing. The union
        # exists for the opposite case, two detections that BOTH confirmed.
        best[finding.finding_id] = (
            _with_techniques_of(winner, loser) if winner.status is loser.status else winner
        )
    return [best[finding_id] for finding_id in order]


def _with_techniques_of(winner: Finding, loser: Finding) -> Finding:
    """``winner`` carrying every technique either duplicate recorded.

    Order-stable and duplicate-free: the winner's own stamps stay first, so a
    finding's primary attribution does not move when an equal-strength duplicate
    happens to be seen first.
    """

    def _union(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*first, *second)))

    atlas = _union(winner.atlas, loser.atlas)
    secondary = _union(winner.owasp_secondary, loser.owasp_secondary)
    if atlas == winner.atlas and secondary == winner.owasp_secondary:
        return winner
    return winner.model_copy(update={"atlas": atlas, "owasp_secondary": secondary})


def _canonical_embedding_model(model: str) -> str:
    """Collapse a manifest/embedder model name to its embedding-space identity.

    Every ``fake-*`` name (``fake-deterministic``, and the ``fake-mini`` /
    ``fake-base`` / ``fake-strong`` sweep labels) maps to the one offline
    ``FakeEmbeddingProvider`` space - it is name-agnostic - so they compare equal.
    Any other name is its own space and is returned unchanged.
    """
    return "fake" if model.startswith("fake-") else model


class DetectionPipeline:
    """Applies exact then semantic then judge detection against a substrate."""

    def __init__(
        self,
        substrate: Substrate,
        embedder: EmbeddingProvider | None = None,
        judge: Judge | None = None,
        semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    ) -> None:
        self._markers: tuple[Marker, ...] = substrate.manifest.markers
        self._embedder: EmbeddingProvider = embedder or FakeEmbeddingProvider()
        self._judge: Judge = judge or FakeJudge()
        self._threshold = semantic_threshold
        self._entity_vectors: dict[str, tuple[float, ...]] = {}
        # Index each entity vector by its manifest embedding_ref (the engineering
        # spec, section 6.3) as well as by marker id, so detection reads the
        # vector from the address the manifest records - binding the attested test
        # condition (which model embedded the entity) to the detector.
        self._stored_vectors: dict[str, tuple[float, ...]] = {}
        entity_token_counts: dict[str, int] = {}
        entity_marker_count = 0
        for marker in self._markers:
            if marker.marker_type is MarkerType.ENTITY_CANARY:
                entity_marker_count += 1
                vector = self._embedder.embed(marker.plaintext)
                self._entity_vectors[marker.marker_id] = vector
                if marker.embedding_ref is not None:
                    self._stored_vectors[marker.embedding_ref] = vector
                for token in set(tokenize(marker.plaintext)):
                    entity_token_counts[token] = entity_token_counts.get(token, 0) + 1
        # Template boilerplate - the fixed scaffolding words every entity canary
        # ("Project <codename>-<serial>") repeats, NOT distinctive evidence of any
        # one marker - from two unioned signals:
        #   * the known template tokens, demoted regardless of manifest size (the
        #     single-entity-marker manifest is the case a statistical test cannot
        #     calibrate; without this the bare word "project" reads as distinctive);
        #   * a statistical-majority fallback for any other word a future template
        #     might share across a MAJORITY of canaries (>=2 and >half). The
        #     majority test, not a bare >=2, avoids demoting an entropic codename in
        #     the astronomically unlikely event two markers draw the same token.
        self._entity_boilerplate: frozenset[str] = _ENTITY_TEMPLATE_TOKENS | frozenset(
            token
            for token, count in entity_token_counts.items()
            if count >= 2 and 2 * count > entity_marker_count
        )
        self._warn_on_embedding_model_mismatch()

    def _warn_on_embedding_model_mismatch(self) -> None:
        """Warn when the detection embedder differs from the manifest's declared model.

        Each entity marker's ``embedding_ref`` is ``{model}/{digest}`` (the spec,
        section 6.3): it records *which* embedding model the manifest's semantic
        test condition assumes. The detector re-embeds with its own embedder, so a
        mismatch means semantic similarity is computed in a different embedding
        space than the manifest records and any calibrated threshold may not
        apply. The check is best-effort: it stays silent unless the embedder
        exposes a ``model_id`` and the manifest declares a model (so it never
        warns spuriously on an embedder that cannot name itself). Every ``fake-*``
        name collapses to one bucket first: the offline ``FakeEmbeddingProvider``
        ignores the model label (it is name-agnostic), so a ``fake-mini`` /
        ``fake-base`` / ``fake-strong`` sweep manifest shares the fake's single
        embedding space and must not warn.
        """
        embedder_model = getattr(self._embedder, "model_id", None)
        if embedder_model is None:
            return
        manifest_models = {
            marker.embedding_ref.rsplit("/", 1)[0]
            for marker in self._markers
            if marker.marker_type is MarkerType.ENTITY_CANARY and marker.embedding_ref is not None
        }
        if manifest_models and _canonical_embedding_model(embedder_model) not in {
            _canonical_embedding_model(model) for model in manifest_models
        }:
            _log.warning(
                "detect.embedding_ref.model_mismatch",
                embedder_model=embedder_model,
                manifest_models=sorted(manifest_models),
            )

    def detect(
        self,
        observed_in_tenant: UUID,
        observation_text: str,
        surface: Surface,
        probe_id: str = "manual",
        *,
        observed_user: UUID | None = None,
        owasp_llm: str = _OWASP_MULTI_TENANT,
        owasp_secondary: tuple[str, ...] = (),
        atlas: tuple[str, ...] = (),
        nist: tuple[str, ...] = (),
    ) -> list[Finding]:
        """Detect cross-principal leakage in one observation; return all findings.

        The observer is the principal whose session produced the observation:
        ``observed_in_tenant`` plus an optional ``observed_user``. A leak is a
        marker owned by a different principal (a different tenant, or a different
        user within the same tenant - ADR-0006) surfacing here. A tenant-level
        observer (``observed_user`` ``None``) detects only cross-tenant leaks, so
        existing tenant-level behavior is unchanged.

        ``owasp_llm``/``atlas``/``nist`` are the calling probe's control
        classification (the engineering spec, sections 9 and 18); each finding is
        stamped with them so the evidence pack carries per-finding control IDs.
        The defaults (the multi-tenant OWASP class, no ATLAS/NIST) leave a manual
        ``detect`` call byte-identical to before.
        """
        observer = Principal(tenant_id=observed_in_tenant, user_id=observed_user)
        findings = self._exact(observer, observation_text, surface, probe_id)
        findings.extend(self._secret_format(observer, observation_text, surface, probe_id))
        findings.extend(self._semantic(observer, observation_text, surface, probe_id))
        stamped = [
            finding.model_copy(
                update={
                    "owasp_llm": owasp_llm,
                    "owasp_secondary": owasp_secondary,
                    "atlas": atlas,
                    "nist": nist,
                }
            )
            for finding in findings
        ]
        for finding in stamped:
            if finding.status is FindingStatus.CONFIRMED:
                # The core security event: a foreign marker surfaced in this
                # principal's session. Only IDs and the control class are logged -
                # never the evidence span or marker plaintext (the spec, §16).
                _log.warning(
                    "detect.cross_tenant_leak",
                    probe=finding.probe_id,
                    marker_id=str(finding.marker_id),
                    owner_tenant=str(finding.owner_tenant_id),
                    observed_in_tenant=str(finding.observed_in_tenant_id),
                    surface=finding.surface.value,
                    severity=finding.severity.value,
                )
        return stamped

    def best_foreign_similarity(
        self,
        observed_in_tenant: UUID,
        observation_text: str,
        *,
        observed_user: UUID | None = None,
    ) -> float:
        """Max cosine of ``observation_text`` to any *foreign* ENTITY_CANARY.

        This is exactly the value the semantic gate (:meth:`_semantic`) compares
        against ``semantic_threshold`` before invoking the judge, so a calibration
        built on this method is provably consistent with detection: a threshold at
        or below this score would admit the observation as a candidate. Returns
        ``0.0`` when the observer has no foreign entity markers (nothing to gate
        against). Side-effect-free; it never builds a :class:`Finding`.
        """
        observer = Principal(tenant_id=observed_in_tenant, user_id=observed_user)
        observation_tokens = tokenize(observation_text)
        window_cache: dict[str, tuple[float, ...]] = {}
        best = 0.0
        for marker in self._foreign(observer, MarkerType.ENTITY_CANARY):
            best = max(best, self._best_window_similarity(observation_tokens, marker, window_cache))
        # Clamp defensively: a true cosine is already <= 1.0, but float rounding
        # can nudge it just past 1.0 (the same clamp _semantic applies before it
        # writes Finding.confidence), which would break a calibration's [0, 1] bound.
        return min(1.0, best)

    def _foreign(self, observer: Principal, marker_type: MarkerType) -> list[Marker]:
        return [
            marker
            for marker in self._markers
            if marker.marker_type is marker_type and is_cross_principal(marker, observer)
        ]

    def _exact(
        self, observer: Principal, text: str, surface: Surface, probe_id: str
    ) -> list[Finding]:
        findings: list[Finding] = []
        for marker in self._foreign(observer, MarkerType.HARD_CANARY):
            # THE shared predicate, not a local copy of it. This spelled the arms
            # out inline - substring, then ordered tokens - and when a third arm
            # (the alphanumeric projection, for a canary wrapped INSIDE its opaque
            # body) was added to `residual_present`, the erasure scan got it and
            # the detector did not: `residual_present` returned True on a wrapped
            # canary while this returned no finding, over the same bytes. A missed
            # HARD_CANARY is an over-claimed PASS on Classes 1, 3, 4, 7, 8 and 9,
            # and two paths answering "is the canary here" differently is exactly
            # what the shared predicate exists to stop. An empty plaintext is
            # handled there too (it would otherwise match every observation).
            if residual_present(marker.plaintext, text):
                findings.append(
                    self._finding(
                        marker,
                        observer,
                        surface,
                        probe_id,
                        severity=Severity.CRITICAL,
                        confidence=1.0,
                        status=FindingStatus.CONFIRMED,
                        evidence=marker.plaintext,
                    )
                )
        return findings

    def _secret_format(
        self, observer: Principal, text: str, surface: Surface, probe_id: str
    ) -> list[Finding]:
        """Detect a foreign SECRET_CANARY by exact match *or* credential shape.

        The engineering spec (section 6.3) gives SECRET_CANARY an "exact + format
        detector" path distinct from HARD_CANARY's plain exact scan. A foreign
        secret is confirmed when its plaintext appears as a normalized substring
        (parity with the exact path, so no foreign secret is ever missed) or when
        it is recovered as a credential-shaped token (``sk-`` / ``AKIA`` / SSN) -
        robust to a secret wrapped in surrounding bytes such as
        ``{"api_key": "<secret>"}``. Either branch requires a manifest marker, so
        the zero-false-positive invariant holds: a secret-shaped string that
        matches no foreign marker produces no finding.
        """
        findings: list[Finding] = []
        shaped = {
            normalize_for_match(match)
            for pattern in _SECRET_PATTERNS
            for match in pattern.findall(text)
        }
        for marker in self._foreign(observer, MarkerType.SECRET_CANARY):
            # The shared predicate for the "is it here" half, plus this tier's own
            # credential-shape branch. Spelling the arms out here meant the
            # projection arm added to `residual_present` reached the erasure scan
            # and not the detector, so a secret wrapped INSIDE its key body read as
            # absent on the path whose whole job is to find it.
            needle = normalize_for_match(marker.plaintext)
            if residual_present(marker.plaintext, text) or (needle and needle in shaped):
                findings.append(
                    self._finding(
                        marker,
                        observer,
                        surface,
                        probe_id,
                        severity=Severity.CRITICAL,
                        confidence=1.0,
                        status=FindingStatus.CONFIRMED,
                        # A confirmed secret leak never carries the verbatim
                        # credential into the evidence artifact (the spec, §16).
                        evidence=redact_secret(marker.plaintext),
                    )
                )
        return findings

    def _semantic(
        self, observer: Principal, text: str, surface: Surface, probe_id: str
    ) -> list[Finding]:
        findings: list[Finding] = []
        observation_tokens = tokenize(text)
        # One window->vector cache for the whole observation: every entity marker
        # tokenizes to the same window size, so without this each distinct window
        # is re-embedded once per foreign marker (~Nx the HTTP calls on a real
        # embedder). The cache makes each window embed exactly once per observation.
        window_cache: dict[str, tuple[float, ...]] = {}
        for marker in self._foreign(observer, MarkerType.ENTITY_CANARY):
            # A foreign entity whose plaintext is literally present is a leak by
            # observation, not a judgement: the text contains another principal's
            # canary. `_exact` applies exactly this standard to HARD_CANARY, but it
            # does not cover ENTITY_CANARY, so a verbatim entity reached the judge
            # alone - and a judge answering "no" (a cautious, flaky, or hostile
            # model) silently downgraded a real cross-tenant leak to a candidate.
            # The threshold could also skip it before the judge ever saw it.
            # The shared predicate, like the two tiers above: the entity with its
            # separator changed ("Quasar7K2Q 00001" for "Quasar7K2Q-00001") is the
            # same text to a reader, and reached the judge alone - where a cautious
            # "no" downgraded it - while the fake judge confirmed it. An entity has
            # no 16-character opaque token, so the projection arm never fires here
            # and this tier keeps exactly the two arms it had.
            verbatim = residual_present(marker.plaintext, text)
            # CONFIRMATION and CONFIDENCE are different claims, and one predicate
            # was answering both. `residual_present`'s token arm is CONTIGUOUS,
            # while this module's own bar for "the text carries that marker" is
            # `_MAX_INTERPOSED_TOKENS` - the bar `FakeJudge` and `_span_traceable`
            # branch 1 both use to confirm. So the canonical leak this file
            # documents at the top, "Project (internal) Onyx-00002", failed the
            # bypass written for exactly it: with a real judge that declines - the
            # cautious, flaky or hostile model the bypass defends against - a
            # foreign entity plainly present was recorded UNVERIFIED and dropped
            # out of `confirmed_findings` and the headline.
            #
            # Kept separate from `verbatim` rather than widening it: `verbatim`
            # also sets confidence to 1.0, and a paraphrase is not certainty. One
            # interposed token is enough to say the leak is THERE; it is not
            # enough to call the match exact in a signed field.
            present = verbatim or ordered_within_span(
                observation_tokens, tokenize(marker.plaintext), _MAX_INTERPOSED_TOKENS
            )
            similarity = self._best_window_similarity(observation_tokens, marker, window_cache)
            # The threshold gates which *semantic* candidates reach the judge. With
            # the deterministic fake providers the judge (a full marker-phrase
            # match) is the binding test; the threshold becomes the real
            # calibration knob once a production embedding model is configured. A
            # verbatim match is never gated by it.
            if not present and similarity < self._threshold:
                continue
            leak = self._judge.judge(text, marker)
            # FP-control backstop (the engineering spec, section 6.4): a judge
            # "yes" alone never confirms. The cited evidence span (or, when the
            # judge cites none, the marker plaintext) must be token-order
            # traceable in the observation - the same anti-fabrication test the
            # fake judge applies, enforced here for EVERY judge. A real LLM
            # judge is primed with the marker plaintext, so a parroting or
            # hallucinating verdict would otherwise put a fabricated CONFIRMED
            # finding (and a fabricated quoted span) into the signed audit pack.
            judged = leak.leak and self._span_traceable(
                text, leak.evidence_span, marker, self._entity_boilerplate
            )
            confirmed = present or judged
            # `_span_traceable` also confirms via the MARKER being present
            # (branch 1), whatever the judge quoted - so it cannot decide what to
            # QUOTE: a judge affirming a verbatim leak while citing a fabricated
            # span would put that fabrication in the signed pack. Asking only
            # whether the span is SOMEWHERE in the observation was not enough
            # either: an unrelated in-observation sentence passes that, and became
            # the quoted proof of the leak. A span is quotable only when it also
            # ties to this marker - branch 2's distinctive-token test.
            # Containment is asked HERE, not inside `_span_ties_to_marker`, because
            # that predicate has a second caller: `_span_traceable`'s branch 2,
            # which decides CONFIRMATION. Tightening the shared predicate made a
            # judge that re-cased its quotation - or an observation carrying a
            # newline or a zero-width split - fail branch 2, so a genuine
            # cross-tenant leak was DOWNGRADED from confirmed/high to
            # unverified/info: a missed leak, introduced while fixing an
            # over-claim about quoting. The two questions are separate. Whether
            # the marker is PRESENT must stay normalization-insensitive; whether
            # this exact text may be put in quotation marks is byte-exact.
            quotable = (
                bool(leak.evidence_span)
                and leak.evidence_span in text
                and self._span_ties_to_marker(
                    text, leak.evidence_span, marker, self._entity_boilerplate
                )
            )
            if confirmed:
                # The audit pack renders this span (the PDF renderer), so a
                # confirmed leak always shows the auditor text that was really
                # observed: the judge's quotation when it is genuinely there
                # (richer context), otherwise the marker plaintext.
                #
                # Except where the plaintext ISN'T there. `present` confirms a
                # marker whose tokens appear in order with one interposed word, so
                # for "Project (internal) Onyx-00002" the plaintext "Project
                # Onyx-00002" is not a substring of the observation - and quoting
                # it puts a phrase in the signed pack that the run never saw,
                # which is the defect `quotable` was just narrowed to prevent, one
                # branch over. Recovering the real substring would need token
                # offsets `tokenize` does not carry, so this says what was matched
                # instead of showing something that was not.
                if judged and quotable:
                    evidence = leak.evidence_span
                elif verbatim:
                    evidence = marker.plaintext
                else:
                    evidence = (
                        f"the foreign marker {marker.plaintext!r} appears in the "
                        "observation with an interposed word, so it is present but not "
                        "a verbatim substring"
                    )
            elif leak.leak:
                evidence = (
                    "judge affirmed a leak but its cited evidence is not traceable "
                    f"in the observation; downgraded to a candidate: {leak.rationale}"
                )
            else:
                evidence = leak.rationale
            findings.append(
                self._finding(
                    marker,
                    observer,
                    surface,
                    probe_id,
                    severity=Severity.HIGH if confirmed else Severity.INFO,
                    # A verbatim match is certain, exactly as `_exact` reports 1.0
                    # for a hard canary; a semantic match reports its true
                    # similarity. Clamp defensively: a true cosine is already
                    # <= 1.0, but float rounding can nudge it just past 1.0, which
                    # would violate Finding.confidence's 0..1 bound.
                    confidence=1.0 if verbatim else round(min(1.0, similarity), 4),
                    status=FindingStatus.CONFIRMED if confirmed else FindingStatus.UNVERIFIED,
                    evidence=evidence,
                )
            )
        return findings

    @staticmethod
    def _span_traceable(
        text: str,
        evidence_span: str,
        marker: Marker,
        boilerplate: frozenset[str] = frozenset(),
    ) -> bool:
        """Whether a judge "yes" is tied back to *this* marker in the observation.

        The spec 6.4 FP-control requires the leak to trace to the manifest marker -
        not merely to some phrase the judge happened to quote. A judge "yes"
        confirms only when one of two holds:

        1. the marker plaintext itself is token-order-traceable in the observation
           (a verbatim / re-cased / NFKC-mangled leak of the entity); or
        2. the judge's cited ``evidence_span`` is traceable in the observation AND
           shares a *distinctive* token with the marker - one not in ``boilerplate``
           (the template words like "project" that every entity canary repeats).
           A genuine paraphrase of a distinctive canary reproduces a distinctive
           token (the codename, the id), which ties the cited evidence to this
           marker; a span overlapping only on boilerplate does not.

        So a judge that affirms a leak but cites an in-observation phrase unrelated
        to the marker - or related only via the shared template word - does NOT
        confirm; the finding stays UNVERIFIED. The deterministic fake judge cites
        the marker plaintext, so it always confirms via (1).
        """
        text_tokens = tokenize(text)
        marker_tokens = tokenize(marker.plaintext)
        marker_present = bool(marker_tokens) and ordered_within_span(
            text_tokens, marker_tokens, _MAX_INTERPOSED_TOKENS
        )
        if marker_present:
            return True
        return DetectionPipeline._span_ties_to_marker(text, evidence_span, marker, boilerplate)

    @staticmethod
    def _span_ties_to_marker(
        text: str,
        evidence_span: str,
        marker: Marker,
        boilerplate: frozenset[str] = frozenset(),
    ) -> bool:
        """Branch 2 alone: the cited span is in the observation AND ties to ``marker``.

        Separated from :meth:`_span_traceable` because the two questions diverge.
        `_span_traceable` answers "does this judge verdict confirm", and branch 1
        says yes on the MARKER being present, whatever the judge quoted - so it
        cannot decide what to QUOTE. Asking only "is the span somewhere in the
        text" let a judge affirming a genuine verbatim leak put an unrelated
        in-observation sentence into the signed pack as the proof of it: a
        CONFIRMED cross-tenant leak of `Project Onyx-00002` evidenced by "the
        quarterly roadmap was also reviewed", sharing no token with the marker,
        in the field the PDF renderer's own docstring calls "the proof".
        """
        text_tokens = tokenize(text)
        marker_tokens = tokenize(marker.plaintext)
        span_tokens = tokenize(evidence_span)
        # A pure-digit token (the canary's serial, e.g. "00002") is low-entropy and
        # collides with everyday numbers (invoice / ticket / lot), so it can never
        # on its own tie a span to a marker - drop it from the distinctive set. The
        # alphabetic codename remains the load-bearing distinctive evidence.
        distinctive_overlap = {
            token
            for token in (set(span_tokens) & set(marker_tokens)) - boilerplate
            if not token.isdigit()
        }
        if not (span_tokens and distinctive_overlap):
            return False
        # Deliberately token-order, NOT raw containment. This predicate also backs
        # `_span_traceable`'s branch 2, which decides CONFIRMATION, and `spec/text.py`
        # states why a raw `in` is wrong for that question: a backend that re-cased,
        # NFKC-normalized or zero-width-split a canary slips past it. Whether a span
        # may be QUOTED is asked at the `quotable` call site instead.
        return ordered_within_span(text_tokens, span_tokens, _MAX_INTERPOSED_TOKENS)

    def _best_window_similarity(
        self,
        observation_tokens: list[str],
        marker: Marker,
        window_cache: dict[str, tuple[float, ...]] | None = None,
    ) -> float:
        """Return the max cosine between ``marker`` and any observation window.

        Comparing against windows the size of the marker keeps the score robust
        to observation length: a marker surfaced anywhere in a long response
        still scores highly, where a whole-text cosine would be diluted.

        ``window_cache`` (optional) memoizes window-text -> embedding across the
        markers of one observation, so each distinct window embeds at most once
        per observation rather than once per marker (a real embedder makes one
        HTTP call per embed).
        """
        # Read the marker's vector from the store keyed by its manifest
        # embedding_ref (the spec, section 6.3) when present, else fall back to
        # the per-marker cache (an older manifest carries no ref).
        if marker.embedding_ref is not None and marker.embedding_ref in self._stored_vectors:
            marker_vector = self._stored_vectors[marker.embedding_ref]
        else:
            marker_vector = self._entity_vectors[marker.marker_id]
        window_size = len(tokenize(marker.plaintext))
        best = 0.0
        for window in _token_windows(observation_tokens, window_size):
            window_text = " ".join(window)
            if window_cache is not None and window_text in window_cache:
                window_vector = window_cache[window_text]
            else:
                window_vector = self._embedder.embed(window_text)
                if window_cache is not None:
                    window_cache[window_text] = window_vector
            best = max(best, _cosine(window_vector, marker_vector))
        return best

    def _finding(
        self,
        marker: Marker,
        observer: Principal,
        surface: Surface,
        probe_id: str,
        *,
        severity: Severity,
        confidence: float,
        status: FindingStatus,
        evidence: str,
    ) -> Finding:
        # A user-level observer adds a user segment, so the same marker reaching
        # two users of one tenant is two distinct findings; a tenant-level
        # observer has no user segment. Full hex (not a truncation) so two
        # principals never collide - dedupe_findings must not merge real leaks.
        user_suffix = f"-{observer.user_id.hex}" if observer.user_id is not None else ""
        return Finding(
            # Keyed by probe, marker, observer, AND surface: the same marker
            # reaching the same principal on two surfaces (say a vector store and
            # a model adapter) is two distinct leaks, while repeated detections on
            # one surface within one probe collapse under dedupe_findings.
            finding_id=(
                f"finding-{probe_id}-{marker.marker_id}-"
                f"{observer.tenant_id.hex}{user_suffix}-{surface.value}"
            ),
            probe_id=probe_id,
            severity=severity,
            confidence=confidence,
            status=status,
            owner_tenant_id=marker.owner_tenant_id,
            observed_in_tenant_id=observer.tenant_id,
            owner_user_id=marker.owner_user_id,
            observed_in_user_id=observer.user_id,
            surface=surface,
            marker_id=marker.marker_id,
            evidence_span=evidence,
            # Required-field default only: detect() re-stamps owasp_llm/atlas/nist
            # on every finding via model_copy, centralizing control-ID tagging in
            # one place for both _exact and _semantic. This value never ships.
            owasp_llm=_OWASP_MULTI_TENANT,
        )
