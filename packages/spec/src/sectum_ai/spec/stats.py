"""Pure standard-library statistics for honest metric reporting.

A point estimate of a rate over-claims precision when the sample is small. The
flagship Class-2 metric, the Retrieval-Pivot Rate (the engineering spec,
section 7), is a binomial proportion - ``k`` of ``n`` benign cross-tenant
queries surfaced a foreign marker - so it carries a confidence interval, exactly
as the Class-5 timing channel reports a confidence interval on its gap (the
spec's "report confidence intervals" / "avoid over-claiming" requirement).

This module is the shared home for that math. Like the Class-5 probe, it depends
only on the standard library (``math``): the normal quantile is found by
bisection on the exact ``math.erfc``-based CDF, so the result is deterministic
across machines and Python versions and needs no SciPy/NumPy (the spec,
section 13: dependency discipline).
"""

import math

__all__ = ["normal_quantile", "wilson_interval"]


def normal_quantile(probability: float) -> float:
    """Return the standard-normal quantile (inverse CDF) at ``probability``.

    Solves ``Phi(z) == probability`` for ``z``, where ``Phi`` is the standard
    normal CDF ``0.5 * erfc(-z / sqrt(2))``. The CDF is monotonically increasing,
    so the root is found by bisection - the same dependency-free technique the
    Class-5 probe uses to invert its t survival function - giving full
    double-precision accuracy with no inverse-CDF table or third-party library.

    Args:
        probability: A probability strictly between 0 and 1.

    Returns:
        The value ``z`` such that ``Phi(z) == probability``.

    Raises:
        ValueError: If ``probability`` is not strictly within ``(0, 1)``; the
            quantile diverges to +/- infinity at the open bounds.
    """
    if not 0.0 < probability < 1.0:
        raise ValueError(f"probability must be strictly within (0, 1), got {probability!r}")
    # +/- 40 standard deviations brackets the quantile for any representable
    # double-precision probability; Phi(-40) and Phi(40) round to 0.0 and 1.0.
    low, high = -40.0, 40.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if 0.5 * math.erfc(-mid / math.sqrt(2.0)) < probability:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def wilson_interval(
    successes: int, trials: int, *, confidence: float = 0.95
) -> tuple[float, float]:
    """Return the Wilson score interval for a binomial proportion.

    The Wilson score interval is the right tool for a proportion: unlike the
    normal (Wald) approximation it stays inside ``[0, 1]`` and keeps near-nominal
    coverage at small ``trials`` or extreme proportions (``successes == 0`` or
    ``successes == trials``), where the Wald interval degenerates to zero width.
    That makes it the honest companion to the Retrieval-Pivot Rate, whose bare
    point estimate over-claims precision when ``trials`` is small.

    The bounds are clamped to ``[0, 1]``: the Wilson formula already lies within
    the unit interval, and the clamp only absorbs sub-ulp rounding from the
    square root so the contract holds exactly.

    Args:
        successes: The number of successes ``k`` (``0 <= k <= trials``).
        trials: The number of trials ``n`` (``n >= 0``).
        confidence: The two-sided confidence level in ``(0, 1)``; defaults to
            ``0.95`` for a 95% interval.

    Returns:
        The ``(low, high)`` bounds of the interval, each in ``[0, 1]``. By
        convention an empty sample (``trials == 0``) has an undefined proportion
        and returns ``(0.0, 0.0)``, so a caller never divides by zero.

    Raises:
        ValueError: If ``trials`` is negative, ``successes`` is outside
            ``[0, trials]``, or ``confidence`` is not strictly within ``(0, 1)``.
    """
    if trials < 0:
        raise ValueError(f"trials must be non-negative, got {trials!r}")
    if not 0 <= successes <= trials:
        raise ValueError(f"successes must be within [0, {trials}], got {successes!r}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be strictly within (0, 1), got {confidence!r}")
    if trials == 0:
        # An empty sample has no estimable proportion; report a degenerate
        # interval rather than dividing by zero. Documented and tested.
        return (0.0, 0.0)
    # Two-sided level: split the remaining tail mass across both tails.
    z = normal_quantile((1.0 + confidence) / 2.0)
    n = float(trials)
    z_sq = z * z
    p_hat = successes / n
    denominator = 1.0 + z_sq / n
    center = (p_hat + z_sq / (2.0 * n)) / denominator
    half_width = (z / denominator) * math.sqrt(p_hat * (1.0 - p_hat) / n + z_sq / (4.0 * n * n))
    low = max(0.0, center - half_width)
    high = min(1.0, center + half_width)
    return (low, high)
