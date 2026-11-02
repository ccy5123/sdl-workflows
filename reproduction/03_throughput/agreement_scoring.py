"""Agreement between two process-information (timing-data) extraction folders.

Usage: python3 agreement_scoring.py <dir_a> <dir_b> [--root <dir>] [--derange]
  dir_a: the extraction being checked (Opus 5.5), dir_b: the independent extraction (Fable 5.1); files <paper_id>.json
  in both. Each file names its record coding by a path relative to --root (default: the current directory).
  --derange  cross-paper negative control: pair each paper of dir_a with a different paper of dir_b (seed 1) by item
             position

Rules:
  field (a) throughput per platform, normalised to experiments per calendar day (rate x experiments_per_count;
  a batch count x batch_size); field (b) step duration in minutes x ceil(b / n) per batch. An item is a
  platform/step with a value in at least one extraction; it agrees iff both give a value and |a / b - 1| <= 0.10.
  Paper-level cluster bootstrap, B = 2000, percentile 95% interval, seed 1.

The functions are those of the scorer used for the manuscript; timing_agreement.py imports them.
"""
import json
import math
import random
import re
import sys
from pathlib import Path

T_PER_DAY = {"s": 86400.0, "min": 1440.0, "h": 24.0, "d": 1.0, "week": 1.0 / 7.0}
T_MIN = {"s": 1 / 60, "min": 1.0, "h": 60.0, "d": 1440.0}
TOL = 0.10
OTHER_Q = ("batch_size", "parallel_units", "planning_time", "operating_hours_per_day", "operating_days_per_week",
           "experiments_per_count", "cost", "throughput_less_automated", "throughput_automated",
           "transfer_agent_count", "units", "transfer_time", "duration_batch_size")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def plat_values(d, pid):
    out = {}
    for r in d["process_items"]:
        if r["target_kind"] == "platform" and r["target_id"] == pid:
            out.setdefault(r["quantity"], []).append(r)
    return out


def per_day(row, pv):
    m = re.fullmatch(r"(experiments|samples|batches)/([1-9][0-9]*)?([a-z]+)|([a-z]+)/(experiment|sample|batch)", row["unit"])
    if m.group(1):
        noun, rate = m.group(1), row["value"] * T_PER_DAY[m.group(3)] / int(m.group(2) or 1)
    else:
        noun = {"experiment": "experiments", "sample": "samples", "batch": "batches"}[m.group(5)]
        rate = T_PER_DAY[m.group(4)] / row["value"]
    if noun == "samples" and "experiments_per_count" in pv:
        rate *= pv["experiments_per_count"][0]["value"]
    if noun == "batches" and "batch_size" in pv:
        rate *= pv["batch_size"][0]["value"]
    return rate


def throughput(d, pid):
    pv = plat_values(d, pid)
    rows = pv.get("throughput", [])
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: 0 if r["qualifier"].startswith("measured") else 1)
    return per_day(rows[0], pv), rows[0]["qualifier"].split(";")[0]


def durations(d, rec):
    plat_of = {s["step_id"]: s["step_id"].rsplit("/", 1)[0] for s in rec["steps"]}
    by = {}
    for r in d["step_process"]:
        by.setdefault(r["step_id"], {})[r["quantity"]] = r
    out = {}
    for sid, q in by.items():
        if "duration" not in q:
            continue
        v = q["duration"]["value"] * T_MIN[q["duration"]["unit"]]
        pv = plat_values(d, plat_of[sid])
        if "duration_batch_size" in q and "batch_size" in pv:
            v *= math.ceil(pv["batch_size"][0]["value"] / q["duration_batch_size"]["value"])
        out[sid] = v
    return out


def agree(x, y):
    return x is not None and y is not None and abs(x / y - 1) <= TOL


def paper_items(da, db, rec):
    """Return {'a': [(id, va, vb)], 'b': [...]} for one paper."""
    items = {"a": [], "b": []}
    for p in rec["platforms"]:
        ta, tb = throughput(da, p["platform_id"]), throughput(db, p["platform_id"])
        if ta or tb:
            items["a"].append((p["platform_id"], ta and ta[0], tb and tb[0]))
    xa, xb = durations(da, rec), durations(db, rec)
    for s in rec["steps"]:
        sid = s["step_id"]
        if sid in xa or sid in xb:
            items["b"].append((sid, xa.get(sid), xb.get(sid)))
    return items


def share(per_paper, field, papers):
    n = k = 0
    for p in papers:
        for _, a, b in per_paper[p][field]:
            n += 1
            k += agree(a, b)
    return (k / n if n else None), n


def boot(per_paper, field, papers, B=2000, seed=1):
    rng = random.Random(seed)
    vals = []
    for _ in range(B):
        s, n = share(per_paper, field, [rng.choice(papers) for _ in papers])
        if n:
            vals.append(s)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]


def other_agreement(da, db):
    def keyed(d):
        out = {}
        for r in d["process_items"]:
            if r["quantity"] in OTHER_Q:
                q = r["qualifier"] if r["quantity"] in ("operating_hours_per_day", "operating_days_per_week", "transfer_agent_count") else ""
                out[(r["target_id"], r["quantity"], q)] = r["value"]
        for r in d["step_process"]:
            if r["quantity"] in OTHER_Q:
                out[(r["step_id"], r["quantity"], "")] = r["value"]
        return out
    ka, kb = keyed(da), keyed(db)
    res = {}
    for key in set(ka) | set(kb):
        n, k = res.get(key[1], (0, 0))
        res[key[1]] = (n + 1, k + agree(ka.get(key), kb.get(key)))
    return res


def main(argv):
    derange = "--derange" in argv
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else Path(".")
    skip = {argv.index("--root") + 1} if "--root" in argv else set()
    dir_a, dir_b = [Path(a) for i, a in enumerate(argv) if not a.startswith("--") and i not in skip][:2]
    papers = sorted(p.stem for p in dir_a.glob("*.json") if (dir_b / p.name).exists())
    pair = {p: p for p in papers}
    if derange:
        rng = random.Random(1)
        while True:
            perm = papers[:]
            rng.shuffle(perm)
            if all(a != b for a, b in zip(papers, perm)):
                break
        pair = dict(zip(papers, perm))
    per_paper, other, kinds = {}, {}, [0, 0]
    for p in papers:
        da, db = load(dir_a / f"{p}.json"), load(dir_b / f"{pair[p]}.json")
        rec = load(root / da["record_coding"])
        if derange:
            recb = load(root / db["record_coding"])
            ia = paper_items(da, da, rec)
            ib = paper_items(db, db, recb)
            items = {}
            for f in ("a", "b"):
                la, lb = [x[1] for x in ia[f]], [x[2] for x in ib[f]]
                m = max(len(la), len(lb))
                la, lb = la + [None] * (m - len(la)), lb + [None] * (m - len(lb))
                items[f] = [(f"pos{i}", x, y) for i, (x, y) in enumerate(zip(la, lb))]
            per_paper[p] = items
            continue
        per_paper[p] = paper_items(da, db, rec)
        for q, (n, k) in other_agreement(da, db).items():
            on, ok = other.get(q, (0, 0))
            other[q] = (on + n, ok + k)
        for pl in rec["platforms"]:
            ta, tb = throughput(da, pl["platform_id"]), throughput(db, pl["platform_id"])
            if ta and tb:
                kinds[0] += 1
                kinds[1] += ta[1] == tb[1]
    print(f"papers: {len(papers)}{' (deranged pairing)' if derange else ''}")
    for f, name in (("a", "throughput per platform"), ("b", "step duration per step")):
        s, n = share(per_paper, f, papers)
        lo, hi = boot(per_paper, f, papers) if n else (None, None)
        both = sum(1 for p in papers for _, a, b in per_paper[p][f] if a is not None and b is not None)
        print(f"({f}) {name}: items {n}, both-valued {both}, agreement {s if s is None else round(s, 3)}, "
              f"95% CI [{lo if lo is None else round(lo, 3)}, {hi if hi is None else round(hi, 3)}]")
    if not derange:
        print(f"throughput kind agreement where both give one: {kinds[1]}/{kinds[0]}")
        print("other quantities (items, agreeing):", {q: other[q] for q in sorted(other)})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
