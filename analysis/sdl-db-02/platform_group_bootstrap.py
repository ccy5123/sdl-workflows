"""Post-hoc sensitivity analysis of the chrono2023 benchmark interval: resample groups of test papers that share a
physical platform instead of single papers.

The pre-registered interval resamples test papers (evaluate.py in the release). Papers that report the same
physical platform (release column platform.identity_id) are not independent, so this script joins test papers into
groups (two papers fall in one group when any of their platforms share an identity_id, transitively) and draws
groups with replacement. Everything else is as in evaluate.py: same predictions, B = 2000, random.Random(1).

Reads only the public release folder. Usage:
  python3 analysis/sdl-db-02/platform_group_bootstrap.py release/out/sdl-workflows-1.1.0 [OUT_JSON]
"""
import csv
import importlib.util
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

bundle = Path(sys.argv[1])
out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
bench = bundle / "modes" / "benchmark"
spec = importlib.util.spec_from_file_location("evaluate", bench / "evaluate.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

parent = {}


def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    parent[find(a)] = find(b)


with open(bundle / "core" / "platform.csv", encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        paper = r["platform_id"].split("/")[0]
        union("paper:" + paper, "identity:" + r["identity_id"])

result = {"bundle": bundle.name, "B": ev.B, "seed": ev.SEED, "tasks": {}}
for task_id in ("chrono2023-module_type", "chrono2023-transfer_mode"):
    task, items, papers = ev.load_task(bench, task_id)
    _, res, preds = ev.evaluate(bench, task_id)
    test = sorted((it for it in items if it["split"] == "test"), key=lambda it: it["item"])
    ref = [p["reference_top1"] for p in preds]
    base = [p["baseline_top1"] for p in preds]

    groups = defaultdict(list)
    for p in papers:
        groups[find("paper:" + p)].append(p)
    keys = sorted(groups, key=lambda k: sorted(groups[k])[0])
    rng = random.Random(ev.SEED)
    sets = [[p for g in (rng.choice(keys) for _ in keys) for p in groups[g]] for _ in range(ev.B)]
    r1, b1, diff, ci, reps = ev.paired_difference(test, ref, base, papers, sets=sets)
    multi = [sorted(v) for v in groups.values() if len(v) > 1]
    result["tasks"][task_id] = {
        "n_test_items": len(test), "n_test_papers": len(papers), "n_groups": len(keys),
        "groups_with_several_papers": len(multi), "papers_in_such_groups": sum(len(v) for v in multi),
        "reference_model_top1": r1, "baseline_top1": b1, "difference": diff,
        "paper_bootstrap_ci95": [res["diff_ci95_low"], res["diff_ci95_high"]],
        "platform_group_bootstrap_ci95": list(ci), "replicates": reps,
    }
text = json.dumps(result, indent=1)
print(text)
if out:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
