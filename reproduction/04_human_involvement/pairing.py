"""Item pairing and agreement metrics for comparing two codings of the same papers.

A coding is one JSON file per paper (keys: modules, steps, connections). Steps and connections of two codings of a
paper are paired by three rules, applied in order:
  R1  same evidence location (document + figure/table/scheme number, or document + page + section/paragraph) -> pair;
      when one location holds several items, items of the same (platform, unit-operation family) pair first, then the
      rest, one-to-one in workflow (id) order.
  R2  otherwise, same platform and same unit-operation family -> the k-th unpaired step of that family in one coding
      pairs with the k-th in the other. Connections: same platform and same (from module type, to module type).
  R3  unpaired items are misses (first coding) or extras (second coding).
Metrics: identification F1 (2 x paired / (n1 + n2)); strict micro-F1 per field (paired and label equal); Cohen's
kappa on paired items; paper-level cluster bootstrap 95% percentile interval (B = 2000, seed 1).
Call configure(taxonomy_path) once before items() or pair() are used.
"""
import json
import random
import re
from collections import Counter
from pathlib import Path

FAM = {}
R1_FAM = True    # R1 tie-break: within one evidence location, same (platform, family) items pair first


def configure(taxonomy_path):
    """Unit-operation families from the taxonomy file (taxonomy-v1.json)."""
    tax = json.loads(Path(taxonomy_path).read_text(encoding="utf-8"))
    FAM.clear()
    FAM.update({c: f for f, cs in tax["unit_operation"].items() for c in cs})
    FAM["unmapped"] = "unmapped"
    return tax


def load(d):
    """{paper_id: coding} for every <paper_id>.json in directory d."""
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(d).glob("*.json"))}


def evkey(ev):
    parts = [x.strip() for x in ev.split(";")]
    doc = parts[0].lower() if parts else ""
    page = parts[1] if len(parts) > 1 else ""
    loc = parts[2].lower() if len(parts) > 2 else ""
    m = re.match(r"(fig(?:ure)?|table|scheme)\.?\s*(s?\d+)", loc)
    if m:
        return (doc, m.group(1)[:3] if m.group(1).startswith("fig") else m.group(1), m.group(2))
    return (doc, page, re.sub(r"\s+", "", loc))


def num(i):
    return int(re.search(r"(\d+)$", i).group(1))


def plat(i):
    return i.split("/")[1]


def items(c, kind):
    mt = {m["module_id"]: m["module_type"] for m in c["modules"]}
    out = []
    if kind == "steps":
        for s in sorted(c["steps"], key=lambda s: (plat(s["step_id"]), num(s["step_id"]))):
            out.append({"id": s["step_id"], "plat": plat(s["step_id"]), "ev": evkey(s["evidence"]),
                        "uo": s["unit_operation"], "fam": FAM.get(s["unit_operation"], "unmapped"),
                        "mt": mt.get(s["module_ids"][0], "unmapped") if s["module_ids"] else "unmapped"})
    else:
        for e in sorted(c["connections"], key=lambda e: (plat(e["edge_id"]), num(e["edge_id"]))):
            out.append({"id": e["edge_id"], "plat": plat(e["edge_id"]), "ev": evkey(e["evidence"]),
                        "tm": e["transfer_mode"], "fam": (mt.get(e["from_module"]), mt.get(e["to_module"]))})
    return out


def pair(G, X):
    pairs, ug, ux = [], list(G), list(X)
    for key in {g["ev"] for g in G} & {x["ev"] for x in X}:            # R1
        if R1_FAM:   # within one location, same (platform, family) first, then the rest in id order
            for k in {(g["plat"], g["fam"]) for g in ug if g["ev"] == key}:
                gs = [g for g in ug if g["ev"] == key and (g["plat"], g["fam"]) == k]
                xs = [x for x in ux if x["ev"] == key and (x["plat"], x["fam"]) == k]
                for g, x in zip(gs, xs):
                    pairs.append((g, x)); ug.remove(g); ux.remove(x)
        gs = [g for g in ug if g["ev"] == key]
        xs = [x for x in ux if x["ev"] == key]
        for g, x in zip(gs, xs):
            pairs.append((g, x)); ug.remove(g); ux.remove(x)
    for k in {(g["plat"], g["fam"]) for g in ug}:                        # R2
        gs = [g for g in ug if (g["plat"], g["fam"]) == k]
        xs = [x for x in ux if (x["plat"], x["fam"]) == k]
        for g, x in zip(gs, xs):
            pairs.append((g, x)); ug.remove(g); ux.remove(x)
    return pairs, ug, ux                                                  # R3


def kappa(pairs, f):
    if not pairs:
        return float("nan")
    a = [g[f] for g, _ in pairs]; b = [x[f] for _, x in pairs]
    po = sum(i == j for i, j in zip(a, b)) / len(a)
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in ca) / len(a) ** 2
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def tally(ref, ext, papers):
    """Per-paper counts: n_ref, n_ext, n_paired, and per-field strict TP."""
    t = {}
    for p in papers:
        row = {}
        for kind, fields in (("steps", ("uo", "mt")), ("connections", ("tm",))):
            pr, _, _ = pair(items(ref[p], kind), items(ext[p], kind))
            row[kind] = {"ref": len(items(ref[p], kind)), "ext": len(items(ext[p], kind)), "paired": len(pr),
                         **{f: sum(g[f] == x[f] for g, x in pr) for f in fields}, "pairs": pr}
        t[p] = row
    return t


def micro(t, papers, kind, f):
    tp = sum(t[p][kind][f] for p in papers); r = sum(t[p][kind]["ref"] for p in papers)
    e = sum(t[p][kind]["ext"] for p in papers)
    return 2 * tp / (r + e) if r + e else float("nan")


def ident(t, papers, kind):
    pr = sum(t[p][kind]["paired"] for p in papers); r = sum(t[p][kind]["ref"] for p in papers)
    e = sum(t[p][kind]["ext"] for p in papers)
    return 2 * pr / (r + e) if r + e else float("nan")


def boot(t, papers, kind, f, B=2000, seed=1):
    rng = random.Random(seed); vals = []
    for _ in range(B):
        s = [rng.choice(papers) for _ in papers]
        v = micro(t, s, kind, f)
        if v == v:
            vals.append(v)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]
