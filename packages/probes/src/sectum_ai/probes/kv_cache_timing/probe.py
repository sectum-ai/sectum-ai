"""Class 5 - KV-cache timing side channel (the engineering spec, section 7).

Shared inference infrastructure with a KV prefix cache returns a prompt faster
when its prefix was recently processed. The probe warms the cache as one tenant,
then, as another tenant, measures the latency of prompts that do and do not
share that prefix. A statistically large timing gap is a side channel: the
second tenant can tell what the first tenant recently asked.

Class 5 is a statistical workflow rather than a plan/detect probe, so - like the
Class 11 erasure probe - it exposes its own ``run`` entry point. Per the spec's
"avoid over-claiming" requirement, a finding is reported only when the timing gap
is *both* statistically significant (a two-sided Welch's t-test below a
Bonferroni-corrected level - ``_ALPHA`` divided by the number of tenant-pair
comparisons, so the family-wise false-positive rate across all pairs stays at
``_ALPHA``) *and* practically large (Cohen's d above ``_EFFECT_THRESHOLD``), in
the expected direction (the primed prompt is faster). Each finding carries the
p-value, the corrected level, and a confidence interval on the gap so an auditor
can judge the strength of evidence.

The statistics are pure standard library: the Student's t survival function is
the regularized incomplete beta function (a Numerical Recipes continued
fraction), and the confidence-interval critical value is found by bisection - no
SciPy/NumPy dependency (the spec, section 13: dependency discipline).
"""

import hashlib
import math
import random
import statistics
from dataclasses import dataclass
from uuid import UUID

from sectum_ai.adapters import ModelAdapter
from sectum_ai.spec import Finding, FindingStatus, Severity, Substrate, Surface

# Trials per condition. Enough samples that the jitter noise floor is stable and
# the t-test has ample degrees of freedom. Must stay EVEN: `_measure` alternates
# which arm it times first, and only an even count leaves the two arms with equal
# mean measurement positions, which is what makes a linear drift cancel exactly.
_TRIALS = 24
# No latency is measured finer than the clock: variances are floored at the
# square of a 1 us resolution (perf_counter's is tens of ns), in ms. A jitter-free
# backend used to yield zero spread, an infinite t with zero degrees of freedom,
# p = 1.0, and Cohen's d = 0 - so a perfect, constant 60 ms side channel produced
# no finding.
_RESOLUTION_MS = 1e-3
_VARIANCE_FLOOR = _RESOLUTION_MS**2
# A shared prefix long enough for a block-granular cache to hit. vLLM's automatic
# prefix caching hashes whole 16-token blocks and never caches a partial one, so
# a 20-character prefix (9-12 tokens) could not produce a single hit: the probe
# recorded Class 5 PASS against a backend with a shared cache. The first 20
# characters stay a unique key (what the built-in fake and the serving test
# doubles key on); the filler behind them spans several full blocks.
_PREFIX_FILLER = " ".join(["sectum prefix cache probe context"] * 24)
# Cohen's d: 0.8 is the conventional "large effect" boundary. A timing gap above
# it stands clear of the per-prompt jitter noise floor (practical significance).
_EFFECT_THRESHOLD = 0.8
_LARGE_EFFECT = 5.0
# Two-sided significance level for the Welch's t-test (statistical significance).
# Strict (1%) so a marginal gap is not reported as a confirmed side channel.
_ALPHA = 0.01
# Reported confidence-interval level for the mean timing gap.
_CI_LEVEL = 0.95


@dataclass(frozen=True)
class TimingSignal:
    """The measured timing side channel for one (owner, observer) tenant pair.

    ``effect_size`` is Cohen's d (practical significance); ``p_value`` is the
    two-sided Welch's t-test (statistical significance); ``ci_low_ms`` /
    ``ci_high_ms`` bound the mean timing gap (control minus primed) at
    ``_CI_LEVEL``. A genuine side channel has a large positive gap whose
    confidence interval excludes zero.
    """

    owner_tenant_id: UUID
    observed_in_tenant_id: UUID
    primed_mean_ms: float
    control_mean_ms: float
    mean_gap_ms: float
    effect_size: float
    t_statistic: float
    degrees_of_freedom: float
    p_value: float
    ci_low_ms: float
    ci_high_ms: float

    def is_significant_at(self, alpha: float) -> bool:
        """Whether the gap clears ``alpha`` and is practically large and directional.

        All three must hold to report a finding (the spec's "avoid over-claiming"):
        a p-value below ``alpha``, a large effect size, and the primed prompt
        being the faster one (a positive gap). ``run`` passes a Bonferroni-
        corrected ``alpha`` (the per-pair level divided by the number of tenant-
        pair comparisons) so the *family-wise* false-positive rate across every
        pair stays at ``_ALPHA``, rather than ``_ALPHA`` leaking once per pair.
        """
        return (
            self.p_value < alpha
            and self.effect_size >= _EFFECT_THRESHOLD
            and self.mean_gap_ms > 0.0
        )

    @property
    def significant(self) -> bool:
        """Per-pair significance at the uncorrected ``_ALPHA`` (no multiplicity correction).

        This judges a single pair in isolation; the run as a whole applies a
        Bonferroni correction across all pairs (see :meth:`is_significant_at`).
        """
        return self.is_significant_at(_ALPHA)


@dataclass(frozen=True)
class KvCacheTimingReport:
    """The result of a KV-cache timing run across every tenant pair."""

    signals: tuple[TimingSignal, ...]
    findings: tuple[Finding, ...]

    @property
    def effect_sizes(self) -> dict[str, float]:
        """Per-pair effect sizes, for ``RunMetrics.side_channel_effect_sizes``."""
        # Full hex so two tenant pairs cannot collide onto one map key.
        return {
            f"{signal.owner_tenant_id.hex}->{signal.observed_in_tenant_id.hex}": signal.effect_size
            for signal in self.signals
        }


def _cohens_d(slow: list[float], fast: list[float]) -> float:
    """Standardised mean difference (slow minus fast); 0 when the means agree."""
    pooled_variance = (statistics.pvariance(slow) + statistics.pvariance(fast)) / 2.0
    return (statistics.fmean(slow) - statistics.fmean(fast)) / math.sqrt(
        max(pooled_variance, _VARIANCE_FLOOR)
    )


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes betacf)."""
    max_iterations = 200
    epsilon = 3.0e-16
    tiny = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b) (Numerical Recipes betai)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(log_beta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _student_t_sf(t: float, df: float) -> float:
    """Two-sided tail probability of Student's t: P(|T| >= |t|) for ``df`` degrees of freedom.

    Uses the identity P(|T| >= |t|) = I_{df/(df+t^2)}(df/2, 1/2). Returns 1.0 at
    ``t == 0`` and approaches 0 as ``|t|`` grows.
    """
    if df <= 0.0:
        return 1.0
    return _betai(df / 2.0, 0.5, df / (df + t * t))


def _t_critical(df: float, level: float) -> float:
    """The two-sided t critical value: the ``t`` whose tail probability is ``1 - level``.

    Found by bisection on the monotonically-decreasing survival function, so no
    inverse-CDF table or third-party dependency is needed.
    """
    alpha = 1.0 - level
    low, high = 0.0, 1000.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if _student_t_sf(mid, df) > alpha:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _welch(slow: list[float], fast: list[float]) -> tuple[float, float, float]:
    """Welch's t-test of ``slow`` minus ``fast``: returns (t_statistic, df, std_error).

    Unequal-variance (Welch) form, so the two conditions need not share a
    variance. ``std_error`` is the standard error of the mean difference, reused
    for the confidence interval. A group's variance is floored at the timer's
    resolution, so a constant-latency backend yields a finite, large t rather
    than a degenerate one; only when neither group has two samples is the
    standard error zero (an infinite t with zero df, which the callers read as
    not significant).
    """
    n_slow, n_fast = len(slow), len(fast)
    var_slow = max(statistics.variance(slow), _VARIANCE_FLOOR) if n_slow > 1 else 0.0
    var_fast = max(statistics.variance(fast), _VARIANCE_FLOOR) if n_fast > 1 else 0.0
    term_slow = var_slow / n_slow
    term_fast = var_fast / n_fast
    std_error = math.sqrt(term_slow + term_fast)
    mean_diff = statistics.fmean(slow) - statistics.fmean(fast)
    if std_error == 0.0:
        # Degenerate: identical spreads. Distinguishable iff the means differ.
        return (math.inf if mean_diff else 0.0), 0.0, 0.0
    t_statistic = mean_diff / std_error
    # A group with n < 2 has no variance estimate (var_* is 0 there), so it
    # adds nothing to the Welch-Satterthwaite denominator; guarding the (n-1)
    # division avoids a ZeroDivisionError on an asymmetric (n=1, n>1) input.
    df_slow = (term_slow**2) / (n_slow - 1) if n_slow > 1 else 0.0
    df_fast = (term_fast**2) / (n_fast - 1) if n_fast > 1 else 0.0
    denominator = df_slow + df_fast
    df = (term_slow + term_fast) ** 2 / denominator if denominator > 0.0 else 0.0
    return t_statistic, df, std_error


def _key(tenant: UUID) -> str:
    return hashlib.sha256(tenant.bytes).hexdigest()[:8]


class KvCacheTimingProbe:
    """Class 5: a statistical timing test for a shared KV prefix cache."""

    id = "kv-cache-timing"
    name = "KV-cache timing side channel"
    owasp_llm = "LLM08:2025"
    owasp_secondary: tuple[str, ...] = ("LLM02:2025",)
    # A statistical timing side channel has no clean MITRE ATLAS technique, so
    # atlas is intentionally empty (the engineering spec, section 9).
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)

    def __init__(self, substrate: Substrate, *, model: ModelAdapter) -> None:
        self._substrate = substrate
        self._model = model

    def run(self) -> KvCacheTimingReport:
        """Warm the cache per tenant, then time prefix-sharing prompts from every other.

        Warm-up primes the owner's prefixes via ``ModelAdapter.infer`` while the
        measurement reads latency via ``measure_latency``; this assumes the
        adapter contract that both touch the *same* prefix cache (the fake and the
        HuggingFace adapter comply - HF's ``measure_latency_ms`` calls ``infer``).
        An adapter whose two paths use independent caches would show no signal.

        The owner warms one prefix per trial and each is measured exactly once,
        by one observer arm: on a backend whose latency call runs inference (HF),
        the observer's own trial 0 used to warm the single shared prefix - and the
        single control prefix - for every later trial, so both arms were cache
        hits from trial 1 and a real shared cache survived only in trial 0
        (d ~ 0.25, no finding). Now only the owner's warm-up can prime the primed
        arm, and the control arm is cold every trial. Each prefix opens with a
        20-character key (what the built-in fake and the serving test doubles key
        on) and continues with filler spanning several full 16-token blocks, so a
        block-granular cache (vLLM) can hit it too. The key is a hash of the
        tenant id, not its leading hex: two low-valued ids share those.
        """
        tenants = [tenant.tenant_id for tenant in self._substrate.tenants]
        signals: list[TimingSignal] = []
        findings: list[Finding] = []
        for owner in tenants:
            prefixes = [
                f"t{_key(owner)}-{trial:02d}-session {_PREFIX_FILLER}" for trial in range(_TRIALS)
            ]
            for prefix in prefixes:
                self._model.infer(owner, f"{prefix} context warm-up prompt")
            for observer in tenants:
                if observer == owner:
                    continue
                signals.append(self._measure(owner, observer, prefixes))
        # Bonferroni correction: a run performs one Welch's t-test per ordered
        # tenant pair, so judging each at _ALPHA would inflate the family-wise
        # false-positive rate (roughly comparisons * _ALPHA). Dividing the level
        # by the number of comparisons holds the run-wide rate at _ALPHA - a
        # conservative guard against reporting noise as a side channel.
        comparisons = max(1, len(tenants) * (len(tenants) - 1))
        alpha = _ALPHA / comparisons
        for signal in signals:
            if signal.is_significant_at(alpha):
                findings.append(self._finding(signal, alpha))
        return KvCacheTimingReport(signals=tuple(signals), findings=tuple(findings))

    def _measure(self, owner: UUID, observer: UUID, prefixes: list[str]) -> TimingSignal:
        # Interleave the two arms, alternating which is measured first, instead of
        # timing all primed trials and then all control trials.
        #
        # Block ordering confounded the comparison with anything that drifts during
        # the run - thermal throttling, CPU frequency scaling, a noisy neighbour, GC.
        # Every bit of that drift landed on whichever block ran second, and the
        # t-test read the resulting offset as a side channel. It is not a small
        # effect: against a model with NO prefix cache, so no channel to find, a
        # drift of 0.01 ms per call flagged all 12 tenant pairs, each with an
        # identical mean gap of 24 x 0.01 ms - the block-size artifact itself.
        # Manufacturing a cross-tenant finding out of ambient machine noise is the
        # worst direction for a signed evidence pack to be wrong in.
        #
        # Alternating makes the two arms' mean measurement positions equal, so a
        # linear drift cancels exactly rather than merely shrinking - which is why
        # _TRIALS must stay even. Higher-order drift (a GC pause mid-run) is damped,
        # not eliminated; the Bonferroni-corrected alpha and the effect-size floor
        # remain the guards against that.
        #
        # The order is SHUFFLED, not `trial % 2`. A fixed ABBA schedule puts each
        # arm on a fixed pair of residues mod 4 - primed at call indices {0,3},
        # control at {1,2} - so behind a 4-way round-robin dispatcher, where the
        # replica IS the call index mod 4, the two arms are pinned to disjoint
        # replica sets. A 5% spread across the pool, or one slow node in four, then
        # manufactured 12 CONFIRMED cross-tenant findings against a model with no
        # cache at all. A period-4 systematic is not damped by ABBA; it lands
        # entirely on one arm. The shuffle is seeded from the pair, so the run stays
        # reproducible, and stays balanced 12/12 so the mean-position argument above
        # still holds.
        primed: list[float] = []
        control: list[float] = []
        primed_first = [True] * (_TRIALS // 2) + [False] * (_TRIALS - _TRIALS // 2)
        random.Random(owner.bytes + observer.bytes).shuffle(primed_first)
        for trial in range(_TRIALS):
            primed_prompt = f"{prefixes[trial]} probe {trial}"
            # Unique per (owner, observer, trial): a control prefix reused across
            # owners is warmed by the observer's own earlier measurement.
            control_prompt = (
                f"u{_key(observer)[:6]}{_key(owner)[:6]}-{trial:02d}-ctl {_PREFIX_FILLER} "
                f"probe {trial}"
            )
            if primed_first[trial]:
                primed.append(self._model.measure_latency(observer, primed_prompt))
                control.append(self._model.measure_latency(observer, control_prompt))
            else:
                control.append(self._model.measure_latency(observer, control_prompt))
                primed.append(self._model.measure_latency(observer, primed_prompt))
        # The side channel makes the primed (cache-hit) prompt faster, so the gap
        # is control minus primed; a positive gap in the expected direction.
        t_statistic, df, std_error = _welch(control, primed)
        p_value = _student_t_sf(t_statistic, df)
        mean_gap = statistics.fmean(control) - statistics.fmean(primed)
        margin = _t_critical(df, _CI_LEVEL) * std_error if df > 0.0 else 0.0
        return TimingSignal(
            owner_tenant_id=owner,
            observed_in_tenant_id=observer,
            primed_mean_ms=round(statistics.fmean(primed), 2),
            control_mean_ms=round(statistics.fmean(control), 2),
            mean_gap_ms=round(mean_gap, 2),
            effect_size=round(_cohens_d(control, primed), 4),
            t_statistic=round(t_statistic, 4),
            degrees_of_freedom=round(df, 2),
            p_value=round(p_value, 10),
            ci_low_ms=round(mean_gap - margin, 2),
            ci_high_ms=round(mean_gap + margin, 2),
        )

    def _finding(self, signal: TimingSignal, alpha: float) -> Finding:
        severity = Severity.HIGH if signal.effect_size >= _LARGE_EFFECT else Severity.MEDIUM
        p_text = "<0.0001" if signal.p_value < 0.0001 else f"{signal.p_value:.4g}"
        return Finding(
            # Full hex (not a truncation): two tenant pairs must never collide
            # into one id, or dedupe_findings would merge distinct side channels.
            finding_id=(
                f"finding-{self.id}-{signal.owner_tenant_id.hex}-{signal.observed_in_tenant_id.hex}"
            ),
            probe_id=self.id,
            severity=severity,
            # Confidence reflects the strength of evidence: 1 minus the p-value.
            confidence=round(min(1.0, 1.0 - signal.p_value), 4),
            status=FindingStatus.CONFIRMED,
            owner_tenant_id=signal.owner_tenant_id,
            observed_in_tenant_id=signal.observed_in_tenant_id,
            surface=Surface.KV_CACHE,
            evidence_span=(
                f"prefix-cache timing distinguishable: primed {signal.primed_mean_ms}ms vs "
                f"control {signal.control_mean_ms}ms (gap {signal.mean_gap_ms}ms, "
                f"{int(_CI_LEVEL * 100)}% CI [{signal.ci_low_ms}, {signal.ci_high_ms}]ms); "
                f"Welch t={signal.t_statistic}, df={signal.degrees_of_freedom}, p={p_text}, "
                f"Cohen's d={signal.effect_size}; significant at Bonferroni alpha={alpha:.2g}"
            ),
            owasp_llm=self.owasp_llm,
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            owasp_secondary=self.owasp_secondary,
            remediation_pointer="disable cross-tenant KV prefix-cache sharing",
        )
