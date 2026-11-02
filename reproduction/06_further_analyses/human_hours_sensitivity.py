"""Sensitivity of both throughput tests to the working hours assumed for people.

  ~/.venvs/sdl-db-03/bin/python human_hours_sensitivity.py --db ../../db/sdl-db.sqlite \
      --recorded ../03_throughput/out/throughput/results.json --out out

Imports ../03_throughput/throughput.py and simulator.py unchanged; only throughput.calendars is replaced, per run, by
a copy that differs in the calendar used when the paper states no human operating hours and no human operating days.

How the simulator applies the default (throughput.calendars): the human calendar is built from the platform's
operating_hours_per_day and operating_days_per_week items with qualifier 'human'; if at least one of the two is stated,
the missing part is filled with 8 h or 5 d; if neither is stated, Monday-Friday 09:00-17:00 (simulator.HUMAN_DEFAULT)
is used. The human calendar applies only to human steps and human transfers; automated and software work uses the
automated calendar. The variants replace only the neither-stated default:
  base        Monday-Friday 09:00-17:00 (Calendar(8, 5)), as recorded
  continuous  people available 24 h, 7 days a week (Calendar(24, 7))
  seven_day   people available 7 days a week, 09:00-17:00 (Calendar(8, 7))
Papers that state one or both parts keep their calendar in every variant.

Everything else (evaluation sets, pools, own and pooled configurations, field-median baseline, failed-simulation
rules) is throughput.py's. Reproduction with own durations: share within a factor of 1.5 (throughput.own_stat) and the
paired difference variant minus base of the within-1.5x indicator (failed = outside). Prediction with pooled
durations: mean of d = |log10(sim / reported)| - |log10(baseline / reported)| over simulated papers
(throughput.pooled_stat) and the paired difference variant minus base of d over the papers simulated in both.
Intervals: throughput.boot (B = 2000, random.Random(1).choice over the sorted paper list).
The base run is compared value by value with the recorded results.json (--recorded).

Outputs: out/human_hours_sensitivity.json, out/human_hours_per_paper.csv.
"""
import argparse
import csv
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "03_throughput"))
import throughput as tp  # noqa: E402
from simulator import Calendar  # noqa: E402

VARIANTS = {"base": Calendar(8.0, 5), "continuous": Calendar(24.0, 7), "seven_day": Calendar(8.0, 7)}
ORIGINAL_CALENDARS = tp.calendars
mean = lambda xs: sum(xs) / len(xs)


def human_stated(pl):
    return {"hours": tp.pval(pl, "operating_hours_per_day", "human") is not None,
            "days": tp.pval(pl, "operating_days_per_week", "human") is not None}


def calendars_with(human_default):
    """throughput.calendars with `human_default` in place of HUMAN_DEFAULT (copied, otherwise unchanged)."""
    def calendars(pl):
        def cal(qual, dh, dd):
            h, d = tp.pval(pl, "operating_hours_per_day", qual), tp.pval(pl, "operating_days_per_week", qual)
            return Calendar(min(h or dh, 24.0), int(min(d or dd, 7))) if (h or d) else None
        return cal("human", 8.0, 5) or human_default, cal("automated", 24.0, 7) or tp.AUTO_DEFAULT
    return calendars


def human_work(p):
    """True if the configured platform has a human step or human transfer that takes time."""
    return (any(s.human and s.duration > 0 for i, s in enumerate(p.steps) if i != p.plan_index)
            or any(t.mode == "human_transfer" and t.minutes > 0 for t in p.transfers))


def run_variant(papers, entries, own_set, pooled_set):
    per = {tp.OWN: {}, tp.POOLED: {}}
    for row in own_set:
        pl = tp.plat_of(papers, row)
        p, _ = tp.configure(pl, "own", tp.Pools(entries, row["paper"]))
        r, err = tp.run_sim(p)
        t, kind = tp.reported(pl)
        per[tp.OWN][row["paper"]] = {"reported": t, "kind": kind, "error": err, "simulated": r.throughput if r else None,
                                     "flagged": r.flagged if r else None,
                                     "log10_r": math.log10(r.throughput / t) if r and r.throughput > 0 else None,
                                     "human_work_simulated": human_work(p)}
    reps = {row["paper"]: tp.reported(tp.plat_of(papers, row))[0] for row in pooled_set}
    for row in pooled_set:
        pid = row["paper"]
        pl = tp.plat_of(papers, row)
        p, _ = tp.configure(pl, "pooled", tp.Pools(entries, pid))
        r, err = tp.run_sim(p)
        same = [reps[q] for q in reps if q != pid and papers[q]["tag"] == papers[pid]["tag"]]
        base = statistics.median(same or [reps[q] for q in reps if q != pid])
        t = reps[pid]
        d = (abs(math.log10(r.throughput / t)) - abs(math.log10(base / t))) if r and r.throughput > 0 else None
        per[tp.POOLED][pid] = {"reported": t, "error": err, "simulated": r.throughput if r else None,
                               "flagged": r.flagged if r else None, "baseline": base, "d": d,
                               "human_work_simulated": human_work(p)}
    return per


def within(v):
    return 1.0 if v["log10_r"] is not None and abs(v["log10_r"]) <= tp.TOL else 0.0


def main(dbpath, recorded, out):
    db = sqlite3.connect(f"file:{Path(dbpath).resolve()}?mode=ro", uri=True)
    digest = tp.build_digest(db)
    papers = tp.read_papers(db)
    entries = tp.pool_entries(papers)
    own_set, pooled_set, _ = tp.sets(papers)

    runs = {}
    for name, cal in VARIANTS.items():
        tp.calendars = calendars_with(cal)
        runs[name] = run_variant(papers, entries, own_set, pooled_set)
        print(name, "done", flush=True)
    tp.calendars = ORIGINAL_CALENDARS

    # check of the base run against the recorded per-paper values
    rec = json.loads(Path(recorded).read_text(encoding="utf-8"))
    mism = []
    for name, keys in ((tp.OWN, ("simulated", "log10_r")), (tp.POOLED, ("simulated", "baseline", "d"))):
        for k, v in runs["base"][name].items():
            for key in keys:
                if v[key] != rec["per_paper"][name][k][key]:
                    mism.append([name, k, key])
    base_stats = {tp.OWN: tp.own_stat(runs["base"][tp.OWN]), tp.POOLED: tp.pooled_stat(runs["base"][tp.POOLED])}

    # who can be affected
    info = {}
    for name, rows in ((tp.OWN, own_set), (tp.POOLED, pooled_set)):
        for row in rows:
            pl = tp.plat_of(papers, row)
            st = human_stated(pl)
            info.setdefault(name, {})[row["paper"]] = {
                "human_step_or_transfer": any(s["by"] == "human" for s in pl["steps"])
                or any(c["mode"] == "human_transfer" for c in pl["conns"]),
                "human_work_simulated": runs["base"][name][row["paper"]]["human_work_simulated"],
                "human_hours_stated": st["hours"], "human_days_stated": st["days"]}

    def counts(name):
        x = info[name].values()
        return {"papers": len(info[name]),
                "human_step_or_transfer": sum(v["human_step_or_transfer"] for v in x),
                "human_work_simulated": sum(v["human_work_simulated"] for v in x),
                "human_hours_or_days_stated": sum(v["human_hours_stated"] or v["human_days_stated"] for v in x),
                "human_work_simulated_and_default_calendar": sum(
                    v["human_work_simulated"] and not (v["human_hours_stated"] or v["human_days_stated"]) for v in x)}

    res = {"db_content_digest": digest, "bootstrap": {"B": tp.B, "seed": tp.SEED},
           "variants": {k: {"hours": v.hours, "days": v.days} for k, v in VARIANTS.items()},
           "base_check": {"recorded_share_within_1p5x": rec["summary"][tp.OWN]["share_within_1p5x"],
                          "rerun_share_within_1p5x": base_stats[tp.OWN]["share_within_1p5x"],
                          "recorded_mean_d": rec["summary"][tp.POOLED]["mean_d"],
                          "rerun_mean_d": base_stats[tp.POOLED]["mean_d"],
                          "per_paper_mismatches": mism},
           "affected_papers": {tp.OWN: counts(tp.OWN), tp.POOLED: counts(tp.POOLED)},
           "results": {}}
    for name in VARIANTS:
        o, b = runs[name][tp.OWN], runs["base"][tp.OWN]
        os_ = tp.own_stat(o)
        ind = {k: (within(o[k]), within(b[k])) for k in o}
        diff = mean([x - y for x, y in ind.values()])
        dlo, dhi = tp.boot(ind, lambda xs: mean([x - y for x, y in xs]))
        po, pb = runs[name][tp.POOLED], runs["base"][tp.POOLED]
        ps = tp.pooled_stat(po)
        both = {k: (po[k]["d"], pb[k]["d"]) for k in po if po[k]["d"] is not None and pb[k]["d"] is not None}
        pdiff = mean([x - y for x, y in both.values()])
        plo, phi = tp.boot(both, lambda xs: mean([x - y for x, y in xs]))
        res["results"][name] = {
            tp.OWN: {**os_, "papers_changed": sum(o[k]["simulated"] != b[k]["simulated"] for k in o),
                     "within_status_changed": sum(within(o[k]) != within(b[k]) for k in o),
                     "difference_vs_base": {"value": diff, "ci95": [dlo, dhi], "n": len(ind)}},
            tp.POOLED: {**ps, "papers_changed": sum(po[k]["simulated"] != pb[k]["simulated"] for k in po),
                        "difference_vs_base": {"value": pdiff, "ci95": [plo, phi], "n": len(both)}}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "human_hours_sensitivity.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    with open(out / "human_hours_per_paper.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["test", "paper", "human_step_or_transfer", "human_work_simulated", "human_hours_stated",
                    "human_days_stated", "reported_per_day", "baseline_per_day"]
                   + [f"simulated_per_day_{v}" for v in VARIANTS])
        for name in (tp.OWN, tp.POOLED):
            for k in sorted(runs["base"][name]):
                i = info[name][k]
                w.writerow([name, k, int(i["human_step_or_transfer"]), int(i["human_work_simulated"]),
                            int(i["human_hours_stated"]), int(i["human_days_stated"]), runs["base"][name][k]["reported"],
                            runs["base"][name][k].get("baseline", "")]
                           + [runs[v][name][k]["simulated"] if runs[v][name][k]["simulated"] is not None else ""
                              for v in VARIANTS])
    print(json.dumps({k: v for k, v in res.items() if k != "variants"}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="the SQLite DB build (opened read-only)")
    ap.add_argument("--recorded", required=True, help="results.json written by 03_throughput/throughput.py")
    ap.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args()
    main(a.db, a.recorded, Path(a.out))
