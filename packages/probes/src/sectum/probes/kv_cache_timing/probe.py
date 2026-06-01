"""Class 5 - KV-cache timing side channel (the engineering spec, section 7).

Shared inference infrastructure with a KV prefix cache returns a prompt faster
when its prefix was recently processed. The probe warms the cache as one tenant,
then, as another tenant, measures the latency of prompts that do and do not
share that prefix. A statistically large timing gap is a side channel: the
second tenant can tell what the first tenant recently asked.

Class 5 is a statistical workflow rather than a plan/detect probe, so - like the
Class 11 erasure probe - it exposes its own ``run`` entry point. Per the spec's
"avoid over-claiming" requirement, a finding is reported only when the timing gap
is *both* statistically significant (a two-sided Welch's t-test below ``_ALPHA``)
*and* practically large (Cohen's d above ``_EFFECT_THRESHOLD``), in the expected
direction (the primed prompt is faster). Each finding carries the p-value and a
confidence interval on the gap so an auditor can judge the strength of evidence.

The statistics are pure standard library: the Student's t survival function is
the regularized incomplete beta function (a Numerical Recipes continued
fraction), and the confidence-interval critical value is found by bisection - no
SciPy/NumPy dependency (the spec, section 13: dependency discipline).
"""

import math
import statistics
from dataclasses import dataclass
from uuid import UUID

from sectum.adapters import ModelAdapter
from sectum.spec import Finding, FindingStatus, Severity, Substrate, Surface

# Trials per condition. Enough samples that the jitter noise floor is stable and
# the t-test has ample degrees of freedom.
_TRIALS = 24
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

    @property
    def significant(self) -> bool:
        """Whether the gap is statistically significant, practically large, and directional.

        All three must hold to report a finding (the spec's "avoid over-claiming"):
        a significant p-value, a large effect size, and the primed prompt being
        the faster one (a positive gap).
        """
        return (
            self.p_value < _ALPHA
            and self.effect_size >= _EFFECT_THRESHOLD
            and self.mean_gap_ms > 0.0
        )


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
    """Standardised mean difference (slow minus fast); 0 when indistinguishable."""
    pooled_variance = (statistics.pvariance(slow) + statistics.pvariance(fast)) / 2.0
    if pooled_variance == 0.0:
        return 0.0
    return (statistics.fmean(slow) - statistics.fmean(fast)) / math.sqrt(pooled_variance)


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
    for the confidence interval. A zero standard error (no within-group spread)
    yields an infinite t and zero df-less significance, handled by the callers.
    """
    n_slow, n_fast = len(slow), len(fast)
    var_slow = statistics.variance(slow) if n_slow > 1 else 0.0
    var_fast = statistics.variance(fast) if n_fast > 1 else 0.0
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


class KvCacheTimingProbe:
    """Class 5: a statistical timing test for a shared KV prefix cache."""

    id = "kv-cache-timing"
    name = "KV-cache timing side channel"
    owasp_llm = "LLM08:2025"
    # A statistical timing side channel has no clean MITRE ATLAS technique, so
    # atlas is intentionally empty (the engineering spec, section 9).
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)

    def __init__(self, substrate: Substrate, *, model: ModelAdapter) -> None:
        self._substrate = substrate
        self._model = model

    def run(self) -> KvCacheTimingReport:
        """Warm the cache per tenant, then time prefix-sharing prompts from every other."""
        tenants = [tenant.tenant_id for tenant in self._substrate.tenants]
        signals: list[TimingSignal] = []
        findings: list[Finding] = []
        for owner in tenants:
            prefix = f"tenant-{owner.hex[:8]}-session"
            self._model.infer(owner, f"{prefix} context warm-up prompt")
            for observer in tenants:
                if observer == owner:
                    continue
                signals.append(self._measure(owner, observer, prefix))
        for signal in signals:
            if signal.significant:
                findings.append(self._finding(signal))
        return KvCacheTimingReport(signals=tuple(signals), findings=tuple(findings))

    def _measure(self, owner: UUID, observer: UUID, prefix: str) -> TimingSignal:
        primed = [
            self._model.measure_latency(observer, f"{prefix} probe {trial}")
            for trial in range(_TRIALS)
        ]
        control = [
            self._model.measure_latency(observer, f"unrelated-{observer.hex[:8]} probe {trial}")
            for trial in range(_TRIALS)
        ]
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

    def _finding(self, signal: TimingSignal) -> Finding:
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
                f"Cohen's d={signal.effect_size}"
            ),
            owasp_llm=self.owasp_llm,
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            remediation_pointer="disable cross-tenant KV prefix-cache sharing",
        )
