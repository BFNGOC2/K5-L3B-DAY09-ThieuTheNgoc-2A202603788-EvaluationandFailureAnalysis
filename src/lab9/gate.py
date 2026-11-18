"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from numbers import Integral, Real
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    def inspect_report(report: dict, name: str) -> tuple[dict[tuple[str, int], dict], dict[tuple[str, int], tuple[str, ...]]]:
        manifest = report.get("manifest")
        if not isinstance(manifest, dict):
            problems.append(f"{name}: missing or invalid manifest")
            manifest = {}
        rows = report.get("rows")
        if not isinstance(rows, list):
            problems.append(f"{name}: rows must be a list")
            rows = []
        metrics = report.get("metrics")
        if not isinstance(metrics, dict):
            problems.append(f"{name}: metrics must be an object")
            metrics = {}
        for metric, value in metrics.items():
            if value is not None and (not isinstance(value, Real) or not math.isfinite(float(value))):
                problems.append(f"{name}: metric {metric} is non-finite or non-numeric")

        failures = report.get("evaluator_failures")
        if not isinstance(failures, list) or failures:
            problems.append(f"{name}: evaluator_failures must be an empty list")

        item_count = manifest.get("items")
        seeds = manifest.get("seeds")
        valid_item_count = isinstance(item_count, Integral) and not isinstance(item_count, bool) and item_count > 0
        valid_seeds = (isinstance(seeds, list) and bool(seeds)
                       and all(isinstance(seed, Integral) and not isinstance(seed, bool) for seed in seeds)
                       and len(set(seeds)) == len(seeds))
        if not valid_item_count:
            problems.append(f"{name}: manifest items must be a positive integer")
        if not valid_seeds:
            problems.append(f"{name}: manifest seeds must be unique integers")
        if valid_item_count and valid_seeds and len(rows) != item_count * len(seeds):
            problems.append(f"{name}: row count {len(rows)} != manifest {item_count} x {len(seeds)}")

        pairs: dict[tuple[str, int], dict] = {}
        slice_tags: dict[tuple[str, int], tuple[str, ...]] = {}
        for row in rows:
            if not isinstance(row, dict):
                problems.append(f"{name}: row must be an object")
                continue
            item_id, seed = row.get("item_id"), row.get("seed")
            if not isinstance(item_id, str) or not item_id:
                problems.append(f"{name}: row has invalid item_id")
                continue
            if not isinstance(seed, Integral) or isinstance(seed, bool):
                problems.append(f"{name}: row {item_id} has invalid seed")
                continue
            key = (item_id, int(seed))
            if key in pairs:
                problems.append(f"{name}: duplicate row for {item_id}@{seed}")
                continue
            pairs[key] = row
            tags = row.get("slices")
            if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                problems.append(f"{name}: {item_id}@{seed} has invalid slice tags")
                slice_tags[key] = ()
            else:
                if len(tags) != len(set(tags)):
                    problems.append(f"{name}: {item_id}@{seed} has duplicate slice tags")
                slice_tags[key] = tuple(tags)

            for metric in spec.get("metrics", []):
                metric_id = metric.get("id")
                if metric.get("grader") == "lab8.metrics.summarize":
                    continue
                value = row.get(metric_id)
                if (metric_id not in row or value is None or not isinstance(value, Real)
                        or not math.isfinite(float(value))):
                    problems.append(f"{name}: {item_id}@{seed} missing/invalid graded metric {metric_id}")

        if valid_seeds:
            declared_seeds = set(int(seed) for seed in seeds)
            unexpected = sorted(seed for _, seed in pairs if seed not in declared_seeds)
            if unexpected:
                problems.append(f"{name}: rows contain undeclared seeds {unexpected}")
        return pairs, slice_tags

    pr_pairs, pr_slices = inspect_report(pr, "PR")
    base_pairs, base_slices = inspect_report(base, "baseline")
    pr_manifest = pr.get("manifest") if isinstance(pr.get("manifest"), dict) else {}
    base_manifest = base.get("manifest") if isinstance(base.get("manifest"), dict) else {}
    if pr_manifest.get("eval_set_sha") != base_manifest.get("eval_set_sha"):
        problems.append("PR and baseline eval_set_sha differ")
    if set(pr_pairs) != set(base_pairs):
        problems.append("PR item/seed pairs differ from baseline")
    if pr_slices != base_slices:
        problems.append("PR item slice tags differ from baseline")

    for metric in spec.get("metrics", []):
        metric_id = metric.get("id")
        if metric.get("blocking"):
            for name, report in (("PR", pr), ("baseline", base)):
                metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
                if metrics.get(metric_id) is None:
                    problems.append(f"{name} missing blocking metric {metric_id}")
    for slice_entry in spec.get("slices", []):
        slice_name = slice_entry.get("name")
        if slice_entry.get("blocking"):
            for name, tags in (("PR", pr_slices), ("baseline", base_slices)):
                if not any(slice_name in item_tags for item_tags in tags.values()):
                    problems.append(f"{name} missing blocking slice {slice_name}")

    if base_spec is not None:
        if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
            problems.append("metric spec eval_set_version differs from baseline spec")

        def keyed(entries: list[dict], key: str) -> dict[str, dict]:
            result = {}
            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get(key), str):
                    name = entry[key]
                    if name in result:
                        problems.append(f"spec has duplicate {key} {name}")
                    result[name] = entry
            return result

        current_metrics = keyed(spec.get("metrics", []), "id")
        old_metrics = keyed(base_spec.get("metrics", []), "id")
        for metric_id, old in old_metrics.items():
            current = current_metrics.get(metric_id)
            if current is None:
                problems.append(f"spec removed metric {metric_id}")
                continue
            for field in ("kind", "level", "grader"):
                if old.get(field) != current.get(field):
                    problems.append(f"spec changed {metric_id} {field}")
            if old.get("blocking") and not current.get("blocking"):
                problems.append(f"spec made {metric_id} non-blocking")
            old_threshold = old.get("threshold") or {}
            new_threshold = current.get("threshold") or {}
            for field, stricter in (("min", lambda new, previous: new >= previous),
                                    ("max", lambda new, previous: new <= previous),
                                    ("max_increase", lambda new, previous: new <= previous)):
                if field in old_threshold:
                    value = new_threshold.get(field)
                    if not isinstance(value, Real) or not stricter(value, old_threshold[field]):
                        problems.append(f"spec loosened {metric_id}.{field}")
            if old_threshold.get("no_significant_drop") and not new_threshold.get("no_significant_drop"):
                problems.append(f"spec removed {metric_id}.no_significant_drop")

        current_slices = keyed(spec.get("slices", []), "name")
        old_slices = keyed(base_spec.get("slices", []), "name")
        for slice_name, old in old_slices.items():
            current = current_slices.get(slice_name)
            if current is None:
                problems.append(f"spec removed slice {slice_name}")
                continue
            if old.get("metric") != current.get("metric"):
                problems.append(f"spec changed slice {slice_name}.metric")
            if old.get("blocking") and not current.get("blocking"):
                problems.append(f"spec made slice {slice_name} non-blocking")
            if "min" in old and (not isinstance(current.get("min"), Real)
                                 or current["min"] < old["min"]):
                problems.append(f"spec loosened slice {slice_name}.min")
            if "max" in old and (not isinstance(current.get("max"), Real)
                                 or current["max"] > old["max"]):
                problems.append(f"spec loosened slice {slice_name}.max")
            if old.get("no_significant_drop") and not current.get("no_significant_drop"):
                problems.append(f"spec removed slice {slice_name}.no_significant_drop")

    return list(dict.fromkeys(problems))


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bootstrap = spec.get("bootstrap", {})
    for entry in spec.get("slices", []):
        name, metric = entry["name"], entry["metric"]
        current = per_item(pr, metric, slice_name=name)
        baseline = per_item(base, metric, slice_name=name)
        keys = sorted(current)
        verdict = "ok"
        note = ""
        value = sum(current.values()) / len(keys) if keys else None
        if not keys or keys != sorted(baseline):
            verdict = "missing"
            note = "paired slice items are missing or differ"
        else:
            if "min" in entry and value < entry["min"]:
                verdict = "fail"
            if entry.get("no_significant_drop"):
                delta, low, high = stats.paired_bootstrap(
                    [current[key] for key in keys],
                    [baseline[key] for key in keys],
                    n_resamples=bootstrap.get("n_resamples", 1000),
                    rng=bootstrap.get("rng", 2027),
                    confidence=bootstrap.get("confidence", 0.95),
                )
                note = f"Δ {delta:+.3f} CI [{low:+.3f}, {high:+.3f}]"
                if high < 0:
                    verdict = "fail"
        if verdict != "ok" and entry.get("blocking"):
            blocked.append(f"slice:{name}/{metric}")
        value_text = "MISSING" if value is None else f"{value:.4f}"
        label = "ok" if verdict == "ok" else ("BLOCK" if entry.get("blocking") else "warn")
        lines.append(f"  slice:{name}/{metric:<16} {value_text:<8} {json.dumps(entry):<56} {note:<32} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    pr_manifest = pr.get("manifest") if isinstance(pr.get("manifest"), dict) else {}
    base_manifest = base.get("manifest") if isinstance(base.get("manifest"), dict) else {}
    if pr_manifest.get("eval_set_sha") != base_manifest.get("eval_set_sha"):
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    if (pr.get("shape") == base.get("shape")
            and pr.get("metrics") == base.get("metrics")
            and pr.get("rows") == base.get("rows")):
        return [], ["  baseline-identical observations: no regression"]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(a)
            if not keys or keys != sorted(b):
                verdict = "missing"
                note = "paired item values are missing or differ"
            else:
                d, lo, hi = stats.paired_bootstrap(
                    [a[k] for k in keys], [b[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                    confidence=bs.get("confidence", 0.95),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
