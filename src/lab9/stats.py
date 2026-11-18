"""Statistics for M2 judge calibration, M4 paired bootstrap, and M6 pass@k metrics.

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from numbers import Integral, Real

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def _normalize_labels(human: Sequence[str], judge: Sequence[str]) -> tuple[list[str], list[str]]:
    if len(human) != len(judge):
        raise ValueError(f"human and judge label counts differ: {len(human)} != {len(judge)}")

    def normalize(labels: Sequence[str], name: str) -> list[str]:
        result = []
        for label in labels:
            if not isinstance(label, str) or label.strip().upper() not in {"PASS", POS}:
                raise ValueError(f"{name} labels must be PASS or FAIL; got {label!r}")
            result.append(label.strip().upper())
        return result

    return normalize(human, "human"), normalize(judge, "judge")


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    h, j = _normalize_labels(human, judge)
    return {
        "tp": sum(a == POS and b == POS for a, b in zip(h, j)),
        "fp": sum(a != POS and b == POS for a, b in zip(h, j)),
        "fn": sum(a == POS and b != POS for a, b in zip(h, j)),
        "tn": sum(a != POS and b != POS for a, b in zip(h, j)),
    }


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    counts = confusion(human, judge)
    predicted_positive = counts["tp"] + counts["fp"]
    actual_positive = counts["tp"] + counts["fn"]
    precision = counts["tp"] / predicted_positive if predicted_positive else 0.0
    recall = counts["tp"] / actual_positive if actual_positive else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    h, j = _normalize_labels(human, judge)
    n = len(h)
    if not n:
        raise ValueError("Cohen's kappa is undefined for empty label sequences")
    observed = sum(a == b for a, b in zip(h, j)) / n
    expected = sum(
        (h.count(label) / n) * (j.count(label) / n)
        for label in ("PASS", POS)
    )
    if expected == 1:
        raise ValueError("Cohen's kappa is undefined when expected agreement is 1")
    return (observed - expected) / (1 - expected)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    rates = {
        "observed_rate": observed_rate,
        "sensitivity": sensitivity,
        "specificity": specificity,
    }
    for name, value in rates.items():
        try:
            valid_rate = math.isfinite(value) and 0 <= value <= 1
        except TypeError:
            valid_rate = False
        if not valid_rate:
            raise ValueError(f"{name} must be a finite rate in [0, 1]; got {value!r}")
    denominator = sensitivity + specificity - 1
    if denominator == 0:
        raise ValueError("Rogan-Gladen correction is undefined when sensitivity + specificity = 1")
    corrected = (observed_rate + specificity - 1) / denominator
    return min(1.0, max(0.0, corrected))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy import stats as scipy_stats

    if len(a) != len(b):
        raise ValueError(f"paired samples must have equal length: {len(a)} != {len(b)}")
    if len(a) == 0:
        raise ValueError("paired samples must not be empty")
    if isinstance(n_resamples, bool) or not isinstance(n_resamples, Integral) or n_resamples <= 0:
        raise ValueError("n_resamples must be a positive integer")
    if (isinstance(confidence, bool) or not isinstance(confidence, Real)
            or not math.isfinite(confidence) or not 0 < confidence < 1):
        raise ValueError("confidence must be a finite value between 0 and 1")

    try:
        values_a = np.asarray(a, dtype=float)
        values_b = np.asarray(b, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("paired samples must contain numeric values") from exc
    if values_a.ndim != 1 or values_b.ndim != 1:
        raise ValueError("paired samples must be one-dimensional")
    if not np.isfinite(values_a).all() or not np.isfinite(values_b).all():
        raise ValueError("paired samples must contain only finite values")
    if np.array_equal(values_a, values_b):
        return 0.0, 0.0, 0.0

    def mean_difference(candidate, baseline, axis=-1):
        return np.mean(candidate - baseline, axis=axis)

    delta = float(np.mean(values_a) - np.mean(values_b))
    result = scipy_stats.bootstrap(
        (values_a, values_b),
        mean_difference,
        n_resamples=int(n_resamples),
        confidence_level=float(confidence),
        method="percentile",
        paired=True,
        vectorized=True,
        rng=np.random.default_rng(rng),
    )
    return delta, float(result.confidence_interval.low), float(result.confidence_interval.high)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    n, c, k = _validate_pass_k_counts(n, c, k)
    if c == 0:
        return 0.0
    if k == 1:
        return c / n
    if k > n - c:
        return 1.0

    log_failure_probability = 0.0
    for i in range(k):
        failure_fraction = c / (n - i)
        if failure_fraction >= 1.0:
            return 1.0
        log_failure_probability += math.log1p(-failure_fraction)
    return min(1.0, max(c / n, -math.expm1(log_failure_probability)))


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    n, c, k = _validate_pass_k_counts(n, c, k)
    if k > c:
        return 0.0
    if k == 1:
        return c / n
    if c == n:
        return 1.0

    log_success_probability = 0.0
    for i in range(k):
        failure_fraction = (n - c) / (n - i)
        if failure_fraction >= 1.0:
            log_success_probability += math.log(c - i) - math.log(n - i)
        else:
            log_success_probability += math.log1p(-failure_fraction)
    return min(c / n, max(0.0, math.exp(log_success_probability)))


def _validate_pass_k_counts(n: int, c: int, k: int) -> tuple[int, int, int]:
    for name, value in (("n", n), ("c", c), ("k", k)):
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise ValueError(f"{name} must be an integer")
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= c <= n:
        raise ValueError("c must be between 0 and n")
    if not 1 <= k <= n:
        raise ValueError("k must be between 1 and n")
    return int(n), int(c), int(k)
