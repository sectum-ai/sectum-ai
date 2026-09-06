"""Principled per-embedding-model semantic-threshold calibration (the spec, section 6.4).

The semantic gate (:class:`~sectum_ai.probes.detection.DetectionPipeline`) admits an
observation to the LLM judge when its cosine similarity to a foreign ENTITY_CANARY
clears ``semantic_threshold``. That threshold is per-embedding-model: a stronger
model packs unrelated text closer together, so a gate tuned for the offline fake
floods a real model's judge with candidates (on one real run
``text-embedding-3-small`` needed ~0.80, not the 0.62 default).

This module makes the choice principled instead of hand-picked. From a seeded
substrate it builds a *labeled* similarity set:

- **positives** - a foreign tenant's ENTITY_CANARY genuinely surfaced into another
  tenant's session (a true cross-tenant leak the gate should admit);
- **negatives** - same-tenant text carrying the entity (not a cross-tenant leak),
  and unrelated foreign-tenant text built from the shared organic entities (the
  leakage bait) that must *not* trip the gate.

Each observation is scored with
:meth:`~sectum_ai.probes.detection.DetectionPipeline.best_foreign_similarity` - the
exact value the gate thresholds on - so the recommendation is provably consistent
with detection. It then sweeps candidate thresholds and recommends the one that
maximises F1 **subject to zero false positives among the negatives**: the
zero-false-positive property is non-negotiable for a verification product (the
spec, sections 1.3 and 6.4), so a threshold that admits any negative is never
recommended. The harness is deterministic: the same seed yields the same labeled
set and the same recommendation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from sectum_ai.probes.detection import (
    DEFAULT_SEMANTIC_THRESHOLD,
    DetectionPipeline,
    EmbeddingProvider,
    Judge,
)
from sectum_ai.spec import Marker, MarkerType, Substrate

__all__ = [
    "CalibrationExample",
    "CalibrationResult",
    "ThresholdScore",
    "calibrate_threshold",
]

# Realistic retrieved-context wrappers around an entity plaintext - the bait
# surfaces inside a chunk a RAG pipeline would return, never as a bare token, so
# the calibration reflects how a leak actually appears in an observation.
_LEAK_TEMPLATES: tuple[str, ...] = (
    "retrieved context: the account note references {entity} for the current quarter.",
    "internal record: deliverables for {entity} were reviewed by the project team.",
    "support ticket excerpt: the customer asked about the status of {entity}.",
)

# Foreign-tenant context that must NOT trip the gate: it talks about the shared
# organic entities (the deliberate leakage bait - shared people, vendors,
# compliance terms, amounts, dates) without naming any tenant's private entity.
# A near-miss negative ("Project ... initiative", "the project board") shares
# common words with the entity codename without being it.
_UNRELATED_TEMPLATES: tuple[str, ...] = (
    "retrieved context: the {entity} engagement covered the standard compliance scope.",
    "meeting note: the team reviewed the project board and the quarterly roadmap.",
    "support ticket: the customer asked about onboarding timelines and pricing tiers.",
)


@dataclass(frozen=True)
class CalibrationExample:
    """One scored observation in the labeled calibration set.

    ``similarity`` is the max cosine of the observation to any foreign
    ENTITY_CANARY (the exact value the semantic gate thresholds on);
    ``is_positive`` marks a genuine cross-tenant leak.
    """

    is_positive: bool
    similarity: float
    label: str


@dataclass(frozen=True)
class ThresholdScore:
    """Precision, recall, and F1 of a candidate threshold over the labeled set."""

    threshold: float
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def zero_false_positive(self) -> bool:
        """Whether this threshold admits no negative example (the hard constraint)."""
        return self.false_positives == 0


@dataclass(frozen=True)
class CalibrationResult:
    """The outcome of a calibration run for one embedding model."""

    model_name: str
    recommended_threshold: float
    examples: tuple[CalibrationExample, ...]
    scores: tuple[ThresholdScore, ...]
    recommended_score: ThresholdScore | None
    # What the shipped default scores on THIS run's labeled set, when no
    # threshold separated the classes. ``None`` when a real recommendation exists.
    fallback_score: ThresholdScore | None = None

    @property
    def positives(self) -> int:
        """Number of genuine cross-tenant leak examples."""
        return sum(1 for example in self.examples if example.is_positive)

    @property
    def negatives(self) -> int:
        """Number of must-not-trip examples (same-tenant and unrelated)."""
        return sum(1 for example in self.examples if not example.is_positive)


def _foreign_entity_markers(substrate: Substrate) -> list[Marker]:
    """Every ENTITY_CANARY in the substrate, in manifest order (each is foreign to others)."""
    return [
        marker
        for marker in substrate.manifest.markers
        if marker.marker_type is MarkerType.ENTITY_CANARY
    ]


def _other_tenant(substrate: Substrate, owner_index: int) -> int:
    """Index of a tenant other than ``owner_index`` (the next one, wrapping)."""
    return (owner_index + 1) % len(substrate.tenants)


def build_calibration_set(
    substrate: Substrate,
    pipeline: DetectionPipeline,
) -> list[CalibrationExample]:
    """Build the deterministic labeled similarity set for ``substrate``.

    For each ENTITY_CANARY owned by tenant X this emits:

    - a *positive* per leak template: the entity surfaced into a different tenant
      Y's session (a true cross-tenant leak the gate should admit);
    - a same-tenant *negative*: the entity in its own tenant's session. This is
      not a cross-tenant leak of *that* entity, but it still scores non-zero
      against the *other* tenants' entities, which share the ``Project`` prefix -
      exactly the near-miss false-positive pressure the gate must resist;
    - an unrelated *negative* per unrelated template: foreign-tenant text built
      from the shared organic bait that names no private entity.

    Every observation is scored with
    :meth:`DetectionPipeline.best_foreign_similarity` from the *observer's*
    perspective, so the score is exactly what the gate would compute. Requires at
    least two tenants (cross-tenant needs a distinct foreign observer); a
    single-tenant substrate yields an empty set.
    """
    examples: list[CalibrationExample] = []
    if len(substrate.tenants) < 2:
        return examples
    tenant_index = {tenant.tenant_id: index for index, tenant in enumerate(substrate.tenants)}
    for marker in _foreign_entity_markers(substrate):
        owner_index = tenant_index[marker.owner_tenant_id]
        owner = substrate.tenants[owner_index].tenant_id
        observer = substrate.tenants[_other_tenant(substrate, owner_index)].tenant_id
        for template in _LEAK_TEMPLATES:
            text = template.format(entity=marker.plaintext)
            examples.append(
                CalibrationExample(
                    is_positive=True,
                    similarity=pipeline.best_foreign_similarity(observer, text),
                    label=f"leak {marker.marker_id} -> {observer.hex[:8]}",
                )
            )
        # Same-tenant: the entity in its owner's own session is not a cross-tenant
        # leak of THIS entity, so it is a negative - though it still scores against
        # other tenants' "Project ..." entities, which is the near-miss the gate
        # must hold the line on.
        same_tenant_text = _LEAK_TEMPLATES[0].format(entity=marker.plaintext)
        examples.append(
            CalibrationExample(
                is_positive=False,
                similarity=pipeline.best_foreign_similarity(owner, same_tenant_text),
                label=f"same-tenant {marker.marker_id}",
            )
        )
        for template in _UNRELATED_TEMPLATES:
            # The unrelated text borrows the entity's distinctive prefix - codename
            # plus its fused entropy, minus the serial - as a near miss without the
            # full entity (e.g. "Project Quasar7K2Q engagement"), so the negative is
            # adversarial, not trivially dissimilar.
            entity_prefix = marker.plaintext.split("-")[0]
            text = template.format(entity=entity_prefix)
            examples.append(
                CalibrationExample(
                    is_positive=False,
                    similarity=pipeline.best_foreign_similarity(observer, text),
                    label=f"unrelated {marker.marker_id} -> {observer.hex[:8]}",
                )
            )
    return examples


def _score_at(threshold: float, examples: Sequence[CalibrationExample]) -> ThresholdScore:
    """Precision/recall/F1 of admitting every example with ``similarity >= threshold``."""
    true_positives = 0
    false_positives = 0
    false_negatives = 0
    for example in examples:
        admitted = example.similarity >= threshold
        if example.is_positive and admitted:
            true_positives += 1
        elif example.is_positive and not admitted:
            false_negatives += 1
        elif not example.is_positive and admitted:
            false_positives += 1
    predicted_positive = true_positives + false_positives
    actual_positive = true_positives + false_negatives
    precision = true_positives / predicted_positive if predicted_positive else 0.0
    recall = true_positives / actual_positive if actual_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return ThresholdScore(
        # The threshold is stored at FULL precision: this is the value the CLI
        # publishes as the recommendation, and rounding it (e.g. to 4dp) could
        # move the gate below a negative example's similarity that this very
        # sweep certified as excluded - silently breaking the zero-FP promise.
        # Rounding is a render-time concern (the text table formats %.4f).
        threshold=threshold,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


def _candidate_thresholds(examples: Sequence[CalibrationExample]) -> list[float]:
    """Candidate thresholds: midpoints between adjacent distinct observed scores.

    Classification only changes at an observed score boundary, so evaluating the
    midpoints between sorted distinct scores (plus a point just above the max, to
    represent admitting nothing) covers every distinct precision/recall trade-off
    without an arbitrary fixed grid. The list is ascending and deterministic.
    """
    scores = sorted({round(example.similarity, 6) for example in examples})
    if not scores:
        return [DEFAULT_SEMANTIC_THRESHOLD]
    candidates: list[float] = []
    # A threshold just below the smallest score admits everything; include it so
    # the sweep records the all-admit (max-recall) operating point too.
    candidates.append(max(0.0, scores[0] - 1e-6))
    for lower, upper in pairwise(scores):
        candidates.append((lower + upper) / 2)
    candidates.append(scores[-1] + 1e-6)
    return candidates


def _recommend(scores: Sequence[ThresholdScore]) -> ThresholdScore | None:
    """Pick the max-F1 threshold among those admitting no negative (zero-FP constraint).

    The zero-false-positive constraint is hard (the spec, sections 1.3 and 6.4):
    only thresholds with ``false_positives == 0`` are eligible. Among them the one
    with the highest F1 wins; ties break toward the *lower* threshold (more recall
    headroom), then the higher recall. Returns ``None`` when no threshold both
    admits a positive and excludes every negative.
    """
    eligible = [score for score in scores if score.zero_false_positive and score.true_positives > 0]
    if not eligible:
        return None
    return max(eligible, key=lambda score: (score.f1, -score.threshold, score.recall))


def calibrate_threshold(
    substrate: Substrate,
    *,
    model_name: str,
    embedder: EmbeddingProvider | None = None,
    judge: Judge | None = None,
) -> CalibrationResult:
    """Calibrate the semantic threshold for ``embedder`` on ``substrate``.

    Builds the labeled set (positives = genuine cross-tenant entity leaks;
    negatives = same-tenant and unrelated text), scores every candidate threshold,
    and recommends the F1-maximising one that admits no negative (the zero-FP
    constraint). When no threshold separates the classes cleanly - for example the
    deterministic fake embedder, whose lexical overlap can score a near-miss
    negative as high as a leak - it falls back to
    :data:`~sectum_ai.probes.detection.DEFAULT_SEMANTIC_THRESHOLD` (recorded in the
    result as ``recommended_score is None``), never a threshold that admits a
    negative.

    ``model_name`` is the canonical embedder name (``st:<model>`` / ``openai:<model>``)
    the result is labeled with - the key under which it can be added to
    :data:`~sectum_ai.probes.detection.MODEL_THRESHOLDS`. The ``judge`` does not
    affect the recommendation (calibration is about the gate, upstream of the
    judge) but is accepted so a caller can pass the same providers it runs with.
    """
    pipeline = DetectionPipeline(substrate, embedder, judge)
    examples = build_calibration_set(substrate, pipeline)
    scores = tuple(_score_at(threshold, examples) for threshold in _candidate_thresholds(examples))
    recommended = _recommend(scores)
    # The fallback is the shipped default, not a measurement: score it on this
    # run's own labeled set so the caller is told what it admits. Published
    # unscored, it was printed as "the conservative default" while admitting 25
    # of 32 negatives - and it gates which candidates become CONFIRMED findings.
    fallback_score = (
        None if recommended is not None else _score_at(DEFAULT_SEMANTIC_THRESHOLD, examples)
    )
    recommended_threshold = (
        recommended.threshold if recommended is not None else DEFAULT_SEMANTIC_THRESHOLD
    )
    return CalibrationResult(
        model_name=model_name,
        recommended_threshold=recommended_threshold,
        examples=tuple(examples),
        scores=scores,
        recommended_score=recommended,
        fallback_score=fallback_score,
    )
