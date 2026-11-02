"""Reporting of ten simulation inputs in 238 closed-loop SDL papers, with further descriptive items (Python standard
library only; the database build is opened read-only).

  python3 reporting.py --db PATH/sdl-db.sqlite --human-dir PATH/extraction/human/opus --out out
      -> out/indicators.csv (one row per paper), out/items.csv (one row per item), out/results.json

Per item: eligible papers, share reporting it with a paper-level bootstrap interval; shares among papers first made
public in or before 2023 (early) and in or after 2024 (late) and the late-minus-early difference with an interval from a
bootstrap stratified by period; a permutation test across primary fields with Holm-adjusted p values; shares weighted so
that each platform group counts once. Also: the further descriptive items with bootstrap intervals, the counts of the
human-intervention categories and the distribution of the number of items reported per paper.
Bootstrap: B = 2000 replicates, random.Random(1), percentile interval by linear interpolation between order statistics.
Permutation test: Pearson chi-square of the reported / not reported by field table, over the primary fields with at
least ten eligible papers; 2000 permutations of the field labels, random.Random(1) per item; p = (1 + number of
permuted statistics >= observed) / (1 + 2000).
"""
import argparse
import csv
import hashlib
import json
import random
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

# content digest of the database build the analysis was run on (sha256 of the SQL dump without the db_build row)
BUILD_DIGEST = "57b39af53554a4b7dbccbdfebfc3b254f88f6af050a378b3cb1f9435deeaa08a"  # 237 papers; 238-paper build: 11c4e4ac...3396
B = 2000                 # bootstrap replicates
PERMS = 2000             # field-label permutations
SEED = 1
FIELD_MIN_PAPERS = 10    # a primary field enters an item's permutation test when it has this many eligible papers
ITEMS = ("durations_every_step", "batch_size", "planning_time", "operating_time", "any_throughput",
         "measured_throughput", "cost", "transfer_time", "human_intervention_number_or_none", "longest_unattended_run")
ITEM_NAMES = {"durations_every_step": "Durations for every step (first platform)", "batch_size": "Batch size",
              "planning_time": "Planning time", "operating_time": "Operating time", "any_throughput": "Any throughput",
              "measured_throughput": "Measured throughput", "cost": "Cost",
              "transfer_time": "Transfer time (papers with a physical transfer)",
              "human_intervention_number_or_none": "Human intervention, number or none",
              "longest_unattended_run": "Longest unattended run"}
DESC = ("at_least_one_step_duration", "nominal_throughput_only", "throughput_less_and_more_automated",
        "parallel_streams_gt1", "identical_units_gt1", "transfer_agents_gt1", "experiments_per_count",
        "human_intervention_number")
PHYSICAL = {"fixed_tubing", "robot_arm_gantry", "mobile_robot", "human_transfer"}
STEP_ID = re.compile(r"[A-Za-z0-9_]+/P\d+/S\d+")


def connect_ro(path):
    return sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)


def content_digest(db):
    """sha256 of the SQL dump without the db_build row (its build time changes with every build)."""
    dump = "\n".join(line for line in db.iterdump() if not line.startswith('INSERT INTO "db_build"'))
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


# ---------- loading ----------
def pnum(platform_id):
    return int(platform_id.rsplit("/P", 1)[1])


def load_db(db):
    """Per paper: record coding, platforms, steps, connections, process rows, era, first field tag."""
    papers = {p: {"coding": c} for p, c in db.execute("SELECT paper_id, coding_id FROM db_record_coding ORDER BY paper_id")}
    for p, x in db.execute("SELECT paper_id, process_id FROM db_process_extraction"):
        papers[p]["process"] = x
    for p in papers.values():
        p.update(platforms=set(), steps=[], conns=[], sp=[], pi=[])
    by_coding = {v["coding"]: k for k, v in papers.items()}
    for c, pl in db.execute("SELECT coding_id, platform_id FROM platform"):
        if c in by_coding:
            papers[by_coding[c]]["platforms"].add(pl)
    for p, pl, s, o, uo, by in db.execute("SELECT paper_id, platform_id, step_id, step_order, unit_operation, "
                                          "performed_by FROM v_step"):
        papers[p]["steps"].append({"platform": pl, "step": s, "order": o, "uo": uo, "by": by})
    for p, pl, e, tm in db.execute("SELECT paper_id, platform_id, edge_id, transfer_mode FROM v_connection"):
        papers[p]["conns"].append({"platform": pl, "edge": e, "mode": tm})
    by_proc = {v.get("process"): k for k, v in papers.items()}
    for x, s, q, qual in db.execute("SELECT process_id, step_id, quantity, qualifier FROM step_process"):
        if x in by_proc:
            papers[by_proc[x]]["sp"].append({"step": s, "q": q, "qual": qual})
    for x, kind, t, q, qual in db.execute("SELECT process_id, target_kind, target_id, quantity, qualifier FROM process_item"):
        if x in by_proc:
            papers[by_proc[x]]["pi"].append({"kind": kind, "target": t, "q": q, "qual": qual})
    for p, y, era in db.execute("SELECT paper_id, first_public_year, era FROM v_era"):
        if p in papers:
            papers[p]["year"], papers[p]["era"] = y, era
    for c, tag in db.execute("SELECT coding_id, field_tag FROM coding_field_tag WHERE position = 1"):
        if c in by_coding:
            papers[by_coding[c]]["field"] = tag
    for p in papers.values():
        p["steps"].sort(key=lambda s: (pnum(s["platform"]), s["order"]))
    return papers


def load_human(papers, hdir):
    """Human-intervention category and stated unattended run lengths, one JSON file per paper."""
    for pid, p in papers.items():
        h = json.loads((Path(hdir) / f"{pid}.json").read_text(encoding="utf-8"))
        p["human"] = {"human_intervention": h["human_intervention"], "unassisted_run_length": h["unassisted_run_length"]}


def weights(db, papers):
    """Connected components of papers linked by a shared platform_identity_member.identity_id; weight 1 / size."""
    parent = {p: p for p in papers}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    members = defaultdict(set)
    for iid, p in db.execute("SELECT m.identity_id, r.paper_id FROM platform_identity_member m "
                             "JOIN db_record_coding r ON r.coding_id = m.coding_id"):
        members[iid].add(p)
    for iid in sorted(members):
        ps = sorted(members[iid])
        for q in ps[1:]:
            a, b = find(ps[0]), find(q)
            if a != b:
                parent[max(a, b)] = min(a, b)
    comp = defaultdict(list)
    for p in papers:
        comp[find(p)].append(p)
    return {p: 1 / len(comp[find(p)]) for p in papers}, len(comp)


# ---------- indicators ----------
def covered_steps(p, plat):
    """Steps of platform plat with a duration row or listed in a 'covers' qualifier of a duration row."""
    pref = plat + "/S"
    cov = set()
    for r in p["sp"]:
        if r["q"] != "duration" or not r["step"].startswith(pref):
            continue
        cov.add(r["step"])
        if "covers" in r["qual"]:
            cov.update(s for s in STEP_ID.findall(r["qual"].split("covers", 1)[1]) if s.startswith(pref))
    return cov


def first_platform(p):
    return min(p["platforms"], key=pnum) if p["platforms"] else None


def has_item(p, q, kind="platform"):
    return any(r["kind"] == kind and r["q"] == q for r in p["pi"])


def indicators(p):
    """{item: 1 | 0 | None (not eligible)} for the ten items, plus the descriptive items."""
    out = {}
    plat = first_platform(p)
    work = [s["step"] for s in p["steps"] if s["platform"] == plat and s["by"] in ("robot", "human")]
    cov = covered_steps(p, plat) if plat else set()
    out["durations_every_step"] = (1 if all(s in cov for s in work) else 0) if work else None
    out["batch_size"] = int(has_item(p, "batch_size"))
    plan_steps = {s["step"] for s in p["steps"] if s["uo"] == "plan_next_experiment"}
    out["planning_time"] = int(has_item(p, "planning_time")
                               or any(r["q"] == "duration" and r["step"] in plan_steps for r in p["sp"]))
    out["operating_time"] = int(has_item(p, "operating_hours_per_day") or has_item(p, "operating_days_per_week"))
    tp = [r for r in p["pi"] if r["kind"] == "platform" and r["q"] == "throughput"]
    out["any_throughput"] = int(bool(tp))
    out["measured_throughput"] = int(any(r["qual"].strip().lower().startswith("measured") for r in tp))
    out["cost"] = int(has_item(p, "cost"))
    phys = {c["edge"] for c in p["conns"] if c["mode"] in PHYSICAL}
    out["transfer_time"] = (1 if any(r["kind"] == "connection" and r["q"] == "transfer_time" and r["target"] in phys
                                     for r in p["pi"]) else 0) if phys else None
    h = p["human"]
    out["human_intervention_number_or_none"] = int(h["human_intervention"] in ("quantified", "none_stated"))
    out["longest_unattended_run"] = int(len(h["unassisted_run_length"]) > 0)
    # descriptive items
    out["at_least_one_step_duration"] = int(any(r["q"] == "duration" for r in p["sp"]))
    out["nominal_throughput_only"] = int(out["any_throughput"] == 1 and out["measured_throughput"] == 0)
    out["throughput_less_and_more_automated"] = int(has_item(p, "throughput_less_automated")
                                                    and has_item(p, "throughput_automated"))
    out["parallel_streams_gt1"] = int(has_item(p, "parallel_units"))
    out["identical_units_gt1"] = int(has_item(p, "units", "module"))
    out["transfer_agents_gt1"] = int(has_item(p, "transfer_agent_count"))
    out["experiments_per_count"] = int(has_item(p, "experiments_per_count"))
    out["human_intervention_number"] = int(h["human_intervention"] == "quantified")
    out["items_reported"] = sum(out[k] or 0 for k in ITEMS)
    return out


# ---------- statistics ----------
def quantile(sorted_vals, q):
    """Linear interpolation between order statistics (as numpy's default 'linear' method)."""
    n = len(sorted_vals)
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def ci(vals):
    v = sorted(vals)
    return (quantile(v, 0.025), quantile(v, 0.975)) if v else (None, None)


def share(ind, seq, k):
    vals = [ind[p][k] for p in seq if ind[p][k] is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def shares(ind, papers, items=ITEMS, b=B, seed=SEED):
    """Share of eligible papers reporting each item, with a paper-level bootstrap interval."""
    rng = random.Random(seed)
    reps = defaultdict(list)
    for _ in range(b):
        seq = [rng.choice(papers) for _ in papers]
        for k in items:
            s, n = share(ind, seq, k)
            if n:
                reps[k].append(s)
    rows = {}
    for k in items:
        s, n = share(ind, papers, k)
        lo, hi = ci(reps[k])
        rows[k] = {"share": s, "n_eligible": n, "n_reported": sum(ind[p][k] or 0 for p in papers),
                   "ci95_lo": lo, "ci95_hi": hi}
    return rows


def by_period(ind, era, papers, items=ITEMS, b=B, seed=SEED):
    """Early and late shares and the late-minus-early difference with a period-stratified bootstrap interval."""
    early = [p for p in papers if era.get(p) == "train"]
    late = [p for p in papers if era.get(p) == "test"]
    rng = random.Random(seed)
    reps = defaultdict(list)
    for _ in range(b):
        se = [rng.choice(early) for _ in early]
        sl = [rng.choice(late) for _ in late]
        for k in items:
            (a, na), (c, nc) = share(ind, se, k), share(ind, sl, k)
            if na and nc:
                reps[k].append(c - a)
    rows = {}
    for k in items:
        (a, na), (c, nc) = share(ind, early, k), share(ind, late, k)
        lo, hi = ci(reps[k])
        rows[k] = {"share_early": a, "n_early": na, "share_late": c, "n_late": nc,
                   "diff": None if a is None or c is None else c - a, "ci95_lo": lo, "ci95_hi": hi}
    return {"items": rows, "n_early": len(early), "n_late": len(late), "n_no_era": len(papers) - len(early) - len(late)}


def chi2(ys, labels):
    """Pearson chi-square of the 2 x F table (reported / not by field)."""
    n = len(ys)
    tot = sum(ys)
    if tot == 0 or tot == n:
        return 0.0
    cnt, rep = Counter(labels), Counter(l for l, y in zip(labels, ys) if y)
    stat = 0.0
    for f, nf in cnt.items():
        e1 = nf * tot / n
        e0 = nf - e1
        stat += (rep[f] - e1) ** 2 / e1 + ((nf - rep[f]) - e0) ** 2 / e0
    return stat


def holm(ps):
    order = sorted(ps, key=lambda k: (ps[k] is None, ps[k] if ps[k] is not None else 0))
    m = sum(v is not None for v in ps.values())
    adj, run = {}, 0.0
    for i, k in enumerate(order):
        if ps[k] is None:
            adj[k] = None
            continue
        run = max(run, min(1.0, (m - i) * ps[k]))
        adj[k] = run
    return adj


def by_field(ind, field, papers, items=ITEMS, perms=PERMS, seed=SEED):
    """Permutation test of the chi-square statistic across primary fields, per item; Holm adjustment over items."""
    mapped = [p for p in papers if field.get(p) not in (None, "unmapped")]
    rows = {}
    for k in items:
        elig = [p for p in mapped if ind[p][k] is not None]
        nf = Counter(field[p] for p in elig)
        fields = sorted(f for f, n in nf.items() if n >= FIELD_MIN_PAPERS)
        row = {"fields": fields, "n_tested": 0, "chi2": None, "p": None}
        if len(fields) >= 2:
            ps = [p for p in elig if field[p] in fields]
            ys = [ind[p][k] for p in ps]
            labs = [field[p] for p in ps]
            obs = chi2(ys, labs)
            rng = random.Random(seed)
            ge = 0
            perm = labs[:]
            for _ in range(perms):
                rng.shuffle(perm)
                ge += chi2(ys, perm) >= obs - 1e-12
            row.update(n_tested=len(ps), chi2=obs, p=(1 + ge) / (1 + perms))
        rows[k] = row
    adj = holm({k: rows[k]["p"] for k in items})
    for k in items:
        rows[k]["p_holm"] = adj[k]
    return {"items": rows, "n_mapped": len(mapped)}


def weighted_shares(ind, W, papers):
    res = {}
    for k in ITEMS:
        el = [p for p in papers if ind[p][k] is not None]
        wn = sum(W[p] for p in el)
        res[k] = {"weighted_share": sum(W[p] * ind[p][k] for p in el) / wn if wn else None, "weighted_n": wn}
    return res


# ---------- run ----------
def analyse(db, hdir):
    data = load_db(db)
    load_human(data, hdir)
    papers = sorted(data)
    ind = {p: indicators(data[p]) for p in papers}
    era = {p: data[p].get("era") for p in papers}
    field = {p: data[p].get("field") for p in papers}
    W, ncomp = weights(db, papers)
    res = {"n_papers": len(papers), "n_platform_groups": ncomp,
           "items": shares(ind, papers), "by_period": by_period(ind, era, papers), "by_field": by_field(ind, field, papers),
           "descriptive": shares(ind, papers, items=DESC),
           "human_intervention_categories": dict(Counter(data[p]["human"]["human_intervention"] for p in papers)),
           "items_reported_per_paper": dict(sorted(Counter(ind[p]["items_reported"] for p in papers).items())),
           "platform_weighted": weighted_shares(ind, W, papers)}
    return res, ind, data


def write_outputs(res, ind, data, od):
    od.mkdir(parents=True, exist_ok=True)
    cols = list(ITEMS) + list(DESC) + ["items_reported"]
    with (od / "indicators.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["paper_id", "era", "first_field_tag", "human_intervention"] + cols)
        for p in sorted(ind):
            w.writerow([p, data[p].get("era") or "", data[p].get("field") or "", data[p]["human"]["human_intervention"]]
                       + ["" if ind[p][k] is None else ind[p][k] for k in cols])
    with (od / "items.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item", "name", "n_eligible", "n_reported", "share", "ci95_lo", "ci95_hi", "share_early", "n_early",
                    "share_late", "n_late", "diff_late_minus_early", "diff_ci95_lo", "diff_ci95_hi", "fields_tested",
                    "n_tested", "chi2", "p", "p_holm", "weighted_share", "weighted_n"])
        for k in ITEMS:
            a, b, c = res["items"][k], res["by_period"]["items"][k], res["by_field"]["items"][k]
            wt = res["platform_weighted"][k]
            w.writerow([k, ITEM_NAMES[k], a["n_eligible"], a["n_reported"], a["share"], a["ci95_lo"], a["ci95_hi"],
                        b["share_early"], b["n_early"], b["share_late"], b["n_late"], b["diff"], b["ci95_lo"],
                        b["ci95_hi"], ";".join(c["fields"]), c["n_tested"], c["chi2"], c["p"], c["p_holm"],
                        wt["weighted_share"], wt["weighted_n"]])
    (od / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="SQLite build of the database (opened read-only)")
    ap.add_argument("--human-dir", required=True, help="folder with one human-intervention JSON file per paper")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "out"))
    a = ap.parse_args()
    db = connect_ro(a.db)
    got = content_digest(db)
    if got != BUILD_DIGEST:
        raise SystemExit(f"{a.db}: content digest {got} is not the build the analysis was run on ({BUILD_DIGEST})")
    res, ind, data = analyse(db, a.human_dir)
    write_outputs(res, ind, data, Path(a.out))
    for k in ITEMS:
        x, y, z = res["items"][k], res["by_period"]["items"][k], res["by_field"]["items"][k]
        print(f"{k:34s} n {x['n_eligible']:3d} share {x['share']:.3f} ({x['ci95_lo']:.3f}-{x['ci95_hi']:.3f}) "
              f"late-early {y['diff']:+.3f} ({y['ci95_lo']:+.3f} to {y['ci95_hi']:+.3f}) p {z['p']:.3f} Holm {z['p_holm']:.3f}")
