"""Label distribution and a majority-class rule for the configuration prediction of the main split (fit on papers up
to 2023, evaluate on the evaluated papers from 2024). Python standard library only.

  python3 config_class_distribution.py --db PATH/sdl-db.sqlite --out out

Reuses ../02_configuration_prediction (model.py, prepare.py, evaluate.py) unchanged and reads its out/m_selection.json.
Items, sets, model, baseline and bootstrap are those of evaluate.py split 'main'. The majority-class rule assigns to
every evaluation item the most frequent label among the fitting-side items of that label (ties alphabetically, as the
L5 level of model.py). Intervals: the paper-level paired cluster bootstrap of evaluate.py (B = 2000,
random.Random(1).choice over the sorted list of the 99 evaluated papers; papers with no item of a label are drawn and
add nothing; 95% percentile interval at positions int(0.025 n) and int(0.975 n) - 1).

Outputs: out/config_class_distribution.json (accuracies, differences and intervals per label) and
out/config_class_counts.csv (items and share per label value on the fitting and evaluation sides).
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "02_configuration_prediction"
sys.path.insert(0, str(SRC))
from evaluate import SPLITS, boot_sets, fit, pct, predict, split  # noqa: E402
from model import FIELDS, load_items  # noqa: E402
from prepare import open_db  # noqa: E402


def main(dbpath, out):
    m = json.loads((SRC / "out" / "m_selection.json").read_text(encoding="utf-8"))["m"]
    side = SPLITS["main"]["side"]
    db = open_db(dbpath)
    papers = {p: side(y, e) for p, y, e in db.execute("SELECT paper_id, first_public_year, era FROM v_era")}
    gold = dict(db.execute("SELECT paper_id, gold_set FROM gold_membership").fetchall())
    eval_papers = sorted(p for p, s in papers.items() if s == "test" and gold.get(p) != "dev")
    items, _ = load_items(db)
    sp = split(items, side)
    train, test = sp["train"], sp["test"]
    models = fit(train, m)
    ev = {f: [it for it in test[f] if it["paper"] in set(eval_papers)] for f in FIELDS}
    rows = predict(models, models, ev, "evaluated")
    sets = boot_sets(eval_papers)

    res = {"split": "main", "m": m, "bootstrap": {"B": len(sets), "seed": 1, "papers_resampled": len(eval_papers)},
           "labels": {}}
    count_rows = []
    for f in FIELDS:
        tr = Counter(it["y"] for it in train[f])
        te = Counter(it["y"] for it in ev[f])
        majority = sorted(tr, key=lambda lab: (-tr[lab], lab))[0]
        fr = [r for r in rows if r["field"] == f]
        n = len(fr)
        acc = {"model": sum(r["model"] == r["y"] for r in fr) / n,
               "baseline": sum(r["base"] == r["y"] for r in fr) / n,
               "majority": sum(majority == r["y"] for r in fr) / n}
        pp = {}
        for r in fr:
            c = pp.setdefault(r["paper"], [0, 0, 0, 0])
            c[0] += 1
            c[1] += r["model"] == r["y"]
            c[2] += r["base"] == r["y"]
            c[3] += majority == r["y"]
        reps = {k: [] for k in ("model", "baseline", "majority", "model_minus_majority", "baseline_minus_majority",
                                "model_minus_baseline")}
        for s in sets:
            t = [0, 0, 0, 0]
            for p in s:
                c = pp.get(p)
                if c:
                    t = [a + b for a, b in zip(t, c)]
            if t[0]:
                reps["model"].append(t[1] / t[0])
                reps["baseline"].append(t[2] / t[0])
                reps["majority"].append(t[3] / t[0])
                reps["model_minus_majority"].append((t[1] - t[3]) / t[0])
                reps["baseline_minus_majority"].append((t[2] - t[3]) / t[0])
                reps["model_minus_baseline"].append((t[1] - t[2]) / t[0])
        ci = {k: list(pct(sorted(v))) for k, v in reps.items()}
        res["labels"][f] = {
            "fitting_items": len(train[f]), "fitting_papers": len({it["paper"] for it in train[f]}),
            "evaluation_items": n, "evaluation_papers": len({r["paper"] for r in fr}),
            "majority_label": majority,
            "accuracy": {k: {"value": v, "ci95": ci[k]} for k, v in acc.items()},
            "difference": {"model_minus_majority": {"value": acc["model"] - acc["majority"],
                                                    "ci95": ci["model_minus_majority"]},
                           "baseline_minus_majority": {"value": acc["baseline"] - acc["majority"],
                                                       "ci95": ci["baseline_minus_majority"]},
                           "model_minus_baseline": {"value": acc["model"] - acc["baseline"],
                                                    "ci95": ci["model_minus_baseline"]}},
            "replicates": len(reps["model"]),
            "counts": {"fitting": dict(tr.most_common()), "evaluation": dict(te.most_common())}}
        for lab in sorted(set(tr) | set(te), key=lambda lab: (-tr[lab], -te[lab], lab)):
            count_rows.append({"label": f, "value": lab, "fitting_items": tr[lab],
                               "fitting_share": f"{tr[lab] / len(train[f]):.6f}", "evaluation_items": te[lab],
                               "evaluation_share": f"{te[lab] / n:.6f}"})
    out.mkdir(parents=True, exist_ok=True)
    (out / "config_class_distribution.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    with open(out / "config_class_counts.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(count_rows[0]))
        w.writeheader()
        w.writerows(count_rows)
    for f in FIELDS:
        x = res["labels"][f]
        print(f, x["evaluation_items"], x["majority_label"],
              {k: round(v["value"], 4) for k, v in x["accuracy"].items()},
              {k: (round(v["value"], 4), [round(c, 4) for c in v["ci95"]]) for k, v in x["difference"].items()})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="SQLite build of the database (opened read-only)")
    ap.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args()
    main(a.db, Path(a.out))
