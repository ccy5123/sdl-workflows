"""Throughput simulation of the DB platforms: reproduction with each paper's own durations, prediction with pooled
durations against a field-median baseline, the shuffled-duration negative controls, the automation gain, and the
breakdowns by throughput kind, case, field and own-duration coverage.

Usage (Python 3.12.3, simpy 4.1.2):
  python reproduction/03_throughput/throughput.py --db db/sdl-db.sqlite --out reproduction/03_throughput/out/throughput
Writes evaluation_sets.json (evaluation sets, case lists, pool sizes; computed from the DB only, before any
simulation) and results.json (all simulated values and summary statistics).

Data source: the Opus 5.5 timing-data extraction of every DB paper (view db_process_extraction; tables step_process,
process_item) and the DB record coding (views v_step, v_connection; tables step_module, platform, coding_field_tag).

Choices fixed in this script:
- Platform order: by the number in P<n>. Steps: by step_order. A step's modules: all its step_module rows.
- Joint durations (qualifier 'covers <step ids>'): the duration is the job time of the step that carries it; the other
  covered steps take no time and count as having their own value. Joint durations are not pooled.
- Plan step: the first step of family 'plan' performed by software. Planning minutes: own durations = the plan step's
  own duration, else own planning_time, else pooled; pooled durations = pooled. Per paper the planning pool value is
  its own planning_time, else its plan step's own duration. A plan step is not in the step-duration pool.
- Step-duration pool entry: (duration in minutes, n) of a non-joint, non-plan step with its own duration; n = its own
  duration_batch_size, else the paper's batch_size, else 1. Levels: (unit_operation, primary_module_type),
  unit_operation, family, all; the finest level with >= 3 entries; job time = median duration, job size = median n. If
  all levels have fewer than 3 entries the 'all' level is used anyway; an empty pool gives 0. Pools leave out the
  paper being simulated.
- Transfers: a material connection is attached before the step it leads to (first module of consecutive steps; else
  the first step on the destination module that follows a step on the source module). Unattached connections are not
  simulated and are counted. transfer_time pool: by transfer_mode, then all, same 3-entry rule.
- Calendars: human = stated operating hours/days with qualifier human (missing part: 8 h, 5 d), else Mon-Fri 09-17;
  automated = stated values with qualifier automated (missing part: 24 h, 7 d), else always on. Software steps use the
  automated calendar.
- Reported throughput: agreement_scoring.throughput() (campaign-measured value if given, else nominal; experiments
  per calendar day with experiments_per_count and batch_size), the same normalisation as the timing-data agreement.
- A platform whose simulation fails (SimulationError) counts as outside 1.5x in the own-duration share, is left out of
  the mean difference of the pooled-duration prediction, and is listed.
- Own-duration platform = the first platform of a paper with a reported throughput and own durations for at least half
  of its steps; pooled-duration platform = the first platform with a reported throughput; each uses its own reported
  value.
- Bootstrap: random.Random(1).choice over the sorted paper list, B = 2000, percentile interval = sorted values at
  int(0.025 B) and min(B - 1, int(0.975 B)).
"""
import argparse
import hashlib
import json
import math
import random
import re
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import simpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agreement_scoring as score  # noqa: E402
from simulator import AUTO_DEFAULT, HUMAN_DEFAULT, Calendar, Platform, SimulationError, Step, Transfer, simulate  # noqa: E402

# content digest of the DB build the manuscript values were computed on (see build_digest)
EXPECTED_DB_DIGEST = "57b39af53554a4b7dbccbdfebfc3b254f88f6af050a378b3cb1f9435deeaa08a"  # 237 papers; 238-paper build: 11c4e4ac...3396
TOL = math.log10(1.5)
B, SEED = 2000, 1
CASES = ["parallel-or-batched-modules", "shared-transfer-agent", "human-transfer-or-human-step", "long-incubation-step",
         "long-planning-computation"]
MATERIAL_AGENTS = ("robot_arm_gantry", "mobile_robot")
OWN, POOLED = "reproduction_own_durations", "prediction_pooled_durations"

num = lambda pid: int(re.search(r"/P(\d+)$", pid).group(1))


def build_digest(db):
    """sha256 of the SQL dump without the db_build row (independent of build time and file layout)."""
    dump = "\n".join(line for line in db.iterdump() if not line.startswith('INSERT INTO "db_build"'))
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------
# Reading the DB

def read_papers(db):
    """Per paper: platforms with steps, modules, connections and the extracted timing values."""
    T = score.T_MIN
    proc = dict(db.execute("SELECT paper_id, process_id FROM db_process_extraction"))
    rec = dict(db.execute("SELECT paper_id, coding_id FROM db_record_coding"))
    papers = {}
    for pid in sorted(rec):
        cid, xid = rec[pid], proc[pid]
        steps = defaultdict(list)
        for r in db.execute("SELECT platform_id, step_id, step_order, unit_operation, family, performed_by, "
                            "primary_module_type, first_field_tag FROM v_step WHERE coding_id = ?", (cid,)):
            steps[r[0]].append({"sid": r[1], "order": r[2], "uo": r[3], "family": r[4], "by": r[5], "pmt": r[6],
                                "tag": r[7] or ""})
        smods = defaultdict(list)
        for sid, mid, pos in db.execute("SELECT step_id, module_id, position FROM step_module WHERE coding_id = ? "
                                        "ORDER BY step_id, position", (cid,)):
            smods[sid].append(mid)
        conns = defaultdict(list)
        for r in db.execute("SELECT platform_id, edge_id, from_module, to_module, transfer_mode, is_material "
                            "FROM v_connection WHERE coding_id = ? ORDER BY edge_id", (cid,)):
            conns[r[0]].append({"eid": r[1], "a": r[2], "b": r[3], "mode": r[4], "material": r[5]})
        sp = defaultdict(dict)
        for sid, q, v, u, qual in db.execute("SELECT step_id, quantity, value, unit, qualifier FROM step_process "
                                             "WHERE process_id = ?", (xid,)):
            sp[sid][q] = (v * T[u] if q == "duration" else v, qual)
        items = [dict(zip(("target_kind", "target_id", "quantity", "value", "unit", "qualifier"), r)) for r in db.execute(
            "SELECT target_kind, target_id, quantity, value, unit, qualifier FROM process_item WHERE process_id = ?", (xid,))]
        tag = db.execute("SELECT field_tag FROM coding_field_tag WHERE coding_id = ? AND position = 1", (cid,)).fetchone()
        plats = []
        for plat in sorted({r[0] for r in db.execute("SELECT platform_id FROM platform WHERE coding_id = ?", (cid,))}, key=num):
            st = sorted(steps.get(plat, []), key=lambda s: s["order"])
            for s in st:
                s["modules"] = smods.get(s["sid"], [])
            pv = defaultdict(list)
            for it in items:
                if it["target_id"] == plat:
                    pv[it["quantity"]].append(it)
            plats.append({"pid": plat, "tag": tag[0] if tag else "", "steps": st, "conns": conns.get(plat, []), "pv": pv,
                          "units": {it["target_id"]: it["value"] for it in items
                                    if it["target_kind"] == "module" and it["quantity"] == "units"
                                    and it["target_id"].startswith(plat + "/")},
                          "ttime": {it["target_id"]: it["value"] * T[it["unit"]] for it in items
                                    if it["target_kind"] == "connection" and it["quantity"] == "transfer_time"
                                    and it["target_id"].startswith(plat + "/")},
                          "sp": {s["sid"]: sp[s["sid"]] for s in st if s["sid"] in sp}})
        papers[pid] = {"paper": pid, "tag": tag[0] if tag else "", "items": items, "platforms": plats}
    return papers


def pval(pl, q, qual=None):
    rows = [r for r in pl["pv"].get(q, []) if qual is None or r["qualifier"] == qual]
    return rows[0]["value"] if rows else None


def covered(pl):
    """Steps covered by a joint duration of an earlier step (not the carrier)."""
    out = set()
    for sid, vals in pl["sp"].items():
        if "duration" in vals:
            m = re.search(r"(?:^|;\s*)covers ([^;]+)", vals["duration"][1])
            if m:
                out |= {x.strip() for x in m.group(1).split(",") if x.strip() and x.strip() != sid}
    return out


def plan_index(pl):
    return next((i for i, s in enumerate(pl["steps"]) if s["family"] == "plan" and s["by"] == "software"), None)


def reported(pl):
    rows = [r for qs in pl["pv"].values() for r in qs]
    t = score.throughput({"process_items": rows}, pl["pid"])
    return (t[0], t[1]) if t else None


def attach(pl):
    """Material connections: (index of the destination step, connection); unattached connections counted."""
    st = pl["steps"]
    first = [s["modules"][0] if s["modules"] else None for s in st]
    out, unattached = [], 0
    for c in pl["conns"]:
        if not c["material"]:
            continue
        j = next((i + 1 for i in range(len(st) - 1) if first[i] == c["a"] and first[i + 1] == c["b"]), None)
        if j is None:
            jb = next((k for k, m in enumerate(first) if m == c["b"]), None)
            if jb is not None and any(first[i] == c["a"] for i in range(jb)):
                j = jb
        if j is None:
            unattached += 1
        else:
            out.append((j, c))
    return out, unattached


# ---------------------------------------------------------------------------------------------------------------------
# Pools (leave-one-paper-out)

def own_planning(pl):
    v = pval(pl, "planning_time")
    if v is not None:
        r = pl["pv"]["planning_time"][0]
        return v * {"s": 1 / 60, "min": 1.0, "h": 60.0}[r["unit"]]
    pi = plan_index(pl)
    if pi is not None and "duration" in pl["sp"].get(pl["steps"][pi]["sid"], {}):
        return pl["sp"][pl["steps"][pi]["sid"]]["duration"][0]
    return None


def own_duration_planning(pl):
    """Planning minutes from own values: the plan step's own duration, else own planning_time."""
    pi = plan_index(pl)
    if pi is not None and "duration" in pl["sp"].get(pl["steps"][pi]["sid"], {}):
        return pl["sp"][pl["steps"][pi]["sid"]]["duration"][0]
    return own_planning(pl)


def pool_entries(papers):
    steps, transfers, planning = [], [], []
    for p in papers.values():
        for pl in p["platforms"]:
            b = pval(pl, "batch_size") or 1
            pi = plan_index(pl)
            for i, s in enumerate(pl["steps"]):
                vals = pl["sp"].get(s["sid"], {})
                if "duration" not in vals or i == pi or "covers" in vals["duration"][1]:
                    continue
                n = vals.get("duration_batch_size", (None,))[0] or b
                steps.append({"paper": p["paper"], "keys": [(s["uo"], s["pmt"]), (s["uo"],), (s["family"],), ()],
                              "d": vals["duration"][0], "n": n})
            modes = {c["eid"]: c["mode"] for c in pl["conns"]}
            for eid, minutes in pl["ttime"].items():
                transfers.append({"paper": p["paper"], "keys": [(modes.get(eid),), ()], "d": minutes})
            v = own_planning(pl)
            if v is not None:
                planning.append({"paper": p["paper"], "keys": [(p["tag"],), ()], "d": v})
    return {"steps": steps, "transfers": transfers, "planning": planning}


class Pools:
    def __init__(self, entries, exclude):
        self.e = {k: [x for x in v if x["paper"] != exclude] for k, v in entries.items()}

    def get(self, kind, keys):
        """(median duration, median n or None, level used) from the finest level with >= 3 entries."""
        es = self.e[kind]
        for lev, key in enumerate(keys):
            sel = [x for x in es if x["keys"][lev] == key]
            if len(sel) >= 3 or lev == len(keys) - 1:
                if not sel:
                    return 0.0, None, lev
                n = statistics.median(x["n"] for x in sel) if kind == "steps" else None
                return statistics.median(x["d"] for x in sel), n, lev
        raise AssertionError


# ---------------------------------------------------------------------------------------------------------------------
# Platform configurations

def calendars(pl):
    def cal(qual, dh, dd):
        h, d = pval(pl, "operating_hours_per_day", qual), pval(pl, "operating_days_per_week", qual)
        return Calendar(min(h or dh, 24.0), int(min(d or dd, 7))) if (h or d) else None
    return cal("human", 8.0, 5) or HUMAN_DEFAULT, cal("automated", 24.0, 7) or AUTO_DEFAULT


def configure(pl, mode, pools, durations=None, less_auto=None):
    """mode 'own' (own values, gaps pooled) or 'pooled' (all pooled). durations: negative-control override, a dict with
    'steps' (list of (minutes, n)), 'transfers' (list of minutes), 'planning' (minutes). less_auto: step or connection
    ids made human for the less-automated configuration."""
    st, cov, pi = pl["steps"], covered(pl), plan_index(pl)
    b = pval(pl, "batch_size") or 1
    human_ids = set(less_auto or ())
    steps = []
    k_dur = 0
    for i, s in enumerate(st):
        vals = pl["sp"].get(s["sid"], {})
        human = s["by"] == "human" or s["sid"] in human_ids
        if i == pi:
            steps.append(Step(s["sid"], tuple(s["modules"]), human, 0.0, None, True))
            continue
        if durations is not None:
            seq = durations["steps"]
            d, n = seq[k_dur % len(seq)] if seq else (durations["step_median"], None)
            k_dur += 1
            own = False
        elif mode == "own" and s["sid"] in cov:
            d, n, own = 0.0, None, True
        elif mode == "own" and "duration" in vals:
            d, n, own = vals["duration"][0], vals.get("duration_batch_size", (None,))[0], True
        else:
            d, n, _ = pools.get("steps", [(s["uo"], s["pmt"]), (s["uo"],), (s["family"],), ()])
            own = False
        steps.append(Step(s["sid"], tuple(s["modules"]), human, d, n, own))
    # planning
    if durations is not None:
        planning, planning_own = durations["planning"], False
    elif mode == "own" and own_duration_planning(pl) is not None:
        planning, planning_own = own_duration_planning(pl), True
    else:
        planning, planning_own = pools.get("planning", [(pl["tag"],), ()])[0], False
    # transfers
    att, unattached = attach(pl)
    transfers, k_tr = [], 0
    for j, c in att:
        m = "human_transfer" if c["eid"] in human_ids else c["mode"]
        if durations is not None:
            seq = durations["transfers"]
            minutes = seq[k_tr % len(seq)] if seq else durations["transfer_median"]
            k_tr += 1
            own = False
        elif mode == "own" and c["eid"] in pl["ttime"]:
            minutes, own = pl["ttime"][c["eid"]], True
        else:
            minutes, own = pools.get("transfers", [(c["mode"],), ()])[0], False
        transfers.append(Transfer(j, m, minutes, own))
    agents = {r["qualifier"]: r["value"] for r in pl["pv"].get("transfer_agent_count", [])}
    hc, ac = calendars(pl)
    units = {m: pl["units"].get(m, 1) for s in st for m in s["modules"]}
    return Platform(steps=steps, units=units, transfers=transfers, batch_size=b,
                    parallel_units=int(pval(pl, "parallel_units") or 1), planning=planning or 0.0,
                    planning_own=planning_own, plan_index=pi, agents=agents, human_cal=hc, auto_cal=ac), unattached


def per_batch(p):
    """Per-batch minutes of each non-plan step: duration x ceil(b / n)."""
    return {s.sid: s.duration * (math.ceil(p.batch_size / s.job_size) if s.job_size else 1)
            for i, s in enumerate(p.steps) if i != p.plan_index}


def cases_of(pl, p):
    st = pl["steps"]
    out = []
    n_own = [v["duration_batch_size"][0] for v in pl["sp"].values() if "duration_batch_size" in v]
    if (p.batch_size > 1 or p.parallel_units > 1 or any(u > 1 for u in pl["units"].values())
            or any(n > 1 for n in n_own)):
        out.append(CASES[0])
    agents = {r["qualifier"]: r["value"] for r in pl["pv"].get("transfer_agent_count", [])}
    if any(sum(c["mode"] == m for c in pl["conns"]) >= 2 and agents.get(m, 1) == 1 for m in MATERIAL_AGENTS):
        out.append(CASES[1])
    if any(s["by"] == "human" for s in st) or any(c["mode"] == "human_transfer" for c in pl["conns"]):
        out.append(CASES[2])
    pb = per_batch(p)
    total = sum(pb.values())
    if total > 0 and any(v >= 0.5 * total for v in pb.values()):
        out.append(CASES[3])
    if p.planning > 0 and p.planning >= 0.5 * total:
        out.append(CASES[4])
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Evaluation sets

def sets(papers):
    """(own-duration set, pooled-duration set, automation-gain set): one platform per paper."""
    own_set, pooled_set, gain_set = [], [], []
    for pid, p in papers.items():
        for pl in p["platforms"]:
            if reported(pl) is None or not pl["steps"]:
                continue
            if not any(x["paper"] == pid for x in pooled_set):
                pooled_set.append({"paper": pid, "platform": pl["pid"]})
            pi, cov = plan_index(pl), covered(pl)
            own = sum(1 for i, s in enumerate(pl["steps"])
                      if (own_planning(pl) is not None if i == pi else ("duration" in pl["sp"].get(s["sid"], {}) or s["sid"] in cov)))
            if own >= 0.5 * len(pl["steps"]) and not any(x["paper"] == pid for x in own_set):
                own_set.append({"paper": pid, "platform": pl["pid"], "own_steps": own, "steps": len(pl["steps"])})
        for pl in p["platforms"]:
            if pval(pl, "throughput_less_automated") is not None and pval(pl, "throughput_automated") is not None:
                gain_set.append({"paper": pid, "platform": pl["pid"]})
                break
    return own_set, pooled_set, gain_set


def plat_of(papers, row):
    return next(pl for pl in papers[row["paper"]]["platforms"] if pl["pid"] == row["platform"])


# ---------------------------------------------------------------------------------------------------------------------
# Statistics

def boot(values_by_paper, stat):
    papers = sorted(values_by_paper)
    rng = random.Random(SEED)
    vals = sorted(stat([values_by_paper[rng.choice(papers)] for _ in papers]) for _ in range(B))
    return vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]


share_within = lambda xs: sum(abs(x) <= TOL for x in xs) / len(xs)
mean = lambda xs: sum(xs) / len(xs)


def derangement(papers):
    rng = random.Random(SEED)
    while True:
        perm = papers[:]
        rng.shuffle(perm)
        if all(a != b for a, b in zip(papers, perm)):
            return dict(zip(papers, perm))


def nc_durations(pl, med):
    """Durations of another paper for the negative control: its own step durations in step order, its transfer and
    planning times; overall medians where it has none."""
    seq = []
    pi = plan_index(pl)
    for i, s in enumerate(pl["steps"]):
        vals = pl["sp"].get(s["sid"], {})
        if i != pi and "duration" in vals:
            seq.append((vals["duration"][0], vals.get("duration_batch_size", (None,))[0]))
    return {"steps": seq, "transfers": list(pl["ttime"].values()), "planning": own_planning(pl) or med["planning"],
            "step_median": med["steps"], "transfer_median": med["transfers"]}


def own_stat(per):
    """Share of papers whose simulated throughput is within a factor of 1.5 of the reported one, with its interval.
    A paper whose simulation failed counts as not within 1.5x."""
    n = len(per)
    if not n:
        return {"n": 0, "n_simulated": 0, "n_within_1p5x": 0, "share_within_1p5x": None, "ci95": [None, None],
                "flagged": 0}
    vals = {k: (per[k]["log10_r"] if per[k]["log10_r"] is not None else math.inf) for k in per}
    share = share_within(list(vals.values()))
    lo, hi = boot(vals, share_within)
    return {"n": n, "n_simulated": sum(1 for v in per.values() if v["log10_r"] is not None),
            "n_within_1p5x": sum(abs(x) <= TOL for x in vals.values()), "share_within_1p5x": share, "ci95": [lo, hi],
            "flagged": sum(1 for v in per.values() if v.get("flagged"))}


def pooled_stat(per):
    """Mean over simulated papers of d = |log10(simulated / reported)| - |log10(baseline / reported)|, with its
    interval. Papers whose simulation failed are left out and counted (n - n_simulated)."""
    vals = {k: v["d"] for k, v in per.items() if v["d"] is not None}
    if not vals:
        return {"n": len(per), "n_simulated": 0, "mean_d": None, "ci95": [None, None], "flagged": 0}
    lo, hi = boot(vals, mean)
    return {"n": len(per), "n_simulated": len(vals), "mean_d": mean(list(vals.values())), "ci95": [lo, hi],
            "flagged": sum(1 for v in per.values() if v.get("flagged"))}


def analytic(p):
    """(serial-sum throughput, bottleneck-rate throughput), experiments per day: the two simpler estimates."""
    pb = per_batch(p)
    cycle = sum(pb.values()) + p.planning + sum(t.minutes for t in p.transfers)
    serial = p.batch_size * 1440.0 / cycle if cycle > 0 else None
    rates = [p.parallel_units * p.batch_size / cycle] if cycle > 0 else []
    for i, s in enumerate(p.steps):
        if i != p.plan_index and pb.get(s.sid, 0) > 0:
            cap = min(p.units.get(m, 1) for m in s.modules) if s.modules else p.parallel_units
            jobs = math.ceil(p.batch_size / s.job_size) if s.job_size else 1
            rates.append(cap * p.batch_size / (jobs * s.duration))
    return serial, (min(rates) * 1440.0 if rates else None)


def breakdowns(per):
    def sub(name, keep):
        sel = {k: v for k, v in per[name].items() if keep(v)}
        if name == OWN:
            xs = [v["log10_r"] for v in sel.values() if v["log10_r"] is not None]
            return {"n": len(sel), "share_within_1p5x": share_within(xs) if xs else None}
        ds = [v["d"] for v in sel.values() if v["d"] is not None]
        return {"n": len(sel), "mean_d": mean(ds) if ds else None}
    out = {}
    for name in (OWN, POOLED):
        fields = sorted({v["field"] for v in per[name].values()})
        out[name] = {
            "by_kind": {k: sub(name, lambda v, k=k: v["kind"] == k) for k in ("measured", "nominal")},
            "by_case": {c: sub(name, lambda v, c=c: c in v["cases"]) for c in CASES},
            "by_field": {t: sub(name, lambda v, t=t: v["field"] == t) for t in fields},
            "simple_estimates_within_1p5x": {
                f: (share_within([math.log10(v[f] / v["reported"]) for v in per[name].values() if v[f]])
                    if any(v[f] for v in per[name].values()) else None) for f in ("serial_sum", "bottleneck_rate")},
            "flagged": sum(1 for v in per[name].values() if v.get("flagged")),
            "failed": sorted(k for k, v in per[name].items() if v.get("error")),
        }
    out[OWN]["by_own_duration_coverage"] = {
        lab: sub(OWN, lambda v, lo=lo, hi=hi: v["own_share"] is not None and lo <= v["own_share"] < hi)
        for lab, lo, hi in (("<0.5", 0, 0.5), ("0.5-0.75", 0.5, 0.75), (">=0.75", 0.75, 1.01))}
    out[OWN]["bottleneck_module"] = {k: v["bottleneck"] for k, v in per[OWN].items()}
    return out


def run_sim(p):
    try:
        return simulate(p), None
    except SimulationError as e:
        return None, str(e)


# ---------------------------------------------------------------------------------------------------------------------

def evaluation_sets(papers, entries):
    """Evaluation sets and case lists, from the DB only (no simulation, no comparison with reported throughput)."""
    own_set, pooled_set, gain_set = sets(papers)
    cases = {OWN: {}, POOLED: {}}
    unatt = {}
    for name, rows, mode in ((OWN, own_set, "own"), (POOLED, pooled_set, "pooled")):
        for row in rows:
            pl = plat_of(papers, row)
            p, un = configure(pl, mode, Pools(entries, row["paper"]))
            cases[name][row["paper"]] = cases_of(pl, p)
            unatt[row["paper"]] = un
    return {"sets": {OWN: own_set, POOLED: pooled_set, "automation_gain": gain_set},
            "n": {OWN: len(own_set), POOLED: len(pooled_set), "automation_gain": len(gain_set)},
            "cases": cases,
            "case_counts": {n: {c: sum(c in v for v in cases[n].values()) for c in CASES} for n in cases},
            "unattached_connections": {"papers": sum(1 for v in unatt.values() if v), "connections": sum(unatt.values())},
            "pool_sizes": {k: len(v) for k, v in entries.items()}}


def evaluate(papers, entries, prep):
    own_set, pooled_set, gain_set = prep["sets"][OWN], prep["sets"][POOLED], prep["sets"]["automation_gain"]
    all_steps = [x["d"] for x in entries["steps"]]
    med = {"steps": statistics.median(all_steps) if all_steps else 0.0,
           "transfers": statistics.median(x["d"] for x in entries["transfers"]) if entries["transfers"] else 0.0,
           "planning": statistics.median(x["d"] for x in entries["planning"]) if entries["planning"] else 0.0}
    rep = {}
    for row in pooled_set:
        rep[row["paper"]] = reported(plat_of(papers, row))
    per = {OWN: {}, POOLED: {}}
    # reproduction with own durations
    for row in own_set:
        pl = plat_of(papers, row)
        p, _ = configure(pl, "own", Pools(entries, row["paper"]))
        r, err = run_sim(p)
        t, kind = reported(pl)
        per[OWN][row["paper"]] = {"reported": t, "kind": kind, "error": err,
                                  "simulated": r.throughput if r else None, "flagged": r.flagged if r else None,
                                  "own_share": r.own_share if r else None,
                                  "log10_r": math.log10(r.throughput / t) if r and r.throughput > 0 else None,
                                  "bottleneck": max(r.utilisation, key=r.utilisation.get) if r and r.utilisation else None,
                                  "serial_sum": analytic(p)[0], "bottleneck_rate": analytic(p)[1],
                                  "cases": prep["cases"][OWN][row["paper"]], "field": papers[row["paper"]]["tag"]}
    # prediction with pooled durations, against the field-median baseline (leave-one-paper-out)
    reps = {row["paper"]: rep[row["paper"]][0] for row in pooled_set}
    for row in pooled_set:
        pid = row["paper"]
        pl = plat_of(papers, row)
        p, _ = configure(pl, "pooled", Pools(entries, pid))
        r, err = run_sim(p)
        same = [reps[q] for q in reps if q != pid and papers[q]["tag"] == papers[pid]["tag"]]
        base = statistics.median(same or [reps[q] for q in reps if q != pid])
        t = reps[pid]
        d = (abs(math.log10(r.throughput / t)) - abs(math.log10(base / t))) if r and r.throughput > 0 else None
        per[POOLED][pid] = {"reported": t, "kind": rep[pid][1], "error": err, "simulated": r.throughput if r else None,
                            "flagged": r.flagged if r else None, "baseline": base, "d": d,
                            "serial_sum": analytic(p)[0], "bottleneck_rate": analytic(p)[1],
                            "cases": prep["cases"][POOLED][pid], "field": papers[pid]["tag"]}
    summary = {OWN: own_stat(per[OWN]), POOLED: pooled_stat(per[POOLED])}
    # negative control: each paper simulated with the durations of another paper (derangement)
    nc = {}
    for name, rows, statf in ((OWN, own_set, own_stat), (POOLED, pooled_set, pooled_stat)):
        ids = sorted(r["paper"] for r in rows)
        if len(ids) < 2:
            nc[name] = None
            continue
        pi_map = derangement(ids)
        nper = {}
        for row in rows:
            pid = row["paper"]
            pl, plo = plat_of(papers, row), plat_of(papers, next(x for x in rows if x["paper"] == pi_map[pid]))
            p, _ = configure(pl, "own" if name == OWN else "pooled", Pools(entries, pid), durations=nc_durations(plo, med))
            r, err = run_sim(p)
            x = per[name][pid]
            t = x["reported"]
            if name == OWN:
                nper[pid] = {**x, "simulated": r.throughput if r else None, "error": err,
                             "log10_r": math.log10(r.throughput / t) if r and r.throughput > 0 else None}
            else:
                nper[pid] = {**x, "simulated": r.throughput if r else None, "error": err,
                             "d": (abs(math.log10(r.throughput / t)) - abs(math.log10(x["baseline"] / t)))
                             if r and r.throughput > 0 else None}
        nc[name] = {"pairing": pi_map, "summary": statf(nper), "per_paper": nper}
    # automation gain: q = (simulated automated / simulated less automated) / (reported automated / reported less)
    gain = []
    for row in gain_set:
        pl = plat_of(papers, row)
        pv = pl["pv"]
        rep_a = score.per_day(pv["throughput_automated"][0], pv)
        rep_l = score.per_day(pv["throughput_less_automated"][0], pv)
        ids = [x.strip() for x in pv["throughput_less_automated"][0]["qualifier"].split(";")[0].split(",")]
        pa, _ = configure(pl, "pooled", Pools(entries, row["paper"]))
        pls, _ = configure(pl, "pooled", Pools(entries, row["paper"]), less_auto=ids)
        ra, ea = run_sim(pa)
        rl, el = run_sim(pls)
        q = ((ra.throughput / rl.throughput) / (rep_a / rep_l)) if ra and rl and rl.throughput > 0 and ra.throughput > 0 else None
        gain.append({"paper": row["paper"], "q": q, "log10_q": math.log10(q) if q else None, "errors": [ea, el]})
    qs = [x["log10_q"] for x in gain if x["log10_q"] is not None]
    summary["automation_gain"] = {"n": len(gain), "n_simulated": len(qs),
                                  "n_within_1p5x": sum(abs(x) <= TOL for x in qs),
                                  "share_within_1p5x": share_within(qs) if qs else None, "per_paper": gain}
    return {"summary": summary, "negative_control_shuffled_durations": nc, "breakdowns": breakdowns(per),
            "per_paper": per, "medians_for_negative_control": med}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, required=True, help="the SQLite DB build")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    a = ap.parse_args()
    if not a.db.exists():
        sys.exit(f"{a.db} not found")
    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    digest = build_digest(db)
    if digest != EXPECTED_DB_DIGEST:
        print(f"warning: DB content digest {digest} is not the build the manuscript used ({EXPECTED_DB_DIGEST})",
              file=sys.stderr)
    papers = read_papers(db)
    entries = pool_entries(papers)
    a.out.mkdir(parents=True, exist_ok=True)
    prep = {"db_content_digest": digest, **evaluation_sets(papers, entries)}
    (a.out / "evaluation_sets.json").write_text(json.dumps(prep, indent=1) + "\n", encoding="utf-8")
    prep = json.loads((a.out / "evaluation_sets.json").read_text(encoding="utf-8"))
    results = {**evaluate(papers, entries, prep), "db_content_digest": digest,
               "python": sys.version.split()[0], "simpy": simpy.__version__}
    (a.out / "results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    s = results["summary"]
    print(json.dumps({k: {x: y for x, y in v.items() if x != "per_paper"} for k, v in s.items()}, indent=1))
    print(json.dumps({k: (v["summary"] if v else None) for k, v in results["negative_control_shuffled_durations"].items()},
                     indent=1))


if __name__ == "__main__":
    main()
