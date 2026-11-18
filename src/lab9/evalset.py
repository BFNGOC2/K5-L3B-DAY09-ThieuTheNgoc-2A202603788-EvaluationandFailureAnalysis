"""Eval sets: items and labels live in separate files; every item records provenance.

Build it once from the Lab 8 public claims:  python -m lab9.evalset --build
Check it:                                    python -m lab9.evalset --check
Build/check v2:                              python -m lab9.evalset --v2 --build
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ITEMS = Path("data/eval/eval_set_v1.jsonl")
LABELS = Path("data/eval/labels_v1.json")
SOURCE = Path("data/public_claims.jsonl")
FAILURE_MODE_MAP = Path("data/eval/failure_modes_v1.json")
VERSION = "v1"
ITEMS_V2 = Path("data/eval/eval_set_v2.jsonl")
LABELS_V2 = Path("data/eval/labels_v2.json")
PACK = Path("data/eval/adversarial_v2.json")
FM_MAP = Path("config/fm_map.yaml")
MIN_PER_MODE_V2 = 3   # v2 rule: a failure mode with < 3 items cannot show a trend, only an anecdote
# Fields an item must carry. Labels never go inline: a grader that can read the
# answer next to the input is a grader that can be fooled by it.
REQUIRED = ("item_id", "claim_id", "failure_modes", "provenance", "split", "eval_set_version")


FM_CODE = re.compile(r"FM-\d{2}")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def build(source: Path = SOURCE) -> tuple[int, int]:
    claims = load_jsonl(source)
    has_failure_mode_map = FAILURE_MODE_MAP.is_file()
    failure_mode_map = (
        json.loads(FAILURE_MODE_MAP.read_text(encoding="utf-8"))
        if has_failure_mode_map else {}
    )
    if has_failure_mode_map:
        claim_ids = {claim["claim_id"] for claim in claims}
        missing = claim_ids - failure_mode_map.keys()
        unknown = failure_mode_map.keys() - claim_ids
        if missing or unknown:
            raise ValueError(
                f"{FAILURE_MODE_MAP} claim IDs differ from {source}: "
                f"missing={sorted(missing)}, unknown={sorted(unknown)}"
            )

    items, labels = [], {}
    for n, claim in enumerate(claims, start=1):
        item_id = f"E-{n:03d}"
        assignment = failure_mode_map.get(claim["claim_id"], {})
        failure_modes = assignment.get("failure_modes", [])
        if has_failure_mode_map and (not isinstance(failure_modes, list) or not failure_modes):
            raise ValueError(f"{FAILURE_MODE_MAP}: {claim['claim_id']} needs failure_modes")
        items.append({
            "item_id": item_id,
            "claim_id": claim["claim_id"],
            "failure_modes": failure_modes,
            "provenance": {"source": "lab8_public", "matrix_id": claim.get("matrix_id"),
                           "from_trace": assignment.get("from_trace"),
                           "generator": "lab9.trace_case" if assignment.get("from_trace") else None,
                           "label_by": "lab8_matrix",
                           "checked_by": "M1 trace review" if assignment.get("from_trace") else None},
            "split": "regression",
            "eval_set_version": VERSION,
        })
        labels[claim["claim_id"]] = claim["expected"]
    ITEMS.parent.mkdir(parents=True, exist_ok=True)
    ITEMS.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    LABELS.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(items), len(labels)


def slices_for(expected: dict[str, Any], adversarial: bool) -> list[str]:
    """Slice tags derived from the label (never from the agent's output), used by the M5 slice gate."""
    tags = []
    if (expected.get("refund_vnd") or 0) > 0:
        tags.append("money_movement")
    if expected.get("status") == "denied":
        tags.append("denial")
    if expected.get("status") == "escalated":
        tags.append("escalation")
    if adversarial:
        tags.append("adversarial")
    return tags


def build_v2(items_v1: Path = ITEMS, labels_v1: Path = LABELS, pack: Path = PACK,
             fm_map: Path = FM_MAP) -> tuple[int, int]:
    """v2 = your v1 items (with YOUR failure_modes from M1) + the instructor's adversarial pack.
    Pack items name an attack *mechanism*; config/fm_map.yaml translates it to your FM code."""
    import yaml
    mapping = yaml.safe_load(fm_map.read_text(encoding="utf-8")) or {}
    base = load_jsonl(items_v1)
    labels = json.loads(labels_v1.read_text(encoding="utf-8"))
    p = json.loads(pack.read_text(encoding="utf-8"))
    mechanisms = {mechanism for claim in p["claims"] for mechanism in claim["mechanisms"]}
    missing = mechanisms - mapping.keys()
    unknown = mapping.keys() - mechanisms
    if missing or unknown:
        raise ValueError(
            f"{fm_map} mechanisms differ from {pack}: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
    invalid = {mechanism: fm for mechanism, fm in mapping.items()
               if not isinstance(fm, str) or not FM_CODE.fullmatch(fm)}
    if invalid:
        raise ValueError(f"{fm_map} contains invalid failure-mode codes: {invalid}")

    items = [{**it, "eval_set_version": "v2", "slices": slices_for(labels[it["claim_id"]], False)} for it in base]
    for claim in p["claims"]:
        items.append({
            "item_id": f"E-{claim['claim_id'][2:]}",   # C-105 -> E-105
            "claim_id": claim["claim_id"],
            "failure_modes": list(dict.fromkeys(mapping[m] for m in claim["mechanisms"])),
            "provenance": {"source": "instructor_adversarial", "matrix_id": None, "from_trace": None,
                           "generator": f"attack:{claim['attack']}", "label_by": "instructor",
                           "checked_by": "fixed_shape_replay"},
            "split": "adversarial",
            "eval_set_version": "v2",
            "slices": slices_for(claim["expected"], True),
        })
        labels[claim["claim_id"]] = claim["expected"]
    ITEMS_V2.parent.mkdir(parents=True, exist_ok=True)
    ITEMS_V2.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    LABELS_V2.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(items), len(labels)


def check(items_path: Path = ITEMS, labels_path: Path = LABELS) -> list[str]:
    problems: list[str] = []
    items = load_jsonl(items_path)
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    for item in items:
        missing = [k for k in REQUIRED if k not in item]
        if missing:
            problems.append(f"{item.get('item_id')}: missing {missing}")
        provenance = item.get("provenance")
        if not isinstance(provenance, dict) or not provenance.get("source") or not provenance.get("label_by"):
            problems.append(f"{item.get('item_id')}: incomplete provenance")
        if "expected" in item or "label" in item:
            problems.append(f"{item['item_id']}: inline label")
        if item.get("claim_id") not in labels:
            problems.append(f"{item['item_id']}: no label for {item.get('claim_id')}")
        failure_modes = item.get("failure_modes")
        if not isinstance(failure_modes, list) or not failure_modes:
            problems.append(f"{item['item_id']}: failure_modes empty (fill from taxonomy)")
        problems += [f"{item['item_id']}: duplicate failure mode" for fm in set(failure_modes or [])
                     if (failure_modes or []).count(fm) > 1]
        problems += [f"{item['item_id']}: {fm} (fill config/fm_map.yaml)"
                     for fm in failure_modes or [] if str(fm).startswith("UNMAPPED:")]
        problems += [f"{item['item_id']}: {fm!r} is not a failure-mode code like FM-03"
                     for fm in failure_modes or []
                     if not str(fm).startswith("UNMAPPED:") and not FM_CODE.fullmatch(str(fm))]
        if items_path == ITEMS_V2 or item.get("eval_set_version") == "v2":
            if item.get("split") not in {"regression", "adversarial"}:
                problems.append(f"{item.get('item_id')}: invalid v2 split {item.get('split')!r}")
            claim_labels = labels.get(item.get("claim_id"))
            if isinstance(claim_labels, dict):
                want_slices = slices_for(claim_labels, item.get("split") == "adversarial")
                if item.get("slices") != want_slices:
                    problems.append(f"{item.get('item_id')}: slices do not match label-derived slices")
    ids = [it.get("item_id") for it in items]
    problems += [f"{i}: duplicate item_id" for i in sorted({i for i in ids if ids.count(i) > 1})]
    cids = [it.get("claim_id") for it in items]
    problems += [f"{c}: claim appears in more than one item" for c in sorted({c for c in cids if cids.count(c) > 1})]
    problems += [f"{c}: label has no corresponding item" for c in sorted(labels.keys() - set(cids))]
    v2 = items_path == ITEMS_V2 or any(it.get("eval_set_version") == "v2" for it in items)
    if v2:
        problems += [f"{it.get('item_id')}: eval_set_version {it.get('eval_set_version')!r}, want 'v2'"
                     for it in items if it.get("eval_set_version") != "v2"]
        # v2 must be a superset: every v1 claim and every adversarial-pack claim, pack items in the
        # adversarial split. Dropping hard items is the cheapest way to make a number go up.
        want_v1 = {it["claim_id"] for it in load_jsonl(ITEMS)} if ITEMS.is_file() else set()
        pack = json.loads(PACK.read_text(encoding="utf-8")) if PACK.is_file() else {"claims": []}
        want_adv = {c["claim_id"] for c in pack["claims"]}
        have = set(cids)
        problems += [f"{c}: v1 claim missing from v2" for c in sorted(want_v1 - have)]
        problems += [f"{c}: adversarial claim missing from v2" for c in sorted(want_adv - have)]
        problems += [f"{it['item_id']}: pack claim not in adversarial split"
                     for it in items if it.get("claim_id") in want_adv and it.get("split") != "adversarial"]
        problems += [f"{it['item_id']}: adversarial split but not a pack claim"
                     for it in items if it.get("split") == "adversarial" and it.get("claim_id") not in want_adv]
    if v2:
        # The >= 3 rule applies to every mode the adversarial split exercises.
        attacked = {fm for it in items if it.get("split") == "adversarial" for fm in it.get("failure_modes") or []}
        count: dict[str, int] = {}
        for item in items:
            for fm in set(item.get("failure_modes") or []):
                count[fm] = count.get(fm, 0) + 1
        problems += [f"{fm}: only {c} item(s) in v2, need >= {MIN_PER_MODE_V2}"
                     for fm, c in sorted(count.items()) if fm in attacked and c < MIN_PER_MODE_V2]
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab9.evalset")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--v2", action="store_true", help="build/check eval set v2 (v1 + adversarial pack)")
    args = ap.parse_args(argv)
    if args.v2:
        if args.build:
            n_items, n_labels = build_v2()
            print(f"wrote {ITEMS_V2} ({n_items} items) and {LABELS_V2} ({n_labels} labels)")
        problems = check(ITEMS_V2, LABELS_V2)
        for p in problems:
            print("FAIL", p)
        print(f"eval set v2 {sha12(ITEMS_V2)}: {len(problems)} problem(s)")
        return 1 if problems else 0
    if args.build:
        n_items, n_labels = build()
        print(f"wrote {ITEMS} ({n_items} items) and {LABELS} ({n_labels} labels)")
        if not args.check:
            return 0
    problems = check()
    for p in problems:
        print("FAIL", p)
    print(f"eval set {sha12(ITEMS)}: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
