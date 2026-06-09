"""Tests for the pure-stdlib statistics helpers (``sectum_ai.spec.stats``)."""

import math

import pytest

from sectum_ai.spec import normal_quantile, wilson_interval


def test_normal_quantile_matches_known_critical_values() -> None:
    # Standard two-sided z critical values, to the published precision: 90% ->
    # 1.6449, 95% -> 1.9600, 99% -> 2.5758. These pin the inverse-CDF bisection
    # to the textbook normal quantile, so the Wilson width is provably correct.
    assert math.isclose(normal_quantile(0.95), 1.6448536269514722, abs_tol=1e-9)
    assert math.isclose(normal_quantile(0.975), 1.959963984540054, abs_tol=1e-9)
    assert math.isclose(normal_quantile(0.995), 2.5758293035489004, abs_tol=1e-9)


def test_normal_quantile_is_symmetric_about_the_median() -> None:
    # Phi^{-1}(p) == -Phi^{-1}(1 - p), and Phi^{-1}(0.5) == 0.
    assert math.isclose(normal_quantile(0.5), 0.0, abs_tol=1e-9)
    assert math.isclose(normal_quantile(0.8), -normal_quantile(0.2), abs_tol=1e-9)


def test_normal_quantile_rejects_degenerate_probabilities() -> None:
    # The quantile diverges at the open bounds; the function refuses 0, 1, and
    # out-of-range inputs rather than returning a saturated +/- 40 sentinel.
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="strictly within"):
            normal_quantile(bad)


def test_wilson_interval_matches_a_published_reference_value() -> None:
    # The canonical small-sample Wilson reference: k=1, n=10, 95% -> approximately
    # (0.0179, 0.4042). Matching this to four decimals proves the formula is
    # correct against an external source, not merely internally consistent.
    low, high = wilson_interval(1, 10, confidence=0.95)
    assert math.isclose(low, 0.0179, abs_tol=5e-5)
    assert math.isclose(high, 0.4042, abs_tol=5e-5)


def test_wilson_interval_brackets_the_point_estimate() -> None:
    # For an interior proportion the point estimate k/n lies strictly inside the
    # interval, and the interval is non-degenerate.
    low, high = wilson_interval(334, 350)
    assert low < 334 / 350 < high
    assert high - low > 0.0


def test_wilson_interval_is_undefined_for_an_empty_sample() -> None:
    # Documented convention: an empty sample has no estimable proportion, so the
    # interval is the degenerate (0.0, 0.0) rather than a division by zero.
    assert wilson_interval(0, 0) == (0.0, 0.0)
    assert wilson_interval(0, 0, confidence=0.99) == (0.0, 0.0)


def test_wilson_bounds_stay_within_the_unit_interval_at_the_extremes() -> None:
    # At k == 0 the lower bound is exactly 0 and at k == n the upper bound is
    # exactly 1, but in both cases the *other* bound stays strictly inside (0, 1):
    # the Wald approximation would collapse to a zero-width interval here, the very
    # failure the Wilson interval is chosen to avoid.
    low_zero, high_zero = wilson_interval(0, 20)
    assert low_zero == 0.0
    assert 0.0 < high_zero < 1.0

    low_full, high_full = wilson_interval(20, 20)
    assert high_full == 1.0
    assert 0.0 < low_full < 1.0


def test_wilson_bounds_are_always_in_the_unit_interval() -> None:
    # Property check across a grid of samples and confidence levels: every bound is
    # ordered and lives in [0, 1], so a confidence interval can never be rendered
    # as a nonsensical negative or above-100% rate.
    for n in (1, 2, 5, 13, 100, 350):
        for k in range(n + 1):
            for confidence in (0.80, 0.90, 0.95, 0.99):
                low, high = wilson_interval(k, n, confidence=confidence)
                assert 0.0 <= low <= high <= 1.0


def test_wider_confidence_yields_a_wider_interval() -> None:
    # Monotonicity in the confidence level: a 99% interval contains the 90% one.
    low_90, high_90 = wilson_interval(7, 20, confidence=0.90)
    low_99, high_99 = wilson_interval(7, 20, confidence=0.99)
    assert low_99 <= low_90
    assert high_99 >= high_90


def test_smaller_sample_yields_a_wider_interval_at_the_same_rate() -> None:
    # Honest precision: the same point estimate (50%) is far less certain at n=4
    # than at n=400, so the small-sample interval must be strictly wider. This is
    # the whole reason a bare RPR point estimate over-claims at small n.
    narrow = wilson_interval(2, 4)
    wide = wilson_interval(200, 400)
    assert (narrow[1] - narrow[0]) > (wide[1] - wide[0])


def test_wilson_interval_validates_its_arguments() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        wilson_interval(0, -1)
    with pytest.raises(ValueError, match=r"within \[0, 5\]"):
        wilson_interval(6, 5)
    with pytest.raises(ValueError, match=r"within \[0, 0\]"):
        wilson_interval(-1, 0)
    for bad_confidence in (0.0, 1.0, -0.5, 2.0):
        with pytest.raises(ValueError, match="strictly within"):
            wilson_interval(1, 10, confidence=bad_confidence)
