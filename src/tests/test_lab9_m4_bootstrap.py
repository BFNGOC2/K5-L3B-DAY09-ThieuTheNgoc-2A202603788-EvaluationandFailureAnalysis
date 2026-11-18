import pytest

pytestmark = pytest.mark.student


def test_paired_bootstrap_detects_improvement_and_regression():
    from lab9.stats import paired_bootstrap

    improved = paired_bootstrap([1, 1, 1], [0, 0, 0])
    regressed = paired_bootstrap([0, 0, 0], [1, 1, 1])

    assert improved == (1.0, 1.0, 1.0)
    assert regressed == (-1.0, -1.0, -1.0)


def test_paired_bootstrap_is_deterministic_for_rng():
    from lab9.stats import paired_bootstrap

    inputs = ([1, 1, 0.8, 1, 0.6], [1, 0.8, 0.8, 0.6, 0.6])
    assert paired_bootstrap(*inputs, rng=88) == paired_bootstrap(*inputs, rng=88)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ([1], [1, 2]),
        ([], []),
        ([float("nan")], [0]),
        ([0], [float("inf")]),
    ],
)
def test_paired_bootstrap_rejects_invalid_samples(a, b):
    from lab9.stats import paired_bootstrap

    with pytest.raises(ValueError):
        paired_bootstrap(a, b)


@pytest.mark.parametrize("confidence", [0, 1, -0.1, 1.1, float("nan"), float("inf")])
def test_paired_bootstrap_rejects_invalid_confidence(confidence):
    from lab9.stats import paired_bootstrap

    with pytest.raises(ValueError):
        paired_bootstrap([1, 0], [0, 1], confidence=confidence)


@pytest.mark.parametrize("n_resamples", [0, -1, 1.5, True])
def test_paired_bootstrap_rejects_invalid_resample_count(n_resamples):
    from lab9.stats import paired_bootstrap

    with pytest.raises(ValueError):
        paired_bootstrap([1, 0], [0, 1], n_resamples=n_resamples)
