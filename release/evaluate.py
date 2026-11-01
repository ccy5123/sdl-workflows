"""Evaluate predictions on the sdl-workflows benchmark chrono2023, or reproduce its reference values.

Reads only the benchmark folder of the release (Python standard library only):
  split.csv                  benchmark_id, paper_id, split (train / test / excluded), exclusion_reason
  items_module_type.csv      items of task chrono2023-module_type
  items_transfer_mode.csv    items of task chrono2023-transfer_mode
  tasks/<task_id>.json       task definition and the recorded reference values

Usage:
  python evaluate.py DIR
      fit the baseline and the reference model on the training items, score them on the test items, and compare
      with the recorded values in tasks/*.json (exit status 1 if any differs at the fourth decimal)
  python evaluate.py DIR --predictions-out FILE
      as above, and write each test item's top-1 and top-3 of both models
  python evaluate.py DIR --task TASK_ID --predictions FILE
      score your own top-1 predictions (CSV with columns item_id, prediction; one row per test item) against the
      baseline, with the same bootstrap

Models (fitted on items with split = train; scored on split = test; excluded items are never read):
  Contexts, finest first. module_type: (unit operation, previous, next, field tag), (unit operation, previous,
  next), (unit operation, field tag), (unit operation). transfer_mode: (from unit operation, to unit operation,
  field tag), (from, to), (from family, to family, field tag), (from family, to family). Below them: all items.
  Baseline: the most frequent label of the coarsest context (unit operation; family pair); an unseen context falls
  back to the most frequent label of all items; ties alphabetical.
  Reference model: the finest context with at least MIN_COUNT training items; its most frequent label, ties broken
  by the next coarser context, then alphabetically. Top-3 continues into coarser contexts when needed.
Statistic: top-1 accuracy over the test items. 95% interval of a difference: paper-level paired cluster bootstrap,
B = 2000 replicates, each drawing as many papers as there are test papers, with replacement, by
random.Random(1).choice over the sorted test-paper list; a test paper without items in the task adds nothing; a
replicate with no item is dropped; the interval is the sorted values at positions int(0.025 n) and int(0.975 n) - 1.
"""
import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ITEM_FILES = {"chrono2023-module_type": "items_module_type.csv",
              "chrono2023-transfer_mode": "items_transfer_mode.csv"}
MIN_COUNT = 1          # recorded choice of the reference model (leave-one-paper-out on the training papers)
B, SEED = 2000, 1
DECIMALS = 4


def contexts(target, r):
    t = r["field_tag"]
    if target == "module_type":
        u, p, n = r["unit_operation"], r["prev_unit_operation"], r["next_unit_operation"]
        return [(u, p, n, t), (u, p, n), (u, t), (u,)]
    a, b, fa, fb = r["from_unit_operation"], r["to_unit_operation"], r["from_family"], r["to_family"]
    return [(a, b, t), (a, b), (fa, fb, t), (fa, fb)]


def ranking(counter, fallback):
    """Labels by count, ties by the counts of the coarser contexts given, then alphabetically."""
    return sorted(counter, key=lambda lab: tuple([-counter[lab]] + [-f.get(lab, 0) for f in fallback] + [lab]))


class Model:
    """Label counts per context, fitted on training items."""

    def __init__(self, items, min_count=MIN_COUNT):
        self.min_count = min_count
        self.lev = [defaultdict(Counter) for _ in range(4)]
        self.all = Counter()
        for it in items:
            for k in range(4):
                self.lev[k][it["ctx"][k]][it["label"]] += 1
            self.all[it["label"]] += 1

    def reference(self, it):
        """(top-1, top-3, context level used: 1 finest .. 5 all items)."""
        used = 4
        for k in range(4):
            if sum(self.lev[k].get(it["ctx"][k], Counter()).values()) >= self.min_count:
                used = k
                break
        chain = [self.lev[k].get(it["ctx"][k], Counter()) for k in range(used, 4)] + [self.all]
        top = []
        for j, c in enumerate(chain):
            for lab in ranking(c, chain[j + 1:j + 2]):
                if lab not in top:
                    top.append(lab)
            if len(top) >= 3:
                break
        return top[0], top[:3], used + 1

    def baseline(self, it):
        """(top-1, top-3)."""
        c = self.lev[3].get(it["ctx"][3], Counter())
        top = sorted(c, key=lambda lab: (-c[lab], lab))
        for lab in sorted(self.all, key=lambda lab: (-self.all[lab], lab)):
            if lab not in top:
                top.append(lab)
        return top[0], top[:3]


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_task(folder, task_id):
    """(task, items, test papers) of one task."""
    folder = Path(folder)
    task = json.loads((folder / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))
    items = []
    for r in read_csv(folder / ITEM_FILES[task_id]):
        items.append({"item": r["item_id"], "paper": r["paper_id"], "split": r["split"], "label": r["label"],
                      "ctx": contexts(task["target"], r)})
    papers = sorted(r["paper_id"] for r in read_csv(folder / "split.csv")
                    if r["benchmark_id"] == task["benchmark_id"] and r["split"] == "test")
    return task, items, papers


def bootstrap_sets(papers, seed=SEED, b=B):
    rng = random.Random(seed)
    return [[rng.choice(papers) for _ in papers] for _ in range(b)]


def interval(values):
    v = sorted(values)
    return (v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]) if v else (None, None)


def paired_difference(test, first, second, papers, sets=None):
    """Top-1 accuracy of two prediction lists over the test items, their difference and its bootstrap interval
    (sets: the bootstrap draws; by default bootstrap_sets(papers))."""
    per = defaultdict(lambda: [0, 0, 0])
    for it, p1, p2 in zip(test, first, second):
        c = per[it["paper"]]
        c[0] += 1
        c[1] += p1 == it["label"]
        c[2] += p2 == it["label"]
    diffs = []
    for s in bootstrap_sets(papers) if sets is None else sets:
        n = c1 = c2 = 0
        for p in s:
            c = per.get(p)
            if c:
                n, c1, c2 = n + c[0], c1 + c[1], c2 + c[2]
        if n:
            diffs.append((c1 - c2) / n)
    n = len(test)
    a1 = sum(p == it["label"] for it, p in zip(test, first)) / n
    a2 = sum(p == it["label"] for it, p in zip(test, second)) / n
    return a1, a2, a1 - a2, interval(diffs), len(diffs)


def evaluate(folder, task_id):
    """Baseline and reference model of one task, with per-item predictions."""
    task, items, papers = load_task(folder, task_id)
    model = Model([it for it in items if it["split"] == "train"])
    test = sorted((it for it in items if it["split"] == "test"), key=lambda it: it["item"])
    ref = [model.reference(it) for it in test]
    base = [model.baseline(it) for it in test]
    r1, b1, diff, ci, reps = paired_difference(test, [r[0] for r in ref], [b[0] for b in base], papers)
    result = {"task_id": task_id, "n_test_items": len(test), "n_test_papers": len({it["paper"] for it in test}),
              "baseline_top1": b1, "reference_model_top1": r1, "diff_ci95_low": ci[0], "diff_ci95_high": ci[1],
              "replicates": reps}
    predictions = [{"task_id": task_id, "item_id": it["item"], "paper_id": it["paper"], "label": it["label"],
                    "reference_top1": r[0], "reference_top3": ";".join(r[1]), "reference_level": r[2],
                    "baseline_top1": b[0], "baseline_top3": ";".join(b[1])}
                   for it, r, b in zip(test, ref, base)]
    return task, result, predictions


def score_predictions(folder, task_id, path):
    """Your top-1 predictions against the baseline."""
    task, items, papers = load_task(folder, task_id)
    model = Model([it for it in items if it["split"] == "train"])
    test = sorted((it for it in items if it["split"] == "test"), key=lambda it: it["item"])
    rows = read_csv(path)
    pred = {r["item_id"]: r["prediction"] for r in rows}
    ids = {it["item"] for it in test}
    if len(pred) != len(rows) or pred.keys() != ids:
        raise SystemExit(f"{path}: need exactly one row per test item ({len(ids)}); "
                         f"missing {len(ids - pred.keys())}, unknown {len(pred.keys() - ids)}, rows {len(rows)}")
    p1, b1, diff, ci, reps = paired_difference(test, [pred[it["item"]] for it in test],
                                               [model.baseline(it)[0] for it in test], papers)
    return {"task_id": task_id, "n_test_items": len(test), "predictions_top1": p1, "baseline_top1": b1,
            "difference": diff, "diff_ci95_low": ci[0], "diff_ci95_high": ci[1], "replicates": reps}


def mismatches(task, result):
    keys = ("n_test_items", "n_test_papers", "baseline_top1", "reference_model_top1", "diff_ci95_low", "diff_ci95_high")
    return [(k, task[k], result[k]) for k in keys if round(task[k], DECIMALS) != round(result[k], DECIMALS)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder", help="the benchmark folder of the release")
    ap.add_argument("--task", choices=sorted(ITEM_FILES))
    ap.add_argument("--predictions", help="CSV item_id,prediction to score (needs --task)")
    ap.add_argument("--predictions-out", help="write the per-item predictions of baseline and reference model")
    args = ap.parse_args(argv)
    if args.predictions:
        if not args.task:
            ap.error("--predictions needs --task")
        print(json.dumps(score_predictions(args.folder, args.task, args.predictions), indent=1))
        return 0
    status, rows = 0, []
    for task_id in ([args.task] if args.task else sorted(ITEM_FILES)):
        task, result, predictions = evaluate(args.folder, task_id)
        rows += predictions
        bad = mismatches(task, result)
        print(json.dumps(result, indent=1))
        print(f"{task_id}: " + ("matches the recorded values" if not bad else f"DIFFERS from the recorded values {bad}"))
        status |= bool(bad)
    if args.predictions_out:
        with open(args.predictions_out, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    return status


if __name__ == "__main__":
    sys.exit(main())
