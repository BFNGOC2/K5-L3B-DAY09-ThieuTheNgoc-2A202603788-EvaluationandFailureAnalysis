import copy

import pytest

from lab9 import gate


pytestmark = pytest.mark.student


def _report(rows, pass_rate, *, run_id="run"):
    return {
        "run_id": run_id,
        "shape": "swarm",
        "manifest": {"eval_set_sha": "same", "items": len({r["item_id"] for r in rows}),
                     "seeds": [1, 2]},
        "rows": rows,
        "metrics": {"pass_rate": pass_rate},
        "evaluator_failures": [],
    }


def _rows(values, tagged=("E-001", "E-002")):
    return [
        {"item_id": f"E-{item:03d}", "seed": seed, "pass_rate": value,
         "slices": ["money_movement"] if f"E-{item:03d}" in tagged else []}
        for item, value in enumerate(values, 1)
        for seed in (1, 2)
    ]


_METRIC = {"id": "pass_rate", "kind": "capability", "blocking": True,
           "threshold": {"min": 0.5}}


def test_slice_floor_uses_paired_items_in_that_slice():
    baseline = _report(_rows([True, True, True]), 1.0)
    pr = _report(_rows([False, False, True]), 1 / 3)
    spec = {"metrics": [_METRIC], "bootstrap": {"n_resamples": 200, "rng": 7},
            "slices": [{"name": "money_movement", "metric": "pass_rate",
                        "min": 0.75, "no_significant_drop": True, "blocking": True}]}

    blocked, lines = gate.check(pr, baseline, spec)

    assert "slice:money_movement/pass_rate" in blocked
    assert any("CI [" in line for line in lines)


def test_missing_blocking_slice_is_an_integrity_failure():
    rows = _rows([True, True], tagged=())
    report = _report(rows, 1.0)
    spec = {"metrics": [_METRIC], "slices": [{"name": "money_movement", "metric": "pass_rate",
                                              "min": 0.5, "blocking": True}]}

    blocked, lines = gate.check(report, report, spec)

    assert blocked == ["integrity"]
    assert any("missing blocking slice" in line for line in lines)


@pytest.mark.parametrize("mutate", [
    lambda r: r["rows"].pop(),
    lambda r: r["rows"].append(copy.deepcopy(r["rows"][0])),
    lambda r: r["metrics"].update(pass_rate=float("nan")),
    lambda r: r["evaluator_failures"].append("grader crashed"),
    lambda r: r["rows"][0].update(pass_rate=None),
])
def test_integrity_rejects_broken_or_missing_observations(mutate):
    baseline = _report(_rows([True, True]), 1.0)
    pr = copy.deepcopy(baseline)
    mutate(pr)

    assert gate.integrity_check(pr, baseline, {"metrics": [_METRIC]})


def test_integrity_rejects_slice_relabeling():
    baseline = _report(_rows([True, True]), 1.0)
    pr = copy.deepcopy(baseline)
    pr["rows"][0]["slices"] = []

    assert any("slice tags differ" in problem
               for problem in gate.integrity_check(pr, baseline, {"metrics": [_METRIC]}))


def test_ratchet_rejects_removed_metrics_and_looser_slice_thresholds():
    baseline_spec = {
        "eval_set_version": "v2",
        "metrics": [_METRIC],
        "slices": [{"name": "money_movement", "metric": "pass_rate", "min": 0.8,
                    "no_significant_drop": True, "blocking": True}],
    }
    looser = copy.deepcopy(baseline_spec)
    looser["metrics"] = []
    looser["slices"][0]["min"] = 0.6

    problems = gate.integrity_check(
        _report(_rows([True, True]), 1.0),
        _report(_rows([True, True]), 1.0),
        looser,
        baseline_spec,
    )

    assert any("removed metric pass_rate" in problem for problem in problems)
    assert any("loosened slice money_movement.min" in problem for problem in problems)


def test_identical_baseline_is_no_regression_even_if_its_floor_is_below_threshold():
    report = _report(_rows([False, False]), 0.0)
    spec = {"metrics": [{**_METRIC, "threshold": {"min": 0.9}}]}

    blocked, lines = gate.check(report, copy.deepcopy(report), spec)

    assert blocked == []
    assert "baseline-identical observations: no regression" in lines[0]
