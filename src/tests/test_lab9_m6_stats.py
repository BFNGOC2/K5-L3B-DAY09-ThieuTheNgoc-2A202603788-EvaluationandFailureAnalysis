import math

import pytest

from lab9.stats import pass_at_k, pass_hat_k


pytestmark = pytest.mark.student


@pytest.mark.parametrize(
    ("n", "c", "k"),
    [(5, 5, 5), (5, 0, 3), (10, 3, 1), (10, 3, 3), (1000, 1, 5)],
)
def test_pass_k_probabilities_are_bounded_and_ordered(n, c, k):
    at_k = pass_at_k(n, c, k)
    hat_k = pass_hat_k(n, c, k)

    assert 0.0 <= hat_k <= 1.0
    assert 0.0 <= at_k <= 1.0
    assert hat_k <= c / n <= at_k


@pytest.mark.parametrize(
    ("n", "c", "k", "at_k", "hat_k"),
    [(5, 2, 1, 0.4, 0.4), (10, 3, 3, 1 - 35 / 120, 1 / 120),
     (10, 8, 2, 1 - 1 / 45, 28 / 45), (5, 4, 5, 1.0, 0.0)],
)
def test_pass_k_reference_values(n, c, k, at_k, hat_k):
    assert math.isclose(pass_at_k(n, c, k), at_k, abs_tol=1e-12)
    assert math.isclose(pass_hat_k(n, c, k), hat_k, abs_tol=1e-12)


@pytest.mark.parametrize(
    ("n", "c", "k"),
    [(0, 0, 1), (5, -1, 1), (5, 6, 1), (5, 2, 0), (5, 2, 6),
     (True, 1, 1), (5, 1.5, 1), (5, 1, False)],
)
def test_pass_k_rejects_invalid_counts(n, c, k):
    with pytest.raises(ValueError):
        pass_at_k(n, c, k)
    with pytest.raises(ValueError):
        pass_hat_k(n, c, k)
