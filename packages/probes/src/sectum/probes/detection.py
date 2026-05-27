"""The exact then semantic then judge leak-detection pipeline (the engineering spec, section 6.4).

A leak is a marker owned by tenant X observed in tenant Y's session. Detection
runs cheapest-and-most-certain first:

1. Exact scan for HARD_CANARY and SECRET_CANARY plaintext: a cross-tenant hit is
   a confirmed critical leak (confidence 1.0).
2. Semantic similarity against foreign ENTITY_CANARY markers yields candidates.
3. A calibrated judge adjudicates each candidate.

Zero false positives by construction: every finding is tied to a manifest
marker, and a finding is only ``CONFIRMED`` on an exact hit or a positive judge
verdict. Text containing no manifest marker can never produce a confirmed
finding (the engineering spec, section 6.4; tested as an invariant).
"""

import hashlib
import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sectum.spec import (
    Finding,
    FindingStatus,
    Marker,
    MarkerType,
    Principal,
    Severity,
    Substrate,
    Surface,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_OWASP_MULTI_TENANT = "LLM08:2025"


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


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
    providers (see ``sectum.probes.providers``) by passing this bundle through to
    each probe. A probe given no bundle behaves exactly as before.
    """

    embedder: "EmbeddingProvider | None" = None
    judge: "Judge | None" = None
    semantic_threshold: float = 0.62

    def pipeline(self, substrate: Substrate) -> "DetectionPipeline":
        """Build a detection pipeline for ``substrate`` with these providers."""
        return DetectionPipeline(substrate, self.embedder, self.judge, self.semantic_threshold)


class DetectingProbe:
    """Base for probes that run the detection pipeline.

    It carries the detection providers so a configured run threads a real
    embedder and judge through to every probe's detection; constructed with no
    argument it uses the deterministic fakes, so existing behavior is unchanged.
    Subclasses call ``self._providers.pipeline(substrate)`` in ``detect``.
    """

    def __init__(self, providers: DetectionProviders | None = None) -> None:
        self._providers = providers if providers is not None else DetectionProviders()


class FakeEmbeddingProvider:
    """Deterministic hashing-trick embedding for tests and offline runs.

    Not semantically meaningful beyond lexical overlap, but fully deterministic:
    identical text always embeds identically, and texts sharing tokens have
    non-zero cosine similarity.
    """

    dim = 96

    def embed(self, text: str) -> tuple[float, ...]:
        """Return a unit-normalized hashing-trick vector for ``text``."""
        vector = [0.0] * self.dim
        for token in _tokenize(text):
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
        """Return a leak verdict based on marker-token coverage of the text."""
        marker_tokens = set(_tokenize(marker.plaintext))
        if not marker_tokens:
            return JudgeVerdict(leak=False, rationale="empty marker", evidence_span="")
        overlap = marker_tokens & set(_tokenize(observed_text))
        ratio = len(overlap) / len(marker_tokens)
        if ratio >= 1.0:
            # On a confirmed leak the fake judge cites the marker plaintext as
            # the evidence span - the same slice the audit-pack PDF quotes.
            return JudgeVerdict(
                leak=True,
                rationale="all marker tokens present in observation",
                evidence_span=marker.plaintext,
            )
        return JudgeVerdict(
            leak=False,
            rationale=f"insufficient marker overlap ({ratio:.2f})",
            evidence_span="",
        )


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(left, right, strict=True))


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


def dedupe_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Collapse findings that share a finding id, keeping the first occurrence.

    The same cross-tenant leak - a marker observed in a tenant - can be detected
    by more than one probe step: a confused-deputy and a token-passthrough
    lookup that both resolve the same resource, or repeated adapter recalls.
    Each detection builds an identical Finding; the run record keeps one.
    """
    seen: set[str] = set()
    unique: list[Finding] = []
    for finding in findings:
        if finding.finding_id in seen:
            continue
        seen.add(finding.finding_id)
        unique.append(finding)
    return unique


class DetectionPipeline:
    """Applies exact then semantic then judge detection against a substrate."""

    def __init__(
        self,
        substrate: Substrate,
        embedder: EmbeddingProvider | None = None,
        judge: Judge | None = None,
        semantic_threshold: float = 0.62,
    ) -> None:
        self._markers: tuple[Marker, ...] = substrate.manifest.markers
        self._embedder: EmbeddingProvider = embedder or FakeEmbeddingProvider()
        self._judge: Judge = judge or FakeJudge()
        self._threshold = semantic_threshold
        self._entity_vectors: dict[str, tuple[float, ...]] = {
            marker.marker_id: self._embedder.embed(marker.plaintext)
            for marker in self._markers
            if marker.marker_type is MarkerType.ENTITY_CANARY
        }

    def detect(
        self,
        observed_in_tenant: UUID,
        observation_text: str,
        surface: Surface,
        probe_id: str = "manual",
        *,
        observed_user: UUID | None = None,
        owasp_llm: str = _OWASP_MULTI_TENANT,
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
        findings.extend(self._semantic(observer, observation_text, surface, probe_id))
        return [
            finding.model_copy(update={"owasp_llm": owasp_llm, "atlas": atlas, "nist": nist})
            for finding in findings
        ]

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
        for marker_type in (MarkerType.HARD_CANARY, MarkerType.SECRET_CANARY):
            for marker in self._foreign(observer, marker_type):
                if marker.plaintext in text:
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

    def _semantic(
        self, observer: Principal, text: str, surface: Surface, probe_id: str
    ) -> list[Finding]:
        findings: list[Finding] = []
        observation_tokens = _tokenize(text)
        for marker in self._foreign(observer, MarkerType.ENTITY_CANARY):
            similarity = self._best_window_similarity(observation_tokens, marker)
            # The threshold gates which candidates reach the judge. With the
            # deterministic fake providers the judge (a full marker-phrase
            # match) is the binding test; the threshold becomes the real
            # calibration knob once a production embedding model is configured.
            if similarity < self._threshold:
                continue
            leak = self._judge.judge(text, marker)
            # The judge may quote a verbatim span from the observation - the
            # audit pack renders that span (the engineering spec, section 6.4
            # and the PDF renderer). Fall back to the marker plaintext when the
            # judge declines, so a confirmed leak always shows the foreign
            # entity to the auditor and an unverified candidate carries the
            # judge's rationale instead.
            evidence = (leak.evidence_span or marker.plaintext) if leak.leak else leak.rationale
            findings.append(
                self._finding(
                    marker,
                    observer,
                    surface,
                    probe_id,
                    severity=Severity.HIGH if leak.leak else Severity.INFO,
                    confidence=round(similarity, 4),
                    status=FindingStatus.CONFIRMED if leak.leak else FindingStatus.UNVERIFIED,
                    evidence=evidence,
                )
            )
        return findings

    def _best_window_similarity(self, observation_tokens: list[str], marker: Marker) -> float:
        """Return the max cosine between ``marker`` and any observation window.

        Comparing against windows the size of the marker keeps the score robust
        to observation length: a marker surfaced anywhere in a long response
        still scores highly, where a whole-text cosine would be diluted.
        """
        marker_vector = self._entity_vectors[marker.marker_id]
        window_size = len(_tokenize(marker.plaintext))
        best = 0.0
        for window in _token_windows(observation_tokens, window_size):
            best = max(best, _cosine(self._embedder.embed(" ".join(window)), marker_vector))
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
            # Keyed by probe as well as marker and observer: the same marker
            # reaching the same principal on two surfaces (say a vector store and
            # a model adapter) is two distinct findings, while repeated detections
            # within one probe collapse under dedupe_findings.
            finding_id=(
                f"finding-{probe_id}-{marker.marker_id}-{observer.tenant_id.hex}{user_suffix}"
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
            owasp_llm=_OWASP_MULTI_TENANT,
        )
