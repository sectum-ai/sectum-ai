"""Tests for Class 5 - the KV-cache timing side-channel probe."""

import random
from uuid import UUID

from sectum_ai.adapters import FakeModel
from sectum_ai.probes import KvCacheTimingProbe, confirmed_findings
from sectum_ai.spec import Scenario, Severity, SharedEntity, Surface, SyntheticTenantSpec
from sectum_ai.substrate import build_substrate, default_scenario


def test_shared_prefix_cache_is_a_timing_side_channel() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    model = FakeModel(prefix_cache=True)
    report = KvCacheTimingProbe(substrate, model=model).run()
    findings = confirmed_findings(report.findings)
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)
    assert all(f.surface is Surface.KV_CACHE for f in findings)
    assert all(signal.effect_size > 1.0 for signal in report.signals)


def test_no_prefix_cache_has_no_timing_side_channel() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    model = FakeModel(prefix_cache=False)
    report = KvCacheTimingProbe(substrate, model=model).run()
    assert report.findings == ()
    # without a shared cache the timing gap stays inside the noise floor
    assert all(abs(signal.effect_size) < 0.8 for signal in report.signals)


def test_report_exposes_per_pair_effect_sizes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    model = FakeModel(prefix_cache=True)
    report = KvCacheTimingProbe(substrate, model=model).run()
    # four tenants yield twelve ordered (owner, observer) pairs
    assert len(report.effect_sizes) == 12
    assert all(value > 1.0 for value in report.effect_sizes.values())


def test_two_low_valued_tenants_yield_distinct_finding_ids() -> None:
    # UUID(int=0xA) and UUID(int=0xC) share their first 8 hex chars ("00000000"),
    # so a truncated finding id would collide and dedupe_findings would merge two
    # distinct cross-tenant timing leaks into one. Full hex keeps them distinct.
    scenario = Scenario(
        scenario_id="kv-low-ids",
        seed=1,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=UUID(int=0xA), display_name="Acme", industry="robotics", corpus_size=24
            ),
            SyntheticTenantSpec(
                tenant_id=UUID(int=0xC), display_name="Globex", industry="finance", corpus_size=24
            ),
        ),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )
    substrate = build_substrate(scenario)
    report = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    finding_ids = [finding.finding_id for finding in report.findings]
    assert len(finding_ids) >= 2
    assert len(set(finding_ids)) == len(finding_ids)  # no id collisions
    # Pin the underlying distinctness a truncated id would have merged: both
    # ordered cross-tenant pairs (A->C and C->A) are present as their own
    # findings, keyed on the full-hex principals.
    pairs = {(f.owner_tenant_id, f.observed_in_tenant_id) for f in report.findings}
    assert (UUID(int=0xA), UUID(int=0xC)) in pairs
    assert (UUID(int=0xC), UUID(int=0xA)) in pairs


# --- Statistical-rigor tests (spec §7 Class 5: t-test, p-value, CI) ----------

from sectum_ai.probes.kv_cache_timing.probe import (  # noqa: E402
    _student_t_sf,
    _t_critical,
    _welch,
)


def test_student_t_survival_matches_t_table_references() -> None:
    # Two-sided tail probabilities against standard t-table critical values.
    assert _student_t_sf(0.0, 10) == 1.0
    assert abs(_student_t_sf(2.228, 10) - 0.05) < 0.005
    assert abs(_student_t_sf(3.169, 10) - 0.01) < 0.002
    # Large df approaches the normal: |t|=1.96 -> ~0.05.
    assert abs(_student_t_sf(1.96, 1_000_000) - 0.05) < 0.005


def test_t_critical_inverts_the_survival_function() -> None:
    assert abs(_t_critical(10, 0.95) - 2.228) < 0.01
    assert abs(_t_critical(10, 0.99) - 3.169) < 0.01


def test_welch_matches_a_textbook_two_sample_case() -> None:
    # Mean diff -5, equal spreads, n=5 each -> t=-5.0, df=8.0; p ~ 0.00105.
    t_stat, df, _ = _welch([1.0, 2.0, 3.0, 4.0, 5.0], [6.0, 7.0, 8.0, 9.0, 10.0])
    assert abs(t_stat - (-5.0)) < 1e-9
    assert abs(df - 8.0) < 1e-9
    assert abs(_student_t_sf(t_stat, df) - 0.00105) < 0.0005


def test_a_confirmed_finding_carries_p_value_and_confidence_interval() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    report = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    findings = confirmed_findings(report.findings)
    assert findings
    for signal in report.signals:
        # Every detected pair is statistically significant, practically large,
        # and directional (primed faster -> positive gap).
        assert signal.p_value < 0.01
        assert signal.effect_size >= 0.8
        assert signal.mean_gap_ms > 0.0
        # The confidence interval on the gap excludes zero.
        assert signal.ci_low_ms > 0.0
        assert signal.ci_low_ms <= signal.mean_gap_ms <= signal.ci_high_ms
    # The evidence span an auditor reads cites the test, p-value, and CI.
    span = findings[0].evidence_span
    assert "p=" in span
    assert "CI" in span
    assert "Welch t=" in span


def test_finding_confidence_is_a_bounded_probability_tracking_the_p_value() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    report = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    findings = confirmed_findings(report.findings)
    assert findings
    signal_by_pair = {
        (signal.owner_tenant_id, signal.observed_in_tenant_id): signal for signal in report.signals
    }
    for finding in findings:
        # Confidence is a probability: it must stay within [0, 1] for any
        # p-value, and equal 1 - p clamped at 1.0 (a near-zero p-value must not
        # push it past 1.0). Guards the pin in the finding builder.
        assert 0.0 <= finding.confidence <= 1.0
        signal = signal_by_pair[(finding.owner_tenant_id, finding.observed_in_tenant_id)]
        assert finding.confidence == round(min(1.0, 1.0 - signal.p_value), 4)


def test_no_cache_signals_are_not_statistically_significant() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    report = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=False)).run()
    assert report.findings == ()
    # No shared cache: the gap is noise, so nothing is significant and the
    # probe does not over-claim (spec §7 Class 5).
    for signal in report.signals:
        assert not signal.significant
        assert signal.p_value > 0.05


def test_timing_statistics_are_deterministic() -> None:
    # The fake model is deterministic, so two runs produce identical p-values
    # and confidence intervals - the reproducibility contract (spec §6.5).
    substrate = build_substrate(default_scenario(seed=2026))
    first = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    second = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    assert [s.p_value for s in first.signals] == [s.p_value for s in second.signals]
    assert [s.ci_low_ms for s in first.signals] == [s.ci_low_ms for s in second.signals]


def test_kv_timing_detects_a_leak_through_a_serving_adapter() -> None:
    # The serving adapters (vLLM/TGI) exist to drive Class 5: confirm the probe's
    # warm-then-measure flow surfaces a cross-tenant prefix-cache timing gap through
    # a VLLMModel whose backend shares one prefix cache across callers (no tenant
    # scope), mirroring a real shared KV cache.
    import hashlib

    from sectum_ai.adapters.model.vllm import VLLMModel

    class _SharedCacheBackend:
        # Mirrors FakeModel's prefix-cache timing so the paired-trial Welch test has
        # a real signal: a warmed 20-char prefix returns ~60ms faster, with a paired
        # last-token jitter. The cache is keyed on the prompt only (no tenant), so an
        # owner's warmed prefix leaks into an observer's timing.
        def __init__(self) -> None:
            self._warm: set[str] = set()

        def complete(self, prompt: str) -> str:
            self._warm.add(prompt[:20])
            return ""  # completion only, no echo

        def first_token_latency_ms(self, prompt: str) -> float:
            tokens = prompt.split()
            key = (tokens[-1] if tokens else prompt).encode("utf-8")
            jitter = float(int.from_bytes(hashlib.sha256(key).digest()[:2], "big") % 16)
            latency = 100.0 + jitter
            return latency - 60.0 if prompt[:20] in self._warm else latency

    substrate = build_substrate(default_scenario(seed=2026))
    report = KvCacheTimingProbe(substrate, model=VLLMModel(_SharedCacheBackend())).run()
    findings = confirmed_findings(report.findings)
    assert findings  # the shared prefix cache leaks a warmed prefix across tenants
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)
    assert all(f.surface is Surface.KV_CACHE for f in findings)


# --- Gate-arm and degenerate-input coverage (the avoid-over-claiming logic) ---

from sectum_ai.probes.kv_cache_timing.probe import TimingSignal  # noqa: E402


def _signal(*, p_value: float, effect_size: float, mean_gap_ms: float) -> TimingSignal:
    """A TimingSignal with only the gate-relevant fields varied."""
    return TimingSignal(
        owner_tenant_id=UUID(int=1),
        observed_in_tenant_id=UUID(int=2),
        primed_mean_ms=40.0,
        control_mean_ms=40.0 + mean_gap_ms,
        mean_gap_ms=mean_gap_ms,
        effect_size=effect_size,
        t_statistic=0.0,
        degrees_of_freedom=46.0,
        p_value=p_value,
        ci_low_ms=mean_gap_ms - 1.0,
        ci_high_ms=mean_gap_ms + 1.0,
    )


def test_significant_requires_all_three_arms() -> None:
    # The avoid-over-claiming gate is significant AND large AND directional.
    assert _signal(p_value=0.001, effect_size=9.0, mean_gap_ms=5.0).significant
    # significant + large but WRONG direction (primed slower) -> not a finding.
    assert not _signal(p_value=0.001, effect_size=9.0, mean_gap_ms=-5.0).significant
    # significant + directional but SMALL effect -> not a finding.
    assert not _signal(p_value=0.001, effect_size=0.5, mean_gap_ms=5.0).significant
    # large + directional but NOT significant -> not a finding.
    assert not _signal(p_value=0.20, effect_size=9.0, mean_gap_ms=5.0).significant
    # p exactly at alpha (0.01) is not significant (strict <).
    assert not _signal(p_value=0.01, effect_size=9.0, mean_gap_ms=5.0).significant


def test_finding_severity_scales_with_effect_size() -> None:
    # _LARGE_EFFECT boundary (5.0): below is MEDIUM, at/above is HIGH.
    probe = KvCacheTimingProbe(
        build_substrate(default_scenario(seed=2026)), model=FakeModel(prefix_cache=True)
    )
    medium = probe._finding(_signal(p_value=0.001, effect_size=4.9, mean_gap_ms=5.0), 0.001)
    high = probe._finding(_signal(p_value=0.001, effect_size=5.1, mean_gap_ms=5.0), 0.001)
    assert medium.severity is Severity.MEDIUM
    assert high.severity is Severity.HIGH


def test_bonferroni_corrected_level_is_stricter_than_the_per_pair_alpha() -> None:
    # A gap below the per-pair _ALPHA (0.01) but above a Bonferroni-corrected
    # level is per-pair significant yet must fail the run-wide multiplicity test,
    # so a run over many tenant pairs does not report borderline noise.
    signal = _signal(p_value=0.005, effect_size=9.0, mean_gap_ms=5.0)
    assert signal.significant  # judged alone, at _ALPHA
    assert not signal.is_significant_at(0.001)  # judged run-wide, corrected


def test_welch_handles_zero_variance_samples() -> None:
    # A constant-latency backend yields zero within-group spread. Identical samples
    # are indistinguishable (t=0, p=1). Different-but-constant means used to give an
    # infinite t with ZERO degrees of freedom, read as p=1.0 - so a perfect,
    # jitter-free side channel produced no finding. Variances are floored at the
    # timer's resolution instead: the gap is then as significant as it looks.
    import math

    from sectum_ai.probes.kv_cache_timing.probe import _cohens_d, _student_t_sf

    t_eq, df_eq, se_eq = _welch([5.0, 5.0, 5.0, 5.0], [5.0, 5.0, 5.0, 5.0])
    assert t_eq == 0.0 and df_eq > 0.0 and se_eq > 0.0
    assert _student_t_sf(t_eq, df_eq) == 1.0

    t_ne, df_ne, se_ne = _welch([7.0, 7.0, 7.0, 7.0], [5.0, 5.0, 5.0, 5.0])
    assert math.isfinite(t_ne) and t_ne > 1e3
    assert df_ne > 0.0 and se_ne > 0.0
    assert _student_t_sf(t_ne, df_ne) < 1e-9
    assert _cohens_d([7.0, 7.0], [5.0, 5.0]) > 1e3


def test_welch_handles_a_single_sample_group() -> None:
    # An asymmetric (n=1, n>1) input: the n=1 group has no variance estimate, so
    # its Welch-Satterthwaite denominator term must be skipped, not divide by
    # (n-1)=0. Guards against a ZeroDivisionError in _welch.
    import math

    t_stat, df, std_error = _welch([5.0], [1.0, 2.0, 3.0, 4.0])
    assert math.isfinite(t_stat)
    assert std_error > 0.0
    # the single-sample group contributes 0 df, so df reduces to the other
    # group's n - 1 = 3.
    assert df == 3.0
    # both groups n=1: zero spread routes through the std_error==0 branch, not a
    # crash.
    t_one, df_one, se_one = _welch([5.0], [9.0])
    assert math.isinf(t_one) and df_one == 0.0 and se_one == 0.0


class _DriftingModel(FakeModel):
    """A model with NO prefix cache whose latency creeps up by a fixed step.

    There is no side channel to find. The drift stands in for anything that
    changes during a run - thermal throttling, CPU frequency scaling, a noisy
    neighbour, GC pressure - which is ambient on any real machine.
    """

    def __init__(self, slope_ms: float) -> None:
        super().__init__(prefix_cache=False)
        self._slope = slope_ms
        self._calls = 0

    def measure_latency(self, tenant: UUID, prompt: str) -> float:
        self._calls += 1
        return 100.0 + self._slope * self._calls


def test_a_drifting_machine_does_not_manufacture_a_side_channel() -> None:
    # Timing all primed trials and then all control trials put every bit of a
    # run's drift onto whichever block ran second, and the t-test read that offset
    # as a cross-tenant side channel. It was not marginal: at 0.01 ms per call all
    # 12 tenant pairs were flagged, each with an identical mean gap of
    # _TRIALS x slope - the block-size artifact itself, not a per-pair signal.
    # Inventing a cross-tenant finding out of machine noise is the worst direction
    # for a signed evidence pack to be wrong in, so the arms are now interleaved.
    substrate = build_substrate(default_scenario(seed=5, corpus_size=8))
    for slope in (0.01, 0.1, 1.0):
        report = KvCacheTimingProbe(substrate, model=_DriftingModel(slope)).run()
        assert report.findings == (), f"drift of {slope} ms/call invented a finding"
        # Alternating which arm is timed first makes the two arms' mean measurement
        # positions equal, so a LINEAR drift cancels exactly rather than shrinking.
        assert all(signal.mean_gap_ms == 0.0 for signal in report.signals)


def test_interleaving_still_detects_a_real_shared_cache() -> None:
    # The premise the test above rests on: the drift fix must not have bought its
    # zero false positives by blunting the probe. A genuine shared prefix cache is
    # still caught, on every ordered tenant pair.
    substrate = build_substrate(default_scenario(seed=5, corpus_size=8))
    report = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    assert len(report.findings) == len(report.signals)
    assert all(signal.mean_gap_ms > 0.0 for signal in report.signals)


class _JitterFreeModel(FakeModel):
    """A shared prefix cache with NO per-prompt jitter: a perfect side channel."""

    def measure_latency(self, tenant: UUID, prompt: str) -> float:
        warm = self._prefix(prompt) in self._warmed_prefixes
        return 40.0 if warm else 100.0


def test_a_jitter_free_shared_cache_is_still_a_side_channel() -> None:
    # Zero within-arm spread gave an infinite t with zero df (p=1.0) and d=0, so
    # the cleanest possible 60 ms cross-tenant gap produced no finding.
    substrate = build_substrate(default_scenario(seed=5, corpus_size=8))
    report = KvCacheTimingProbe(substrate, model=_JitterFreeModel(prefix_cache=True)).run()
    assert len(report.findings) == len(report.signals) > 0
    assert all(signal.mean_gap_ms == 60.0 for signal in report.signals)


class _WarmingModel(FakeModel):
    """A backend whose latency call runs inference and so warms the cache (HF).

    ``shared`` keys the cache on the prompt alone (the side channel); otherwise
    on (tenant, prompt) - a correctly scoped cache that must NOT be flagged.
    """

    def __init__(self, *, shared: bool) -> None:
        super().__init__()
        self._shared = shared
        self._warm: set[tuple[UUID | None, str]] = set()

    def _key(self, tenant: UUID, prompt: str) -> tuple[UUID | None, str]:
        return (None if self._shared else tenant, self._prefix(prompt))

    def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
        self._warm.add(self._key(tenant, prompt))
        return "completion"

    def measure_latency(self, tenant: UUID, prompt: str) -> float:
        hit = self._key(tenant, prompt) in self._warm
        self.infer(tenant, prompt)
        return 40.0 if hit else 100.0


def test_a_measurement_that_warms_the_cache_still_detects_a_shared_cache() -> None:
    # With one prefix per pair, the observer's own trial 0 warmed both the primed
    # and the control prefix for every later trial, so both arms were cache hits
    # from trial 1 on and a genuine shared cache survived only in trial 0 (d~0.25,
    # no finding). One owner-warmed prefix per trial, measured exactly once, and a
    # fresh control prefix per trial keep the signal in every trial.
    substrate = build_substrate(default_scenario(seed=5, corpus_size=8))
    leaky = KvCacheTimingProbe(substrate, model=_WarmingModel(shared=True)).run()
    assert len(leaky.findings) == len(leaky.signals) > 0
    assert all(signal.mean_gap_ms == 60.0 for signal in leaky.signals)
    # and a correctly tenant-scoped cache, which the observer also warms, is not
    # mistaken for one: neither arm is ever a hit.
    scoped = KvCacheTimingProbe(substrate, model=_WarmingModel(shared=False)).run()
    assert scoped.findings == ()
    assert all(signal.mean_gap_ms == 0.0 for signal in scoped.signals)


class _BlockCacheBackend:
    """A serving backend with a block-granular shared prefix cache (vLLM's APC).

    Only whole 16-token blocks are cached, chained on the previous block's hash,
    and a partial block never is - so a 20-character prefix (9-12 tokens) could
    not produce a single hit and the probe recorded Class 5 PASS against it.
    """

    block = 16

    def __init__(self) -> None:
        self._warm: set[tuple[str, ...]] = set()

    def _blocks(self, prompt: str) -> list[tuple[str, ...]]:
        tokens = prompt.split()
        full = len(tokens) // self.block * self.block
        return [tuple(tokens[: i + self.block]) for i in range(0, full, self.block)]

    def complete(self, prompt: str) -> str:
        self._warm.update(self._blocks(prompt))
        return ""

    def first_token_latency_ms(self, prompt: str) -> float:
        hits = sum(1 for chain in self._blocks(prompt) if chain in self._warm)
        self._warm.update(self._blocks(prompt))
        return 100.0 - 15.0 * hits


def test_a_block_granular_shared_cache_is_detected() -> None:
    from sectum_ai.adapters.model.vllm import VLLMModel

    substrate = build_substrate(default_scenario(seed=5, corpus_size=8))
    report = KvCacheTimingProbe(substrate, model=VLLMModel(_BlockCacheBackend())).run()
    assert len(report.findings) == len(report.signals) > 0
    assert all(signal.mean_gap_ms > 0.0 for signal in report.signals)


def test_two_low_valued_tenants_do_not_share_a_warm_up_prefix() -> None:
    # Prefixes keyed on the leading 8 hex characters collided for low-int ids, so
    # the second owner's own warm-up primed the (tenant, prefix) key its later
    # observer measurement hit on a correctly tenant-scoped cache.
    scenario = Scenario(
        scenario_id="kv-low-ids-scoped",
        seed=1,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=UUID(int=0xA), display_name="Acme", industry="robotics", corpus_size=24
            ),
            SyntheticTenantSpec(
                tenant_id=UUID(int=0xC), display_name="Globex", industry="finance", corpus_size=24
            ),
        ),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )
    substrate = build_substrate(scenario)
    report = KvCacheTimingProbe(substrate, model=_WarmingModel(shared=False)).run()
    assert report.findings == ()
    assert all(signal.mean_gap_ms == 0.0 for signal in report.signals)


class _RoundRobinPool(FakeModel):
    """No prefix cache. Latency is whichever replica the dispatcher picked.

    A four-way round robin, the ordinary shape of a served model behind a load
    balancer. Nothing here can leak: the prompt does not affect the latency at
    all, only the call's position in the rotation does.
    """

    def __init__(self, pool: tuple[float, ...]) -> None:
        super().__init__(prefix_cache=False)
        self._pool = pool
        self._calls = 0

    def measure_latency(self, tenant: UUID, prompt: str) -> float:
        index = self._calls
        self._calls += 1
        # Ambient jitter, so the t-test has the non-degenerate variance a real
        # machine gives it. Identical in distribution for both arms.
        return self._pool[index % len(self._pool)] + random.Random(index).uniform(-0.5, 0.5)


def test_a_round_robin_replica_pool_does_not_manufacture_a_side_channel() -> None:
    # A fixed ABBA schedule puts each arm on a fixed pair of residues mod 4 -
    # primed at call indices {0,3}, control at {1,2} - so behind a four-way round
    # robin, where the replica IS the call index mod 4, the arms are pinned to
    # disjoint replica sets. Any spread across the pool then lands entirely on one
    # arm: this pool (two fast replicas exactly where the primed arm lands)
    # produced 12 CONFIRMED cross-tenant findings at Cohen's d = 19.5 against a
    # model with no cache at all. ABBA cancels a LINEAR drift; a period-4
    # systematic it does not touch.
    substrate = build_substrate(default_scenario(seed=5, corpus_size=8))
    report = KvCacheTimingProbe(
        substrate, model=_RoundRobinPool((100.0, 105.0, 105.0, 100.0))
    ).run()
    assert report.findings == (), (
        "a round-robin replica pool invented "
        f"{len(report.findings)} findings; max |d| "
        f"{max((abs(s.effect_size) for s in report.signals), default=0.0):.2f}"
    )


def test_the_shuffled_arm_order_is_reproducible() -> None:
    # The order is seeded from the tenant pair, so two runs of the same scenario
    # against the same backend measure the same thing - the determinism the whole
    # evidence chain rests on.
    substrate = build_substrate(default_scenario(seed=5, corpus_size=8))
    first = KvCacheTimingProbe(substrate, model=_RoundRobinPool((100.0, 105.0, 105.0, 100.0))).run()
    second = KvCacheTimingProbe(
        substrate, model=_RoundRobinPool((100.0, 105.0, 105.0, 100.0))
    ).run()
    assert [s.mean_gap_ms for s in first.signals] == [s.mean_gap_ms for s in second.signals]
