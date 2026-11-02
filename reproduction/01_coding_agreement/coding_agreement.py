"""Agreement between codings of the 30 test papers.

Four comparisons, all with the pairing and metrics of pairing.py:
  1. Reproducibility of the independent coding: the 10 papers coded twice (reference/ vs recode/): step- and
     connection-identification F1, Cohen's kappa, percent agreement and Gwet's AC1 per field, with paper-level
     bootstrap intervals.
  2. Taxonomy coverage: share of steps, modules and connections of the independent coding (reference/, 30 papers) whose
     label is a taxonomy class (not 'unmapped'), overall and per field tag.
  3. Language-model records (opus_a/) vs the independent coding (reference/): strict micro-F1 per field with
     paper-level bootstrap intervals, identification F1, label agreement and kappa on paired items, confusion table,
     values per difficult case and per field tag, agreement between the two extractions (opus_a/ vs opus_b/) and the
     items on which they disagree (uncertain flags) against errors.
  4. Negative control: each extraction scored against the independent coding of another paper (derangement, seed 7).

Fixed choices:
  - Gwet's AC1 uses Q = number of taxonomy classes of the field + 1 ('unmapped').
  - A paper with several field tags (gold_split.csv field_tag, ';'-separated) counts in each tag.
  - Bootstrap: random.Random(1).choice over the paper list, B = 2000, percentile positions int(0.025 k) and
    int(0.975 k) - 1; replicates with an undefined value are dropped.
  - Uncertain flag: an item of the first extraction unpaired with the second or paired with a different label; an
    error: an item of the first extraction unpaired with the independent coding or paired with a different label.

Usage: python3 coding_agreement.py [--codings DIR] [--gold-split CSV] [--gold-keys CSV] [--taxonomy JSON] [--out DIR]
  --codings holds reference/, recode/, opus_a/, opus_b/ (one <paper_id>.json per paper).
Defaults are the paths inside the project workspace, two levels above this folder.
"""
import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import pairing as P

HERE = Path(__file__).resolve().parent
WS = HERE.parents[1]
B, BOOT_SEED, NC_SEED = 2000, 1, 7

DC = [("dc1_hw_SI_only", "hardware-in-SI-only"),
      ("dc2_multi_platform", "multiple-platforms-or-campaigns"),
      ("dc3_commercial_black_box", "commercial-integrated-platform"),
      ("dc4_implied_human", "implied-human-step"),
      ("dc5_flow_plus_arm", "mixed-flow-and-robot-arm"),
      ("dc6_off_platform", "closed-loop-with-off-platform-step")]
FIELDS = (("steps", "uo", "unit_operation"), ("steps", "mt", "module_type"),
          ("connections", "tm", "transfer_mode"))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def boot_any(fn, papers, b=B, seed=BOOT_SEED):
    """Paper-level bootstrap (resampling as in pairing.boot) for any statistic fn(list of papers)."""
    rng = random.Random(seed)
    vals = []
    for _ in range(b):
        s = [rng.choice(papers) for _ in papers]
        v = fn(s)
        if v == v:
            vals.append(v)
    vals.sort()
    return [vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]], len(vals)


def pct_agree(pairs, f):
    return sum(g[f] == x[f] for g, x in pairs) / len(pairs) if pairs else float("nan")


def gwet_ac1(pairs, f, q):
    if not pairs:
        return float("nan")
    n = len(pairs)
    pa = pct_agree(pairs, f)
    c = Counter([g[f] for g, _ in pairs]) + Counter([x[f] for _, x in pairs])
    pe = sum((m / (2 * n)) * (1 - m / (2 * n)) for m in c.values()) / (q - 1)
    return (pa - pe) / (1 - pe)


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def wjson(path, obj):
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")


def rnd(v):
    """Full precision; an undefined value (NaN) is written as null."""
    return None if v is None or v != v else v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--codings", type=Path, default=WS / "extraction" / "test")
    ap.add_argument("--gold-split", type=Path, default=WS / "collection" / "gold_split.csv")
    ap.add_argument("--gold-keys", type=Path, default=WS / "collection" / "gold_keys.csv")
    ap.add_argument("--taxonomy", type=Path, default=WS / "protocol" / "taxonomy-v1.json")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    a = ap.parse_args(argv)
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    tax = P.configure(a.taxonomy)

    split = {r["cand_id"]: r for r in csv.DictReader(open(a.gold_split, encoding="utf-8"))}
    keys = {r["cand_id"]: r for r in csv.DictReader(open(a.gold_keys, encoding="utf-8"))}
    meta = {}
    for cid, k in keys.items():
        s = split[cid]
        meta[k["paper_id"]] = {"cand_id": cid, "set": s["set"], "recode": s["recode"],
                               "tags": [x.strip() for x in s["field_tag"].split(";") if x.strip()],
                               "dc": {key: s[col] == "yes" for col, key in DC}}
    test_ids = sorted(p for p, m in meta.items() if m["set"] == "test")
    recode_ids = sorted(p for p, m in meta.items() if m["set"] == "test" and m["recode"] == "yes")
    Q = {"uo": sum(len(v) for v in tax["unit_operation"].values()) + 1,
         "mt": len(tax["module_type"]) + 1, "tm": len(tax["transfer_mode"]) + 1}

    # ---------------------------------------------------------- input checksums (files read by this script)
    rows = []
    for d in ("reference", "recode", "opus_a", "opus_b"):
        for p in sorted((a.codings / d).glob("*.json")):
            rows.append([f"{d}/{p.name}", sha(p)])
    for p in (a.gold_split, a.gold_keys, a.taxonomy):
        rows.append([p.name, sha(p)])
    write_csv(out / "inputs_sha256.csv", ["path", "sha256"], rows)

    # ---------------------------------------------------------- 1. reproducibility of the independent coding
    ref_all, rec1 = P.load(a.codings / "reference"), P.load(a.codings / "recode")
    p1 = sorted(set(ref_all) & set(rec1))
    assert p1 == recode_ids, (p1, recode_ids)
    t1 = P.tally(ref_all, rec1, p1)

    def recode_parts(ps):
        sp = [pp for p in ps for pp in t1[p]["steps"]["pairs"]]
        cp = [pp for p in ps for pp in t1[p]["connections"]["pairs"]]
        return {"f1_step": P.ident(t1, ps, "steps"), "f1_conn": P.ident(t1, ps, "connections"),
                "kappa_uo": P.kappa(sp, "uo"), "kappa_mt": P.kappa(sp, "mt"), "kappa_tm": P.kappa(cp, "tm"),
                "sp": sp, "cp": cp}

    r1 = recode_parts(p1)
    r1_ci = {}
    for k in ("f1_step", "f1_conn", "kappa_uo", "kappa_mt", "kappa_tm"):
        ci, nb = boot_any(lambda s, k=k: recode_parts(s)[k], p1)
        r1_ci[k] = {"ci95": [rnd(ci[0]), rnd(ci[1])], "replicates_kept": nb}
    recode_out = {
        "papers": p1, "n_papers": len(p1),
        "n_steps_reference": sum(t1[p]["steps"]["ref"] for p in p1),
        "n_steps_recode": sum(t1[p]["steps"]["ext"] for p in p1),
        "n_steps_paired": len(r1["sp"]),
        "n_connections_reference": sum(t1[p]["connections"]["ref"] for p in p1),
        "n_connections_recode": sum(t1[p]["connections"]["ext"] for p in p1),
        "n_connections_paired": len(r1["cp"]),
        "f1_step_identification": rnd(r1["f1_step"]),
        "f1_connection_identification": rnd(r1["f1_conn"]),
        "kappa_unit_operation": rnd(r1["kappa_uo"]), "kappa_module_type": rnd(r1["kappa_mt"]),
        "kappa_transfer_mode": rnd(r1["kappa_tm"]),
        "pct_agreement_unit_operation": rnd(pct_agree(r1["sp"], "uo")),
        "pct_agreement_module_type": rnd(pct_agree(r1["sp"], "mt")),
        "pct_agreement_transfer_mode": rnd(pct_agree(r1["cp"], "tm")),
        "gwet_ac1_unit_operation": rnd(gwet_ac1(r1["sp"], "uo", Q["uo"])),
        "gwet_ac1_module_type": rnd(gwet_ac1(r1["sp"], "mt", Q["mt"])),
        "gwet_ac1_transfer_mode": rnd(gwet_ac1(r1["cp"], "tm", Q["tm"])),
        "gwet_q": Q, "bootstrap": r1_ci,
    }
    rows = []
    for p in p1:
        r = recode_parts([p])
        rows.append([p, t1[p]["steps"]["ref"], t1[p]["steps"]["ext"], len(r["sp"]), rnd(r["f1_step"]),
                     t1[p]["connections"]["ref"], t1[p]["connections"]["ext"], len(r["cp"]), rnd(r["f1_conn"]),
                     rnd(pct_agree(r["sp"], "uo")), rnd(pct_agree(r["sp"], "mt")), rnd(pct_agree(r["cp"], "tm")),
                     rnd(r["kappa_uo"]), rnd(r["kappa_mt"]), rnd(r["kappa_tm"])])
    write_csv(out / "recode_per_paper.csv",
              ["paper_id", "steps_ref", "steps_recode", "steps_paired", "f1_step", "conn_ref", "conn_recode",
               "conn_paired", "f1_conn", "pct_agree_uo", "pct_agree_mt", "pct_agree_tm", "kappa_uo", "kappa_mt",
               "kappa_tm"], rows)
    wjson(out / "recode_summary.json", recode_out)

    # ---------------------------------------------------------- data of comparisons 2-4
    ref, A, Bx = ref_all, P.load(a.codings / "opus_a"), P.load(a.codings / "opus_b")
    papers = sorted(set(ref) & set(A))
    assert papers == test_ids and sorted(Bx) == test_ids, papers

    # ---------------------------------------------------------- 2. taxonomy coverage
    classes = {"steps": ("unit_operation", {c for v in tax["unit_operation"].values() for c in v}),
               "modules": ("module_type", set(tax["module_type"])),
               "connections": ("transfer_mode", set(tax["transfer_mode"]))}

    def mapped(ps):
        res = {}
        for kind, (lab, cls) in classes.items():
            vals = [x[lab] for p in ps for x in ref[p][kind]]
            res[kind] = (sum(v in cls for v in vals), len(vals))
        return res

    m = mapped(papers)
    cov_out = {"n_papers": len(papers)}
    for k, (nm, n) in m.items():
        cov_out[f"n_{k}"] = n
        cov_out[f"n_{k}_mapped"] = nm
        cov_out[f"n_{k}_unmapped"] = n - nm
        cov_out[f"mapped_share_{k}"] = rnd(nm / n)
    tags = sorted({t for p in papers for t in meta[p]["tags"]})
    cov_tag, rows = {}, []
    for tg in tags:
        ps = [p for p in papers if tg in meta[p]["tags"]]
        mm = mapped(ps)
        cov_tag[tg] = {"n_papers": len(ps),
                       **{f"mapped_share_{k}": rnd(nm / n) if n else None for k, (nm, n) in mm.items()}}
        rows.append([tg, len(ps)] + [x for k in ("steps", "modules", "connections") for x in mm[k]])
    cov_out["per_field_tag"] = cov_tag
    write_csv(out / "taxonomy_coverage_per_field_tag.csv",
              ["field_tag", "n_papers", "steps_mapped", "steps_n", "modules_mapped", "modules_n",
               "connections_mapped", "connections_n"], rows)
    rows = []
    for p in papers:
        for kind, (lab, cls) in classes.items():
            idk = {"steps": "step_id", "modules": "module_id", "connections": "edge_id"}[kind]
            for x in ref[p][kind]:
                if x[lab] not in cls:
                    rows.append([p, kind, x[idk], x[lab], x.get("unmapped_note", "")])
    write_csv(out / "taxonomy_unmapped_items.csv", ["paper_id", "kind", "item_id", "label", "unmapped_note"], rows)
    wjson(out / "taxonomy_coverage_summary.json", cov_out)

    # ---------------------------------------------------------- 3. records vs independent coding
    t = P.tally(ref, A, papers)

    def field_block(tt, ps, ci=True):
        res = {}
        for kind, f, name in FIELDS:
            tp = sum(tt[p][kind][f] for p in ps)
            pr = sum(tt[p][kind]["paired"] for p in ps)
            d = {"strict_micro_f1": rnd(P.micro(tt, ps, kind, f)), "n_correct": tp, "n_paired": pr,
                 "label_accuracy_paired": rnd(tp / pr) if pr else None}
            if ci:
                lo, hi = P.boot(tt, ps, kind, f)
                d["ci95"] = [rnd(lo), rnd(hi)]
            res[name] = d
        for kind in ("steps", "connections"):
            res[f"identification_f1_{kind}"] = rnd(P.ident(tt, ps, kind))
            res[f"n_{kind}_reference"] = sum(tt[p][kind]["ref"] for p in ps)
            res[f"n_{kind}_extraction"] = sum(tt[p][kind]["ext"] for p in ps)
            res[f"n_{kind}_paired"] = sum(tt[p][kind]["paired"] for p in ps)
        return res

    allp = {k: [pp for p in papers for pp in t[p][k]["pairs"]] for k in ("steps", "connections")}
    ext_out = {"n_papers": len(papers), "fields": field_block(t, papers),
               "kappa_paired": {name: rnd(P.kappa(allp[kind], f)) for kind, f, name in FIELDS}}

    # confusion table on paired items, plus misses (reference item unpaired) and extras
    conf = Counter()
    for p in papers:
        for kind, fs in (("steps", ("uo", "mt")), ("connections", ("tm",))):
            pr, ug, ux = P.pair(P.items(ref[p], kind), P.items(A[p], kind))
            for f in fs:
                for g, x in pr:
                    conf[(f, g[f], x[f])] += 1
                for g in ug:
                    conf[(f, g[f], "(missed)")] += 1
                for x in ux:
                    conf[(f, "(extra)", x[f])] += 1
    fname = {f: name for _, f, name in FIELDS}
    write_csv(out / "extraction_confusion.csv", ["field", "reference_label", "extraction_label", "count"],
              sorted([fname[f], ra, xb, c] for (f, ra, xb), c in conf.items()))
    ext_out["offdiagonal_paired"] = {fname[f]: sum(c for (ff, ra, xb), c in conf.items() if ff == f and ra != xb
                                                   and ra != "(extra)" and xb != "(missed)") for f in fname}

    # per difficult case and per field tag (no interval)
    per_case, rows = {}, []
    for col, key in DC:
        ps = [p for p in papers if meta[p]["dc"][key]]
        blk = field_block(t, ps, ci=False) if ps else None
        per_case[key] = {"n_papers": len(ps), **({} if blk is None else blk)}
        if ps:
            rows.append([key, len(ps)] + [blk[name][x] for _, _, name in FIELDS
                                          for x in ("strict_micro_f1", "label_accuracy_paired")]
                        + [blk["identification_f1_steps"], blk["identification_f1_connections"]])
    ext_out["per_difficult_case"] = per_case
    write_csv(out / "extraction_per_case.csv",
              ["case", "n_papers", "uo_strict_f1", "uo_label_acc", "mt_strict_f1", "mt_label_acc", "tm_strict_f1",
               "tm_label_acc", "ident_f1_steps", "ident_f1_connections"], rows)
    per_tag, rows = {}, []
    for tg in tags:
        ps = [p for p in papers if tg in meta[p]["tags"]]
        blk = field_block(t, ps, ci=False)
        per_tag[tg] = {"n_papers": len(ps), **blk}
        rows.append([tg, len(ps)] + [blk[name][x] for _, _, name in FIELDS
                                     for x in ("strict_micro_f1", "label_accuracy_paired")]
                    + [blk["identification_f1_steps"], blk["identification_f1_connections"]])
    ext_out["per_field_tag"] = per_tag
    write_csv(out / "extraction_per_field_tag.csv",
              ["field_tag", "n_papers", "uo_strict_f1", "uo_label_acc", "mt_strict_f1", "mt_label_acc",
               "tm_strict_f1", "tm_label_acc", "ident_f1_steps", "ident_f1_connections"], rows)
    rows = []
    for p in papers:
        r = t[p]
        sf = lambda k, f: rnd(2 * r[k][f] / (r[k]["ref"] + r[k]["ext"])) if r[k]["ref"] + r[k]["ext"] else None
        rows.append([p, r["steps"]["ref"], r["steps"]["ext"], r["steps"]["paired"], r["connections"]["ref"],
                     r["connections"]["ext"], r["connections"]["paired"], sf("steps", "uo"), sf("steps", "mt"),
                     sf("connections", "tm")])
    write_csv(out / "extraction_per_paper.csv",
              ["paper_id", "steps_ref", "steps_ext", "steps_paired", "conn_ref", "conn_ext", "conn_paired",
               "uo_strict_f1", "mt_strict_f1", "tm_strict_f1"], rows)

    # agreement of the two extractions, and uncertain flags against errors
    tab = P.tally(A, Bx, papers)
    ext_out["two_extractions_strict_f1"] = {name: rnd(P.micro(tab, papers, kind, f)) for kind, f, name in FIELDS}
    tp = fp = fn = tn_ = 0
    for p in papers:
        for kind, fs in (("steps", ("uo", "mt")), ("connections", ("tm",))):
            ab, ua, _ = P.pair(P.items(A[p], kind), P.items(Bx[p], kind))
            unc = {x["id"] for x in ua} | {x["id"] for x, y in ab if any(x[f] != y[f] for f in fs)}
            ra, _, ux = P.pair(P.items(ref[p], kind), P.items(A[p], kind))
            wrong = {x["id"] for x in ux} | {x["id"] for g, x in ra if any(g[f] != x[f] for f in fs)}
            for it in P.items(A[p], kind):
                u, w = it["id"] in unc, it["id"] in wrong
                tp += u and w; fp += u and not w; fn += (not u) and w; tn_ += (not u) and (not w)
    ext_out["uncertain_flags"] = {"flagged_wrong": tp, "flagged_right": fp, "unflagged_wrong": fn,
                                  "unflagged_right": tn_, "precision": rnd(tp / max(1, tp + fp)),
                                  "recall": rnd(tp / max(1, tp + fn))}
    wjson(out / "extraction_summary.json", ext_out)

    # ---------------------------------------------------------- 4. negative control (derangement)
    rng = random.Random(NC_SEED); perm = papers[:]
    while any(x == y for x, y in zip(papers, perm)):
        rng.shuffle(perm)
    shuf = {p: ref[q] for p, q in zip(papers, perm)}
    tn = P.tally(shuf, A, papers)
    nc_case = {}
    for col, key in DC:
        ps = [p for p in papers if meta[p]["dc"][key]]
        blk = field_block(tn, ps, ci=False) if ps else None
        nc_case[key] = {"n_papers": len(ps), **({} if blk is None else
                                               {name: blk[name]["strict_micro_f1"] for _, _, name in FIELDS})}
    nc_out = {"n_papers": len(papers), "seed": NC_SEED, "fields": field_block(tn, papers),
              "per_difficult_case": nc_case, "n_fixed_points": sum(x == y for x, y in zip(papers, perm))}
    write_csv(out / "negative_control_derangement.csv", ["extraction_paper_id", "scored_against_reference_of"],
              list(zip(papers, perm)))
    wjson(out / "negative_control_summary.json", nc_out)
    print("done:", sorted(x.name for x in out.iterdir()))


if __name__ == "__main__":
    main()
