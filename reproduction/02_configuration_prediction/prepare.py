"""Steps before the evaluation: the list of papers by period, and the choice of the minimum count m by
leave-one-paper-out over the papers first made public in or before 2023.

  python3 prepare.py --db PATH/sdl-db.sqlite --out out era        -> out/era_list.csv
  python3 prepare.py --db PATH/sdl-db.sqlite --out out select-m   -> out/lopo.csv, out/m_selection.json

Both first check that the tables of the database build hold the rows the recorded analysis read (STRUCTURE_SHA256,
see check_structure). select-m reads only rows of papers first made public in or before 2023 (era = 'train').
"""
import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import FIELDS, Model, load_items  # noqa: E402

M_CANDIDATES = (1, 2, 3, 5, 10)
# sha256 of the INSERT lines of the SQL dump, in dump order, of every table except those listed in
# STRUCTURE_EXCLUDED (build metadata, the list of build input files, and the process tables added by a later build).
# The build the analysis was run on and the later build that only added the process tables give the same value.
STRUCTURE_EXCLUDED = ("db_build", "source_file", "process_extraction", "step_process", "process_item")
STRUCTURE_SHA256 = "ea4ab949e3f5063fc01ccd42bf039e87997d964a94f26f224a165ef0e97e14fe"  # 237 papers; 238-paper build: abd4f57f...a32f


def structure_digest(db):
    dump = "\n".join(line for line in db.iterdump()
                     if line.startswith("INSERT INTO ") and line.split('"')[1] not in STRUCTURE_EXCLUDED)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


def open_db(path):
    db = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    got = structure_digest(db)
    if got != STRUCTURE_SHA256:
        raise SystemExit(f"{path}: table contents differ from the build the analysis was run on "
                         f"(structure sha256 {got}, expected {STRUCTURE_SHA256})")
    return db


def era_list(db, out):
    gold = dict(db.execute("SELECT paper_id, gold_set FROM gold_membership"))
    rows = [{"paper_id": p, "first_public_year": y, "era": e or "", "gold_set": gold.get(p, "")}
            for p, y, e in db.execute("SELECT paper_id, first_public_year, era FROM v_era ORDER BY paper_id")]
    with open(out / "era_list.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    c = Counter(r["era"] or "NULL" for r in rows)
    dev_test = sum(1 for r in rows if r["era"] == "test" and r["gold_set"] == "dev")
    print(f"{len(rows)} papers: up to 2023 {c['train']}, from 2024 {c['test']} (of which {dev_test} development "
          f"papers), no year {c.get('NULL', 0)}")


def select_m(db, out):
    items, left_out = load_items(db, era_only="train")
    lopo_rows, chosen, acc_by = [], {}, {}
    for f in FIELDS:
        by_paper = defaultdict(list)
        for it in items[f]:
            by_paper[it["paper"]].append(it)
        acc = {}
        for m in M_CANDIDATES:
            correct = 0
            for p, own in by_paper.items():
                model = Model([it for q, its in by_paper.items() if q != p for it in its], m)
                correct += sum(model.predict(it)[0] == it["y"] for it in own)
            acc[m] = correct / len(items[f])
            lopo_rows.append({"label": f, "m": m, "items": len(items[f]), "papers": len(by_paper), "correct": correct,
                              "accuracy": f"{acc[m]:.6f}"})
        best = max(acc.values())
        chosen[f] = max(m for m in M_CANDIDATES if acc[m] == best)  # ties -> larger m
        acc_by[f] = {str(m): a for m, a in acc.items()}
    with open(out / "lopo.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(lopo_rows[0]))
        w.writeheader()
        w.writerows(lopo_rows)
    sel = {"papers": len({it["paper"] for f in FIELDS for it in items[f]}),
           "items": {f: len(items[f]) for f in FIELDS}, "left_out": dict(left_out),
           "lopo_accuracy": acc_by, "m": chosen}
    (out / "m_selection.json").write_text(json.dumps(sel, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(sel))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="SQLite build of the database (opened read-only)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "out"))
    ap.add_argument("step", choices=("era", "select-m"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    {"era": era_list, "select-m": select_m}[a.step](open_db(a.db), out)
