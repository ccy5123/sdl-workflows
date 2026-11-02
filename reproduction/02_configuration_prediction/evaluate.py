"""Temporal evaluation of the configuration model against its baseline (Python standard library only).

  python3 evaluate.py --db PATH/sdl-db.sqlite --out out main            fit on papers first made public in or before
                                                                        2023, evaluate on 2024 or later -> out/evaluation/
  python3 evaluate.py --db PATH/sdl-db.sqlite --out out temporal-2019   reads only papers up to 2023; fit on papers up
                                                                        to 2019, evaluate on 2020-2023 -> out/temporal_2019/
Both splits run the same code. m per label is read from out/m_selection.json (written by prepare.py select-m). The
model and baselines are model.py.

Sets. Fitting side: papers up to 2023 (main) or up to 2019 (temporal-2019). Evaluation side: papers from 2024 (main)
or 2020-2023 (temporal-2019). Evaluated papers = evaluation-side papers that were not used in developing the coding
guideline (gold_membership.gold_set = 'dev'); development papers = the evaluation-side papers that were; papers without
a year are on neither side.

Accuracy: per label, model and baseline top-1 accuracy pooled over all items of the evaluated papers. Interval:
paper-level paired cluster bootstrap, B = 2000 replicates, each drawing len(papers) papers with replacement by
random.Random(1).choice over the sorted paper list (papers with no item of a label are drawn and add nothing); a
replicate in which a label has zero items is dropped for that label; 95% percentile interval = sorted values at
positions int(0.025 * n) and int(0.975 * n) - 1.
Shuffled labels (negative control): fitting-side labels shuffled with random.Random(20261024), module types first
(items in sorted (paper, platform, item) order), then transfer modes; model refitted with the same m on the shuffled
labels, baseline on the original labels; same evaluated papers and bootstrap.
Also reported: the same comparison with the development papers added; without the evaluated papers that have a
platform in a platform-identity group that also holds a fitting-side paper's platform; and on the independent
reference codings (coding.role = 'reference') of the evaluation-side test papers (gold_membership.gold_set = 'test'),
read through TEMP views with the v_step / v_connection definitions over those codings. Top-3 accuracy and macro-F1
(over the classes in the truth or the predictions) are given with each comparison.
Outputs (out/<split>/): predictions.csv (one row per item and set) and results.json.
"""
import argparse
import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import FIELDS, Model, load_items  # noqa: E402
from prepare import open_db  # noqa: E402

B, BOOT_SEED, SHUFFLE_SEED = 2000, 1, 20261024
SPLITS = {
    "temporal-2019": {"era_only": "train", "dir": "temporal_2019",
                      "side": lambda y, e: None if y is None else ("train" if y <= 2019 else "test")},
    "main": {"era_only": None, "dir": "evaluation", "side": lambda y, e: e},
}


# ---------- statistics ----------
def key(it):
    return (it["paper"], it["platform"], str(it["item"]))


def pct(v):
    """95% percentile interval of a sorted list."""
    return (v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]) if v else (None, None)


def boot_sets(papers, seed=BOOT_SEED, b=B):
    rng = random.Random(seed)
    return [[rng.choice(papers) for _ in papers] for _ in range(b)]


def per_paper(rows):
    """{label: {paper: [items, model correct, baseline correct]}}."""
    pp = {f: {} for f in FIELDS}
    for r in rows:
        c = pp[r["field"]].setdefault(r["paper"], [0, 0, 0])
        c[0] += 1
        c[1] += r["model"] == r["y"]
        c[2] += r["base"] == r["y"]
    return pp


def boot(rows, sets):
    """Per label: replicates kept and the 95% intervals of model, baseline and difference."""
    pp = per_paper(rows)
    res = {}
    for f in FIELDS:
        d, t, b = [], [], []
        for s in sets:
            n = ct = cb = 0
            for p in s:
                c = pp[f].get(p)
                if c:
                    n, ct, cb = n + c[0], ct + c[1], cb + c[2]
            if n:
                t.append(ct / n)
                b.append(cb / n)
                d.append((ct - cb) / n)
        res[f] = {"replicates": len(d), "diff_ci95": pct(sorted(d)), "model_ci95": pct(sorted(t)),
                  "baseline_ci95": pct(sorted(b))}
    return res


def macro_f1(rows, k):
    classes = {r["y"] for r in rows} | {r[k] for r in rows}
    f1 = []
    for c in sorted(classes):
        tp = sum(r["y"] == c and r[k] == c for r in rows)
        fp = sum(r[k] == c and r["y"] != c for r in rows)
        fn = sum(r["y"] == c and r[k] != c for r in rows)
        f1.append(2 * tp / (2 * tp + fp + fn))
    return sum(f1) / len(f1) if f1 else None


def describe(rows):
    n = len(rows)
    if not n:
        return {"items": 0}
    model = sum(r["model"] == r["y"] for r in rows) / n
    base = sum(r["base"] == r["y"] for r in rows) / n
    return {"items": n, "papers": len({r["paper"] for r in rows}), "model": model, "baseline": base, "diff": model - base,
            "model_top3": sum(r["y"] in r["model3"] for r in rows) / n,
            "baseline_top3": sum(r["y"] in r["base3"] for r in rows) / n,
            "model_macro_f1": macro_f1(rows, "model"), "baseline_macro_f1": macro_f1(rows, "base")}


def compare(rows, sets):
    ci = boot(rows, sets)
    return {f: {**describe([r for r in rows if r["field"] == f]), **ci[f]} for f in FIELDS}


# ---------- data ----------
def shadow(path, role):
    """Read-only connection whose TEMP views v_step / v_connection repeat the database's view definitions over the
    codings of `role` (instruction extraction/prompt-v1.md); v_era is the database's."""
    con = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    r = (f"(SELECT paper_id, coding_id FROM main.coding WHERE role = '{role}' "
         "AND prompt_path = 'extraction/prompt-v1.md') r")
    con.execute(f"""CREATE TEMP VIEW v_step AS
      SELECT r.paper_id, s.coding_id, s.platform_id, s.step_id, s.step_order,
             s.unit_operation, u.family, s.performed_by,
             sm.module_id AS primary_module_id, m.module_type AS primary_module_type, m.on_platform,
             e.first_public_year, e.era,
             (SELECT tag.field_tag FROM main.coding_field_tag tag
               WHERE tag.coding_id = r.coding_id AND tag.position = 1) AS first_field_tag,
             EXISTS (SELECT 1 FROM main.item_flag f WHERE f.coding_id = s.coding_id AND f.item_id = s.step_id) AS uncertain
      FROM {r}
      JOIN main.step s ON s.coding_id = r.coding_id
      JOIN main.unit_operation u ON u.unit_operation = s.unit_operation
      LEFT JOIN main.step_module sm ON sm.coding_id = s.coding_id AND sm.step_id = s.step_id AND sm.position = 1
      LEFT JOIN main.module m ON m.coding_id = sm.coding_id AND m.module_id = sm.module_id
      JOIN main.v_era e ON e.paper_id = r.paper_id""")
    con.execute(f"""CREATE TEMP VIEW v_connection AS
      SELECT r.paper_id, c.coding_id, c.platform_id, c.edge_id, c.from_module, c.to_module,
             c.transfer_mode, t.is_material, c.stated,
             mf.module_type AS from_module_type, mt.module_type AS to_module_type,
             e.first_public_year, e.era,
             EXISTS (SELECT 1 FROM main.item_flag f WHERE f.coding_id = c.coding_id AND f.item_id = c.edge_id) AS uncertain
      FROM {r}
      JOIN main.connection c ON c.coding_id = r.coding_id
      JOIN main.transfer_mode t ON t.transfer_mode = c.transfer_mode
      JOIN main.module mf ON mf.coding_id = c.coding_id AND mf.module_id = c.from_module
      JOIN main.module mt ON mt.coding_id = c.coding_id AND mt.module_id = c.to_module
      JOIN main.v_era e ON e.paper_id = r.paper_id""")
    return con


def items_key_set(items):
    return {f: sorted((key(it), it["y"], tuple(it["ctx"])) for it in items[f]) for f in FIELDS}


def split(items, side):
    out = {"train": {f: [] for f in FIELDS}, "test": {f: [] for f in FIELDS}}
    for f in FIELDS:
        for it in items[f]:
            s = side(it["year"], it["era"])
            if s in out:
                out[s][f].append(it)
    for s in out:
        for f in FIELDS:
            out[s][f].sort(key=key)
            assert len({key(it) for it in out[s][f]}) == len(out[s][f]), "duplicate item key"
    return out


def fit(train, m, labels=None):
    return {f: Model(train[f] if labels is None else labels[f], m[f]) for f in FIELDS}


def predict(models, base_models, items_by_field, set_name):
    rows = []
    for f in FIELDS:
        for it in items_by_field[f]:
            t1, t3, lev = models[f].predict(it)
            b1, b3 = base_models[f].baseline(it)
            rows.append({"set": set_name, "field": f, "paper": it["paper"], "it": it, "y": it["y"],
                         "model": t1, "model3": t3, "level": lev, "base": b1, "base3": b3})
    return rows


def shuffled_labels(train):
    rng = random.Random(SHUFFLE_SEED)
    out = {}
    for f in FIELDS:  # module types first
        labs = [it["y"] for it in train[f]]
        rng.shuffle(labs)
        out[f] = [{**it, "y": lab} for it, lab in zip(train[f], labs)]
    return out


# ---------- the run ----------
def run(split_name, dbpath, out):
    cfg = SPLITS[split_name]
    era_only, side = cfg["era_only"], cfg["side"]
    m = json.loads((out / "m_selection.json").read_text(encoding="utf-8"))["m"]
    od = out / cfg["dir"]
    od.mkdir(parents=True, exist_ok=True)
    db = open_db(dbpath)
    where = " WHERE era = ?" if era_only else ""
    arg = (era_only,) if era_only else ()
    papers = {p: side(y, e) for p, y, e in db.execute("SELECT paper_id, first_public_year, era FROM v_era" + where, arg)}
    gold = dict(db.execute("SELECT g.paper_id, g.gold_set FROM gold_membership g JOIN v_era e ON e.paper_id = g.paper_id"
                           + (" WHERE e.era = ?" if era_only else ""), arg).fetchall())
    eval_papers = sorted(p for p, s in papers.items() if s == "test" and gold.get(p) != "dev")
    dev_papers = sorted(p for p, s in papers.items() if s == "test" and gold.get(p) == "dev")
    ref_papers = sorted(p for p, s in papers.items() if s == "test" and gold.get(p) == "test")

    items, _ = load_items(db, era_only=era_only)
    sh = shadow(dbpath, "extractor_a")
    assert items_key_set(load_items(sh, era_only=era_only)[0]) == items_key_set(items), "TEMP views differ from the DB views"
    sp = split(items, side)
    train, test = sp["train"], sp["test"]
    models = fit(train, m)
    shuffled_models = fit(train, m, shuffled_labels(train))
    by_set = {"evaluated": {f: [it for it in test[f] if it["paper"] in set(eval_papers)] for f in FIELDS},
              "development": {f: [it for it in test[f] if it["paper"] in set(dev_papers)] for f in FIELDS}}
    rows = predict(models, models, by_set["evaluated"], "evaluated")
    sh_rows = predict(shuffled_models, models, by_set["evaluated"], "evaluated")
    dev_rows = predict(models, models, by_set["development"], "development")
    sets_eval = boot_sets(eval_papers)
    res = {"split": split_name, "m": m, "bootstrap": {"B": B, "seed": BOOT_SEED},
           "papers": {"fitting_side": sum(1 for s in papers.values() if s == "train"), "evaluated": len(eval_papers),
                      "development": len(dev_papers), "reference_coded": len(ref_papers),
                      "no_year_or_outside": sum(1 for s in papers.values() if s not in ("train", "test"))},
           "fitting_items": {f: len(train[f]) for f in FIELDS},
           "labels": compare(rows, sets_eval),
           "shuffled_labels": {"seed": SHUFFLE_SEED, "labels": compare(sh_rows, sets_eval)}}

    res["with_development_papers"] = {"papers": len(eval_papers) + len(dev_papers),
                                      "labels": compare(rows + dev_rows, boot_sets(sorted(eval_papers + dev_papers)))}
    mem = db.execute("SELECT r.paper_id, m.platform_id, m.identity_id FROM platform_identity_member m "
                     "JOIN db_record_coding r ON r.coding_id = m.coding_id JOIN v_era e ON e.paper_id = r.paper_id"
                     + (" WHERE e.era = ?" if era_only else ""), arg).fetchall()
    fit_ids = {i for p, _, i in mem if papers.get(p) == "train"}
    shared = sorted({p for p, _, i in mem if p in set(eval_papers) and i in fit_ids})
    keep = [p for p in eval_papers if p not in set(shared)]
    res["shared_platforms_removed"] = {"papers_removed": len(shared), "papers_kept": len(keep),
                                       "labels": compare([r for r in rows if r["paper"] not in set(shared)], boot_sets(keep))}

    ref = shadow(dbpath, "reference")
    ref_items, ref_left_out = load_items(ref, era_only=era_only)
    ref_test = split(ref_items, side)["test"]
    ref_by = {f: [it for it in ref_test[f] if it["paper"] in set(ref_papers)] for f in FIELDS}
    ref_rows = predict(models, models, ref_by, "reference_coded")
    res["reference_coded"] = {"papers": len(ref_papers), "left_out": dict(ref_left_out),
                              "labels": compare(ref_rows, boot_sets(ref_papers))}

    sh_by = {(r["field"], key(r["it"])): r for r in sh_rows}
    shared_set = set(shared)
    with open(od / "predictions.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["set", "label", "paper", "platform", "item", "year", "field_tag", "context_L4", "y", "model_top1",
                    "model_top3", "model_level", "baseline_top1", "baseline_top3", "shuffled_model_top1",
                    "shared_platform_with_fitting_side"])
        for r in rows + dev_rows + ref_rows:
            it = r["it"]
            shr = sh_by.get((r["field"], key(it))) if r["set"] == "evaluated" else None
            w.writerow([r["set"], r["field"], it["paper"], it["platform"], it["item"], it["year"], it["t"],
                        "|".join(it["ctx"][3]), r["y"], r["model"], ";".join(r["model3"]), r["level"], r["base"],
                        ";".join(r["base3"]), shr["model"] if shr else "",
                        int(r["set"] == "evaluated" and it["paper"] in shared_set)])
    (od / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return res


def summary(res):
    lines = []
    for name, block in (("labels", res["labels"]), ("shuffled labels", res["shuffled_labels"]["labels"]),
                        ("with development papers", res["with_development_papers"]["labels"]),
                        ("shared platforms removed", res["shared_platforms_removed"]["labels"]),
                        ("reference-coded", res["reference_coded"]["labels"])):
        for f in FIELDS:
            x = block[f]
            lines.append(f"{name:26s} {f:14s} items {x['items']:5d} papers {x.get('papers', 0):3d} model "
                         f"{x.get('model', float('nan')):.3f} baseline {x.get('baseline', float('nan')):.3f} difference "
                         f"{x.get('diff', float('nan')):+.3f} ({x['diff_ci95'][0]:+.3f} to {x['diff_ci95'][1]:+.3f})")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="SQLite build of the database (opened read-only)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "out"))
    ap.add_argument("split", choices=tuple(SPLITS))
    a = ap.parse_args()
    print(summary(run(a.split, a.db, Path(a.out))))
