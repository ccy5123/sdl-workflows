"""Agreement of the timing-data extraction (Opus 5.5) with an independent extraction (Fable 5.1) on the test papers,
and the cross-paper negative control.

Usage (from the workspace root, standard library only):
  python3 reproduction/03_throughput/timing_agreement.py \
      --extraction extraction/process/opus --reference extraction/process/fable \
      --root . --out reproduction/03_throughput/out/timing_agreement

  --extraction  folder of <paper_id>.json timing-data extractions being checked
  --reference   folder of the independent extractions; the papers scored are those present in both folders
  --root        folder the record-coding paths inside the extraction files are relative to
  --out         output folder; writes results.json

Scoring uses the functions of agreement_scoring.py (same folder). Field (a): reported throughput per platform; field
(b): step duration per step; an item agrees when both extractions give a value within 10% of each other. Paper-level
cluster bootstrap, B = 2000, seed 1, percentile 95% interval. The negative control pairs the extraction of paper i with
the independent extraction of a different paper pi(i) (random.Random(1), reshuffled until no paper is paired with
itself), platforms paired by order and steps by step order, then scores and bootstraps the same way.
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agreement_scoring as score  # noqa: E402

FIELDS = (("a", "throughput_per_platform"), ("b", "step_duration_per_step"))


def per_paper_items(ext, ref, root, derange):
    """The per-paper items exactly as agreement_scoring.main() builds them."""
    papers = sorted(p.stem for p in ext.glob("*.json") if (ref / p.name).exists())
    pair = {p: p for p in papers}
    if derange:
        rng = random.Random(1)
        while True:
            perm = papers[:]
            rng.shuffle(perm)
            if all(a != b for a, b in zip(papers, perm)):
                break
        pair = dict(zip(papers, perm))
    out, other, kinds = {}, {}, [0, 0]
    for p in papers:
        da, db_ = score.load(ext / f"{p}.json"), score.load(ref / f"{pair[p]}.json")
        rec = score.load(root / da["record_coding"])
        if derange:
            recb = score.load(root / db_["record_coding"])
            ia, ib = score.paper_items(da, da, rec), score.paper_items(db_, db_, recb)
            items = {}
            for f in ("a", "b"):
                la, lb = [x[1] for x in ia[f]], [x[2] for x in ib[f]]
                m = max(len(la), len(lb))
                la, lb = la + [None] * (m - len(la)), lb + [None] * (m - len(lb))
                items[f] = [(f"pos{i}", x, y) for i, (x, y) in enumerate(zip(la, lb))]
            out[p] = items
            continue
        out[p] = score.paper_items(da, db_, rec)
        for q, (n, k) in score.other_agreement(da, db_).items():
            on, ok = other.get(q, (0, 0))
            other[q] = (on + n, ok + k)
        for pl in rec["platforms"]:
            ta, tb = score.throughput(da, pl["platform_id"]), score.throughput(db_, pl["platform_id"])
            if ta and tb:
                kinds[0] += 1
                kinds[1] += ta[1] == tb[1]
    return papers, pair, out, other, kinds


def field_stats(papers, items):
    res = {}
    for f, name in FIELDS:
        share, n = score.share(items, f, papers)
        lo, hi = score.boot(items, f, papers) if n else (None, None)
        both = sum(1 for p in papers for _, a, b in items[p][f] if a is not None and b is not None)
        res[name] = {"items": n, "both_valued": both, "agreement": share, "ci95": [lo, hi],
                     "papers_with_items": sum(1 for p in papers if items[p][f])}
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extraction", type=Path, required=True)
    ap.add_argument("--reference", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    papers, _, items, other, kinds = per_paper_items(a.extraction, a.reference, a.root, derange=False)
    res = field_stats(papers, items)
    _, pair_nc, items_nc, _, _ = per_paper_items(a.extraction, a.reference, a.root, derange=True)
    res_nc = field_stats(papers, items_nc)

    results = {
        "papers": papers, "n_papers": len(papers), "bootstrap_B": 2000, "bootstrap_seed": 1, "tolerance": 0.10,
        "timing_agreement": {
            **res,
            "throughput_kind_agreement": {"both_give_throughput": kinds[0], "same_kind": kinds[1]},
            "other_quantities": {q: {"items": n, "agreeing": k} for q, (n, k) in sorted(other.items())}},
        "negative_control_cross_paper": {"pairing": pair_nc, **res_nc},
    }
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    for label, r in (("agreement", res), ("negative control", res_nc)):
        for name, x in r.items():
            print(f"{label}: {name}: items {x['items']}, both valued {x['both_valued']}, agreement {x['agreement']}, "
                  f"95% CI {x['ci95']}")
    print(f"same throughput kind: {kinds[1]}/{kinds[0]}")


if __name__ == "__main__":
    main()
