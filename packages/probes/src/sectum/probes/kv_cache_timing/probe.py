"""Class 5 - KV-cache timing side channel (the engineering spec, section 7).

Shared inference infrastructure with a KV prefix cache returns a prompt faster
when its prefix was recently processed. The probe warms the cache as one tenant,
then, as another tenant, measures the latency of prompts that do and do not
share that prefix. A statistically large timing gap is a side channel: the
second tenant can tell what the first tenant recently asked.

Class 5 is a statistical workflow rather than a plan/detect probe, so - like the
Class 11 erasure probe - it exposes its own ``run`` entry point.
"""

import math
import statistics
from dataclasses import dataclass
from uuid import UUID

from sectum.adapters import ModelAdapter
from sectum.spec import Finding, FindingStatus, Severity, Substrate, Surface

# Trials per condition. Enough samples that the jitter noise floor is stable.
_TRIALS = 24
# Cohen's d: 0.8 is the conventional "large effect" boundary. A timing gap above
# it stands clear of the per-prompt jitter noise floor.
_EFFECT_THRESHOLD = 0.8
_LARGE_EFFECT = 5.0


@dataclass(frozen=True)
class TimingSignal:
    """The measured timing side channel for one (owner, observer) tenant pair."""

    owner_tenant_id: UUID
    observed_in_tenant_id: UUID
    primed_mean_ms: float
    control_mean_ms: float
    effect_size: float


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


class KvCacheTimingProbe:
    """Class 5: a statistical timing test for a shared KV prefix cache."""

    id = "kv-cache-timing"
    name = "KV-cache timing side channel"
    owasp_llm = "LLM08:2025"

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
            if signal.effect_size >= _EFFECT_THRESHOLD:
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
        return TimingSignal(
            owner_tenant_id=owner,
            observed_in_tenant_id=observer,
            primed_mean_ms=round(statistics.fmean(primed), 2),
            control_mean_ms=round(statistics.fmean(control), 2),
            effect_size=round(_cohens_d(control, primed), 4),
        )

    def _finding(self, signal: TimingSignal) -> Finding:
        severity = Severity.HIGH if signal.effect_size >= _LARGE_EFFECT else Severity.MEDIUM
        return Finding(
            # Full hex (not a truncation): two tenant pairs must never collide
            # into one id, or dedupe_findings would merge distinct side channels.
            finding_id=(
                f"finding-{self.id}-{signal.owner_tenant_id.hex}-{signal.observed_in_tenant_id.hex}"
            ),
            probe_id=self.id,
            severity=severity,
            confidence=round(min(1.0, signal.effect_size / 10.0), 4),
            status=FindingStatus.CONFIRMED,
            owner_tenant_id=signal.owner_tenant_id,
            observed_in_tenant_id=signal.observed_in_tenant_id,
            surface=Surface.KV_CACHE,
            evidence_span=(
                f"prefix-cache timing distinguishable: primed {signal.primed_mean_ms}ms "
                f"vs control {signal.control_mean_ms}ms, Cohen's d={signal.effect_size}"
            ),
            owasp_llm=self.owasp_llm,
            remediation_pointer="disable cross-tenant KV prefix-cache sharing",
        )
