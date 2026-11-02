"""Dependence on people by unit operation, from the database records of 238 papers.

Usage:
  python3 human_involvement.py [--db SQLITE] [--workspace DIR] [--confusion CSV] [--taxonomy JSON] [--out DIR]
    --db         the SQLite build (opened read-only); default ../../db/sdl-db.sqlite
    --workspace  directory against which the coding-file paths stored in the build (coding.source_path) resolve;
                 default ../.. (the project workspace)
    --confusion  confusion table of the records against the independent coding of the 30 test papers, written by
                 ../01_coding_agreement/coding_agreement.py (extraction_confusion.csv); default that file
    --taxonomy   taxonomy-v1.json (unit-operation families used to pair steps); default ../../protocol/taxonomy-v1.json
Writes to --out (default ./out): results.json, shares.csv, field_counts.csv.

Definitions:
  Records: the database-record coding of each paper (view db_record_coding), steps from v_step, connections from
  v_connection, all modules of a step from step_module. Module ids are keyed by (coding_id, module_id).
  A step depends on people if (a) performed_by = 'human', (b) its primary module is off the platform
  (v_step.on_platform = 0; a step without a primary module does not meet (b)), or (c) a v_connection row with
  transfer_mode = 'human_transfer' has from_module or to_module among the step's modules.
  Paper p contains unit operation u iff a step of p has unit_operation u; p depends on people for u iff such a step does.
  Weights: papers are linked when their platforms share platform_identity_member.identity_id; w_p = 1 / size of p's
  connected component (platform group). Weights are held as integers W_p = L / size (L = lcm of the component sizes) so
  that weighted counts are exact.
  Field: v_step.first_field_tag (primary field). For each unit operation (not 'unmapped'), the number of primary fields
  (not 'unmapped', not missing) with weighted n >= 5 in which the weighted share is >= 0.5, and the number in which it
  is < 0.5, are reported.
  Bootstrap: random.Random(1); each of B = 2000 replicates draws len(papers) papers by rng.choice over the
  paper_id-sorted list; weights fixed from the full build; a cell with weighted n = 0 in a replicate is dropped for
  that cell; 95% percentile interval = sorted values at positions int(0.025 k) and int(0.975 k) - 1.
  Further tables (shares.csv, column analysis): each condition (a), (b), (c) alone; step-level counts; unweighted;
  all field tags of a paper; early (v_era 'train', first public in or before 2023) and late (v_era 'test', in or after
  2024) papers; unit-operation family; without the 40 independently coded papers; items flagged uncertain excluded.
  Relabelling: records relabelled by drawing from the confusion table (see relabel()); per-label miss rates.
  Paired comparison: records vs the independent (reference) coding on the 30 test papers (see paired_comparison()).
"""
import argparse
import csv
import hashlib
import json
import random
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from math import lcm
from pathlib import Path

import pairing as P

HERE = Path(__file__).resolve().parent
WS = HERE.parents[1]
DB_PATH = WS / "db" / "sdl-db.sqlite"
CONFUSION = HERE.parent / "01_coding_agreement" / "out" / "extraction_confusion.csv"
TAXONOMY = WS / "protocol" / "taxonomy-v1.json"
B, BOOT_SEED = 2000, 1
S1_B, S1_SEED = 2000, 1
N_MIN = 5                         # per-field counts use primary fields with weighted n >= 5; share >= 0.5 is 2 hd >= n
ALL = "(all)"                     # group label of the overall share
UNMAPPED = "unmapped"
EXTRA = "(extra)"
MISSED = "(missed)"
REFERENCE_CODING = ("reference", "claude-fable-5-1", "fable-5.1-reference-test", "extraction/prompt-v1.md")
STEP_COLS = ("paper_id", "coding_id", "platform_id", "step_id", "step_order", "unit_operation", "family", "performed_by",
             "primary_module_id", "primary_module_type", "on_platform", "first_field_tag", "era", "uncertain")
CONN_COLS = ("paper_id", "coding_id", "platform_id", "edge_id", "from_module", "to_module", "transfer_mode", "stated",
             "uncertain")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def connect_ro(path=DB_PATH):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


# ---------- reading the build ----------
def edge_num(e):
    m = re.search(r"(\d+)$", e or "")
    if not m:
        raise SystemExit(f"edge_id without a trailing number: {e!r}")
    return int(m.group(1))


def load(db):
    """All database-record records the analysis uses. Steps in (paper_id, platform_id, step_order) order, connections
    in (paper_id, platform_id, edge number) order."""
    papers = [p for (p,) in db.execute("SELECT paper_id FROM db_record_coding ORDER BY paper_id")]
    if len(set(papers)) != len(papers):
        raise SystemExit("a paper has more than one database-record coding")
    steps = [dict(zip(STEP_COLS, r)) for r in db.execute(
        f"SELECT {', '.join(STEP_COLS)} FROM v_step ORDER BY paper_id, platform_id, step_order")]
    sm = defaultdict(set)
    for c, s, m in db.execute("SELECT sm.coding_id, sm.step_id, sm.module_id FROM step_module sm "
                              "JOIN db_record_coding r ON r.coding_id = sm.coding_id"):
        sm[(c, s)].add((c, m))
    for s in steps:
        s["modules"] = frozenset(sm.get((s["coding_id"], s["step_id"]), ()))
        s["uncertain"] = int(s["uncertain"])
    conns = [dict(zip(CONN_COLS, r)) for r in db.execute(f"SELECT {', '.join(CONN_COLS)} FROM v_connection")]
    for c in conns:
        c["uncertain"] = int(c["uncertain"])
    conns.sort(key=lambda c: (c["paper_id"], c["platform_id"], edge_num(c["edge_id"])))
    field = {}
    for s in steps:
        if field.setdefault(s["paper_id"], s["first_field_tag"]) != s["first_field_tag"]:
            raise SystemExit(f"two first field tags for {s['paper_id']}")
    era = dict(db.execute("SELECT v.paper_id, v.era FROM v_era v JOIN db_record_coding r ON r.paper_id = v.paper_id"))
    tags = defaultdict(list)
    for p, t in db.execute("SELECT r.paper_id, t.field_tag FROM db_record_coding r JOIN coding_field_tag t "
                           "ON t.coding_id = r.coding_id ORDER BY r.paper_id, t.position"):
        tags[p].append(t)
    gold = {p for (p,) in db.execute("SELECT paper_id FROM gold_membership")}
    W, L, comps = weights(db, papers)
    return {"papers": papers, "steps": steps, "conns": conns, "field": {p: field.get(p) for p in papers},
            "era": {p: era.get(p) for p in papers}, "tags": {p: tuple(tags.get(p, ())) for p in papers},
            "gold": gold & set(papers), "W": W, "L": L, "components": comps}


def weights(db, papers):
    """Connected components of papers linked by a shared platform_identity_member.identity_id (database-record
    codings)."""
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
    size = {p: len(comp[find(p)]) for p in papers}
    L = lcm(*sorted(set(size.values()))) if papers else 1
    return {p: L // size[p] for p in papers}, L, sorted(sorted(c) for c in comp.values())


# ---------- the indicator and the tables ----------
def human_modules(conns):
    return {(c["coding_id"], m) for c in conns if c["transfer_mode"] == "human_transfer"
            for m in (c["from_module"], c["to_module"])}


def components(steps, conns):
    """(a, b, c) per step."""
    ht = human_modules(conns)
    return [(s["performed_by"] == "human", s["on_platform"] == 0, bool(s["modules"] & ht)) for s in steps]


def composite(comp):
    return [a or b or c for a, b, c in comp]


def cells(rows):
    """rows: (paper, label, depends on people) per step -> {paper: {label: paper depends on people for label}}."""
    out = defaultdict(dict)
    for p, u, h in rows:
        out[p][u] = out[p].get(u, False) or bool(h)
    return out


def step_cells(steps, ind, key="unit_operation"):
    return cells((s["paper_id"], s[key], h) for s, h in zip(steps, ind))


def tally(cl, W, seq, groups):
    """{(label, group): [sum W over papers containing label, sum W over those depending on people]} over the paper list
    seq (repeats count again); group ALL is every paper, otherwise each group in groups[p]."""
    t = defaultdict(lambda: [0, 0])
    for p in seq:
        w = W[p]
        gs = (ALL,) + tuple(groups.get(p, ()))
        for u, hd in cl.get(p, {}).items():
            for g in gs:
                c = t[(u, g)]
                c[0] += w
                c[1] += w * hd
    return t


def field_counts(t, L):
    """{label: [fields with weighted n >= 5 and share >= 0.5, fields with weighted n >= 5 and share < 0.5]};
    'unmapped' labels and the groups ALL, 'unmapped' and missing are not counted."""
    cnt = defaultdict(lambda: [0, 0])
    for (u, g), (n, hd) in t.items():
        if u == UNMAPPED or g in (ALL, UNMAPPED, None) or n < N_MIN * L:
            continue
        cnt[u][0 if 2 * hd >= n else 1] += 1
    return cnt


def pct(v):
    """95% percentile interval of a sorted list."""
    return (v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]) if v else (None, None)


def first_field_groups(d):
    return {p: (() if f is None else (f,)) for p, f in d["field"].items()}


def table(cl, W, L, seq, groups):
    t = tally(cl, W, seq, groups)
    return {"t": t, "cnt": field_counts(t, L), "L": L}


def bootstrap(cl, W, L, papers, groups, b=B, seed=BOOT_SEED):
    """Paper-level cluster bootstrap; weights fixed. Returns ({(label, group): (lo, hi, replicates kept)}, b)."""
    rng = random.Random(seed)
    vals = defaultdict(list)
    for _ in range(b):
        seq = [rng.choice(papers) for _ in papers]
        t = tally(cl, W, seq, groups)
        for k, (n, hd) in t.items():
            if n:
                vals[k].append(hd / n)
    return {k: (*pct(sorted(v)), len(v)) for k, v in vals.items()}, b


# ---------- relabelling and uncertain items ----------
def read_confusion(path=CONFUSION):
    """P(reference label | extraction label) per field from the confusion table, '(extra)' included as a reference
    label; rows with extraction label '(missed)' give the per-label miss rates (missed / all reference items with that
    label)."""
    dist = defaultdict(lambda: defaultdict(Counter))
    ref_total = defaultdict(Counter)
    missed = defaultdict(Counter)
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            f, g, x, n = r["field"], r["reference_label"], r["extraction_label"], int(r["count"])
            if x == MISSED:
                missed[f][g] += n
            else:
                dist[f][x][g] += n
            if g != EXTRA:
                ref_total[f][g] += n
    table_ = {f: {x: (sorted(c), [c[g] for g in sorted(c)]) for x, c in d.items()} for f, d in dist.items()}
    miss = {f: {g: {"missed": missed[f][g], "reference_items": ref_total[f][g],
                    "miss_rate": missed[f][g] / ref_total[f][g]} for g in sorted(ref_total[f])} for f in sorted(ref_total)}
    return table_, miss


def draw(rng, tab, lab):
    if lab not in tab:
        return lab
    labels, w = tab[lab]
    return rng.choices(labels, weights=w)[0]


def relabel(d, conf, b=S1_B, seed=S1_SEED):
    """Monte Carlo relabelling. Per replicate, in this order: for each step (paper_id, platform_id, step_order) its
    unit_operation, then (if it has a primary module) the primary module's module_type; then for each connection
    (paper_id, platform_id, edge number) its transfer_mode. '(extra)' drawn for a unit operation deletes the step, for a
    transfer mode the connection; module_type draws are reported only (share of steps with a primary module whose drawn
    type differs from the recorded one, '(extra)' counted as different) and change nothing. (a), (b) stay as recorded;
    (c) is recomputed from the kept connections with their drawn modes."""
    rng = random.Random(seed)
    uo_t, mt_t, tm_t = conf.get("unit_operation", {}), conf.get("module_type", {}), conf.get("transfer_mode", {})
    steps, conns, W, papers = d["steps"], d["conns"], d["W"], d["papers"]
    groups = first_field_groups(d)
    shares = defaultdict(list)
    mt_share, del_steps, del_conns = [], [], []
    for _ in range(b):
        new_uo, n_mt, n_mt_changed = [], 0, 0
        for s in steps:
            new_uo.append(draw(rng, uo_t, s["unit_operation"]))
            if s["primary_module_id"] is not None:
                n_mt += 1
                n_mt_changed += draw(rng, mt_t, s["primary_module_type"]) != s["primary_module_type"]
        kept_conns = []
        for c in conns:
            tm = draw(rng, tm_t, c["transfer_mode"])
            if tm != EXTRA:
                kept_conns.append({**c, "transfer_mode": tm})
        ht = human_modules(kept_conns)
        rows = [(s["paper_id"], u, s["performed_by"] == "human" or s["on_platform"] == 0 or bool(s["modules"] & ht))
                for s, u in zip(steps, new_uo) if u != EXTRA]
        t = tally(cells(rows), W, papers, groups)
        for (u, g), (n, hd) in t.items():
            if g == ALL and n:
                shares[u].append(hd / n)
        mt_share.append(n_mt_changed / n_mt if n_mt else None)
        del_steps.append(len(steps) - len(rows))
        del_conns.append(len(conns) - len(kept_conns))

    def q(v):
        v = sorted(x for x in v if x is not None)
        return {"median": statistics.median(v), "q025": pct(v)[0], "q975": pct(v)[1]} if v else None

    per_u = {u: {"share": q(v), "replicates": len(v)} for u, v in sorted(shares.items())}
    return {"B": b, "seed": seed, "per_unit_operation": per_u,
            "primary_module_type_changed_share": q(mt_share), "steps_deleted": q(del_steps),
            "connections_deleted": q(del_conns)}


def uncertain_excluded(d):
    steps = [s for s in d["steps"] if not s["uncertain"]]
    conns = [c for c in d["conns"] if not c["uncertain"]]
    tb = table(step_cells(steps, composite(components(steps, conns))), d["W"], d["L"], d["papers"], first_field_groups(d))
    tb["steps_excluded"] = len(d["steps"]) - len(steps)
    tb["connections_excluded"] = len(d["conns"]) - len(conns)
    return tb


# ---------- paired comparison with the independent coding (30 test papers) ----------
def coding_steps(db, coding_id):
    """{step_id: (performed_by, on_platform of the primary module or None, composite, primary module id or None)} of
    one coding, from the base tables with the v_step definition (primary module = step_module position 1)."""
    steps = [dict(zip(("step_id", "performed_by", "primary_module_id", "on_platform"), r)) for r in db.execute(
        "SELECT s.step_id, s.performed_by, sm.module_id, m.on_platform FROM step s "
        "LEFT JOIN step_module sm ON sm.coding_id = s.coding_id AND sm.step_id = s.step_id AND sm.position = 1 "
        "LEFT JOIN module m ON m.coding_id = sm.coding_id AND m.module_id = sm.module_id "
        "WHERE s.coding_id = ? ORDER BY s.step_id", (coding_id,))]
    sm = defaultdict(set)
    for s, m in db.execute("SELECT step_id, module_id FROM step_module WHERE coding_id = ?", (coding_id,)):
        sm[s].add((coding_id, m))
    for s in steps:
        s["modules"] = frozenset(sm[s["step_id"]])
    conns = [{"coding_id": coding_id, "from_module": f, "to_module": t, "transfer_mode": m} for f, t, m in db.execute(
        "SELECT from_module, to_module, transfer_mode FROM connection WHERE coding_id = ?", (coding_id,))]
    return {s["step_id"]: (s["performed_by"], s["on_platform"], h, s["primary_module_id"])
            for s, h in zip(steps, composite(components(steps, conns)))}


def coding_modules(db, coding_id):
    """{module_id: on_platform} of one coding."""
    return dict(db.execute("SELECT module_id, on_platform FROM module WHERE coding_id = ?", (coding_id,)))


def coding_json(db, coding_id, root):
    """The coding JSON file the build was made from; stops if it differs from the sha256 stored in the build."""
    path, want = db.execute("SELECT c.source_path, f.sha256 FROM coding c JOIN source_file f ON f.path = c.source_path "
                            "WHERE c.coding_id = ?", (coding_id,)).fetchone()
    if sha(root / path) != want:
        raise SystemExit(f"{path} differs from the sha256 recorded in the build")
    return json.loads((root / path).read_text(encoding="utf-8"))


def agreement(pairs):
    if not pairs:
        return {"n": 0, "agreement": None, "kappa": None}
    k = P.kappa(pairs, "v")
    return {"n": len(pairs), "agreement": sum(g["v"] == x["v"] for g, x in pairs) / len(pairs),
            "kappa": None if k != k else k}


def codings_of_test_papers(db):
    """Test papers and their (reference, database-record) coding ids; stops unless each has exactly one of each."""
    test = [p for (p,) in db.execute("SELECT paper_id FROM gold_membership WHERE gold_set = 'test' ORDER BY paper_id")]
    rec = defaultdict(list)
    for p, c in db.execute("SELECT paper_id, coding_id FROM db_record_coding"):
        rec[p].append(c)
    ref = defaultdict(list)
    for p, c in db.execute("SELECT paper_id, coding_id FROM coding WHERE role = ? AND model_id = ? AND coder_label = ? "
                           "AND prompt_path = ?", REFERENCE_CODING):
        ref[p].append(c)
    bad = [p for p in test if len(rec[p]) != 1 or len(ref[p]) != 1]
    if bad:
        raise SystemExit(f"test papers without exactly one database-record and one reference coding: {bad}")
    return [(p, ref[p][0], rec[p][0]) for p in test]


def paired_comparison(db, root=WS):
    """Test papers: database-record coding vs the independent (reference) coding. Steps are paired with pairing.py on
    the coding JSON files the build was made from, reference as the first argument of pair(). performed_by and the
    composite indicator are compared on paired steps. Modules: pairing.py pairs steps and connections only, so the
    paired modules are the de-duplicated set of (reference primary module, record primary module) pairs taken from
    paired steps where both sides have a primary module; on_platform agreement and Cohen's kappa are computed over that
    set; a module in two or more distinct pairs keeps every pair and is counted as a many-to-one conflict (per side);
    the unpaired module count of a coding is the number of its modules on the test papers that no module pair reaches;
    paired steps where either side has no primary module are counted."""
    pb, hd, mpairs = [], [], set()
    per_paper, n_ref_unpaired, n_rec_unpaired, n_op_missing = {}, 0, 0, 0
    ref_mod, rec_mod = {}, {}          # (paper, module_id) -> on_platform, all modules of each coding
    for p, rc, dc in codings_of_test_papers(db):
        gi, xi = coding_steps(db, rc), coding_steps(db, dc)
        ref_mod.update({(p, m): o for m, o in coding_modules(db, rc).items()})
        rec_mod.update({(p, m): o for m, o in coding_modules(db, dc).items()})
        pairs, ug, ux = P.pair(P.items(coding_json(db, rc, root), "steps"),
                               P.items(coding_json(db, dc, root), "steps"))
        n_ref_unpaired += len(ug)
        n_rec_unpaired += len(ux)
        for g, x in pairs:
            a, b = gi[g["id"]], xi[x["id"]]
            pb.append(({"v": a[0]}, {"v": b[0]}))
            hd.append(({"v": a[2]}, {"v": b[2]}))
            if a[3] is None or b[3] is None:
                n_op_missing += 1
            else:
                mpairs.add(((p, a[3]), (p, b[3])))
        per_paper[p] = {"paired_steps": len(pairs), "reference_unpaired_steps": len(ug), "db_record_unpaired_steps": len(ux)}
    mpairs = sorted(mpairs)
    op = [({"v": ref_mod[g]}, {"v": rec_mod[x]}) for g, x in mpairs]
    ref_n, rec_n = Counter(g for g, _ in mpairs), Counter(x for _, x in mpairs)
    conf_ref, conf_rec = sum(n > 1 for n in ref_n.values()), sum(n > 1 for n in rec_n.values())
    return {"papers": len(per_paper), "paired_steps": len(pb), "reference_unpaired_steps": n_ref_unpaired,
            "db_record_unpaired_steps": n_rec_unpaired, "performed_by": agreement(pb),
            "composite": agreement(hd), "module_pairs": len(mpairs),
            "on_platform_module_pairs": agreement(op),
            "module_pair_conflicts_reference_side": conf_ref, "module_pair_conflicts_db_record_side": conf_rec,
            "module_pair_conflicts": conf_ref + conf_rec,
            "reference_modules": len(ref_mod), "db_record_modules": len(rec_mod),
            "reference_unpaired_modules": len(set(ref_mod) - set(ref_n)),
            "db_record_unpaired_modules": len(set(rec_mod) - set(rec_n)),
            "paired_steps_without_primary_module": n_op_missing, "per_paper": per_paper}


# ---------- the whole analysis ----------
def rows_of(tb, analysis, group_kind, ci=None):
    """Long-format rows of a table; weighted values are divided by L."""
    L = tb["L"]
    out = []
    for (u, g), (n, hd) in sorted(tb["t"].items(), key=lambda kv: (kv[0][0], kv[0][1] != ALL, str(kv[0][1]))):
        lo, hi, k = (ci or {}).get((u, g), (None, None, None))
        out.append({"analysis": analysis, "label": u, "group_kind": "all" if g == ALL else group_kind, "group": g,
                    "weighted_n": n / L, "weighted_hd": hd / L, "share": hd / n if n else None,
                    "ci95_lo": lo, "ci95_hi": hi, "ci_replicates": k})
    return out


def field_summary(tb):
    return {u: {"fields_share_ge_half": a, "fields_share_lt_half": b} for u, (a, b) in sorted(tb["cnt"].items())}


def analyse(db, root=WS, conf_path=CONFUSION, b=B, s1_b=S1_B):
    d = load(db)
    W, L, papers = d["W"], d["L"], d["papers"]
    ff = first_field_groups(d)
    comp = components(d["steps"], d["conns"])
    ind = composite(comp)
    rows = []
    res = {"papers": len(papers), "steps": len(d["steps"]), "connections": len(d["conns"]),
           "components": len(d["components"]), "multi_paper_components": sum(len(c) > 1 for c in d["components"]),
           "papers_in_multi_paper_components": sum(len(c) for c in d["components"] if len(c) > 1),
           "largest_component": max((len(c) for c in d["components"]), default=0), "L": L,
           "multi_paper_component_members": [c for c in d["components"] if len(c) > 1],
           "papers_without_steps": sorted(set(papers) - {s["paper_id"] for s in d["steps"]}),
           "papers_without_first_field_tag": sorted(p for p in papers if d["field"][p] is None)}

    # main table and bootstrap
    cl = step_cells(d["steps"], ind)
    main = table(cl, W, L, papers, ff)
    ci, nb = bootstrap(cl, W, L, papers, ff, b=b)
    rows += rows_of(main, "main", "first_field_tag", ci)
    labels = sorted({u for u, _ in main["t"]})
    res["main"] = {"fields": field_summary(main), "bootstrap": {"B": nb, "seed": BOOT_SEED}}

    # further tables
    further = {}
    for name, k in (("a_performed_by_human", 0), ("b_primary_module_off_platform", 1), ("c_human_transfer", 2)):
        tb = table(step_cells(d["steps"], [x[k] for x in comp]), W, L, papers, ff)
        rows += rows_of(tb, f"condition_{name}", "first_field_tag")
    st = defaultdict(lambda: [0, 0])
    for s, h in zip(d["steps"], ind):
        for g in (ALL,) + ff[s["paper_id"]]:
            st[(s["unit_operation"], g)][0] += 1
            st[(s["unit_operation"], g)][1] += h
    rows += rows_of({"t": st, "L": 1}, "step_level", "first_field_tag")
    ones = {p: 1 for p in papers}
    rows += rows_of(table(cl, ones, 1, papers, ff), "unweighted", "first_field_tag")
    rows += rows_of(table(cl, W, L, papers, d["tags"]), "all_field_tags", "field_tag")
    further["period"] = {}
    for e, name in (("train", "early"), ("test", "late")):     # v_era values: 'train' <= 2023, 'test' >= 2024
        tb = table(cl, W, L, [p for p in papers if d["era"][p] == e], ff)
        rows += rows_of(tb, f"period_{name}", "first_field_tag")
        further["period"][name] = {"papers": sum(d["era"][p] == e for p in papers), "fields": field_summary(tb)}
    further["period_missing_papers"] = sorted(p for p in papers if d["era"][p] is None)
    rows += rows_of(table(step_cells(d["steps"], ind, "family"), W, L, papers, ff), "unit_operation_family",
                    "first_field_tag")
    no_gold = [p for p in papers if p not in d["gold"]]
    rows += rows_of(table(cl, W, L, no_gold, ff), "without_independently_coded_papers", "first_field_tag")
    further["independently_coded_papers"] = len(d["gold"])
    further["condition_counts"] = {"a": sum(x[0] for x in comp), "b": sum(x[1] for x in comp), "c": sum(x[2] for x in comp),
                                "composite": sum(ind), "steps": len(comp),
                                "steps_without_primary_module": sum(s["primary_module_id"] is None for s in d["steps"])}
    res["further"] = further

    # relabelling, uncertain items excluded, paired comparison
    conf, miss = read_confusion(conf_path)
    s1 = relabel(d, conf, b=s1_b)
    s1["miss_rates"] = miss
    s2 = uncertain_excluded(d)
    rows += rows_of(s2, "uncertain_items_excluded", "first_field_tag")
    res["relabelling"] = s1
    res["uncertain_items_excluded"] = {"fields": field_summary(s2), "steps_excluded": s2["steps_excluded"],
                                       "connections_excluded": s2["connections_excluded"]}
    res["paired_comparison"] = paired_comparison(db, root)

    fc = []
    for u in labels:
        a, bb = main["cnt"].get(u, (0, 0))
        fc.append({"unit_operation": u, "fields_share_ge_half": None if u == UNMAPPED else a,
                   "fields_share_lt_half": None if u == UNMAPPED else bb})
    return res, rows, fc


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def write_outputs(res, rows, fc, od):
    od.mkdir(parents=True, exist_ok=True)
    (od / "results.json").write_text(json.dumps(res, ensure_ascii=True, indent=1) + "\n", encoding="utf-8")
    write_csv(od / "shares.csv", rows)
    write_csv(od / "field_counts.csv", fc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--workspace", type=Path, default=WS)
    ap.add_argument("--confusion", type=Path, default=CONFUSION)
    ap.add_argument("--taxonomy", type=Path, default=TAXONOMY)
    ap.add_argument("--out", type=Path, default=HERE / "out")
    a = ap.parse_args(argv)
    P.configure(a.taxonomy)
    db = connect_ro(a.db)
    try:
        res, rows, fc = analyse(db, a.workspace, a.confusion)
    finally:
        db.close()
    write_outputs(res, rows, fc, a.out)
    print("written:", sorted(x.name for x in a.out.iterdir()))


if __name__ == "__main__":
    main()
