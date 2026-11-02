"""Paired comparisons on the recorded per-paper throughput values (no new simulation).

  ~/.venvs/sdl-db-03/bin/python throughput_comparisons.py \
      --results ../03_throughput/out/throughput/results.json --out out

Reads per_paper of the results.json written by ../03_throughput/throughput.py and imports TOL, B, SEED and boot from
that script unchanged (SimPy is needed only because throughput.py imports it).

Reproduction test with own durations (35 papers):
- share within a factor of 1.5 of the reported throughput for the simulation (a paper whose simulation failed counts as
  outside, as in throughput.py), the serial-sum estimate and the slowest-module (bottleneck-rate) estimate, and the
  paired differences simulation minus each estimate;
- campaign-measured minus nominal reported throughput: share within 1.5x among the simulated papers of each kind
  (the failed paper is left out, as in the recorded breakdown), with a stratified bootstrap (each replicate draws, with
  random.Random(1), the measured papers from the sorted measured list and then the nominal papers from the sorted
  nominal list, each group keeping its size) and, for comparison, an unstratified one (the simulated papers drawn
  together; a replicate with no paper of one kind is dropped);
- median fold error = 10 ** median |log10(estimate / reported)| over the papers with an estimate.
Prediction test with pooled durations (128 papers): share within 1.5x for the field-median baseline, the simulation
(failed = outside), the serial-sum and bottleneck-rate estimates; paired difference simulation minus baseline; median
fold errors.
Intervals: throughput.boot (B = 2000, random.Random(1).choice over the sorted paper list, percentile positions
int(0.025 B) and min(B - 1, int(0.975 B))), except the two kind comparisons described above, which use the same
positions.

Output: out/throughput_comparisons.json.
"""
import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "03_throughput"))
from throughput import B, POOLED, OWN, SEED, TOL, boot  # noqa: E402

mean = lambda xs: sum(xs) / len(xs)


def within(est, rep):
    return 1.0 if est and est > 0 and abs(math.log10(est / rep)) <= TOL else 0.0


def share(ind):
    """value and interval of the share of papers with indicator 1."""
    return {"n": len(ind), "n_within_1p5x": int(sum(ind.values())), "share_within_1p5x": mean(list(ind.values())),
            "ci95": list(boot(ind, mean))}


def paired(a, b):
    v = {k: (a[k], b[k]) for k in a}
    return {"n": len(v), "value": mean([x - y for x, y in v.values()]),
            "ci95": list(boot(v, lambda xs: mean([x - y for x, y in xs])))}


def fold(per, key, ref="reported"):
    errs = {k: abs(math.log10(v[key] / v[ref])) for k, v in per.items() if v.get(key) and v[key] > 0}
    med = lambda xs: statistics.median(xs)
    lo, hi = boot(errs, med)
    m = med(list(errs.values()))
    return {"n": len(errs), "median_abs_log10_error": m, "ci95": [lo, hi], "median_fold_error": 10 ** m,
            "median_fold_error_ci95": [10 ** lo, 10 ** hi]}


def pct(vals):
    vals = sorted(vals)
    return [vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]]


def kind_difference(per):
    sim = {k: v for k, v in per.items() if v["log10_r"] is not None}
    ind = {k: float(abs(v["log10_r"]) <= TOL) for k, v in sim.items()}
    meas = sorted(k for k in sim if sim[k]["kind"] == "measured")
    nom = sorted(k for k in sim if sim[k]["kind"] == "nominal")
    sm, sn = mean([ind[k] for k in meas]), mean([ind[k] for k in nom])
    rng = random.Random(SEED)
    strat = []
    for _ in range(B):
        dm = [ind[rng.choice(meas)] for _ in meas]
        dn = [ind[rng.choice(nom)] for _ in nom]
        strat.append(mean(dm) - mean(dn))
    rng = random.Random(SEED)
    allp = sorted(sim)
    unstrat = []
    for _ in range(B):
        draw = [rng.choice(allp) for _ in allp]
        dm = [ind[k] for k in draw if sim[k]["kind"] == "measured"]
        dn = [ind[k] for k in draw if sim[k]["kind"] == "nominal"]
        if dm and dn:
            unstrat.append(mean(dm) - mean(dn))
    return {"measured": {"n_simulated": len(meas), "n_within_1p5x": int(sum(ind[k] for k in meas)), "share": sm},
            "nominal": {"n_simulated": len(nom), "n_within_1p5x": int(sum(ind[k] for k in nom)), "share": sn},
            "failed_left_out": sorted(k for k, v in per.items() if v["log10_r"] is None),
            "difference_measured_minus_nominal": sm - sn,
            "ci95_stratified": pct(strat), "replicates_stratified": len(strat),
            "ci95_unstratified": pct(unstrat), "replicates_unstratified": len(unstrat)}


def main(results, out):
    r = json.loads(Path(results).read_text(encoding="utf-8"))
    own, pooled = r["per_paper"][OWN], r["per_paper"][POOLED]
    res = {"input": {"results": str(results), "db_content_digest": r["db_content_digest"]},
           "bootstrap": {"B": B, "seed": SEED}, "tolerance_log10": TOL}

    sim = {k: (1.0 if v["log10_r"] is not None and abs(v["log10_r"]) <= TOL else 0.0) for k, v in own.items()}
    ser = {k: within(v["serial_sum"], v["reported"]) for k, v in own.items()}
    bot = {k: within(v["bottleneck_rate"], v["reported"]) for k, v in own.items()}
    res[OWN] = {
        "n_papers": len(own),
        "share_within_1p5x": {"simulation": share(sim), "serial_sum": share(ser), "bottleneck_rate": share(bot)},
        "paired_difference": {"simulation_minus_serial_sum": paired(sim, ser),
                              "simulation_minus_bottleneck_rate": paired(sim, bot)},
        "measured_vs_nominal": kind_difference(own),
        "median_fold_error": {"simulation": fold(own, "simulated"), "serial_sum": fold(own, "serial_sum"),
                              "bottleneck_rate": fold(own, "bottleneck_rate")}}

    psim = {k: (1.0 if v["simulated"] and abs(math.log10(v["simulated"] / v["reported"])) <= TOL else 0.0)
            for k, v in pooled.items()}
    pbase = {k: within(v["baseline"], v["reported"]) for k, v in pooled.items()}
    pser = {k: within(v["serial_sum"], v["reported"]) for k, v in pooled.items()}
    pbot = {k: within(v["bottleneck_rate"], v["reported"]) for k, v in pooled.items()}
    psim_only = {k: psim[k] for k, v in pooled.items() if v["simulated"]}
    res[POOLED] = {
        "n_papers": len(pooled),
        "share_within_1p5x": {"field_median_baseline": share(pbase), "simulation": share(psim),
                              "simulation_simulated_papers_only": share(psim_only),
                              "serial_sum": share(pser), "bottleneck_rate": share(pbot)},
        "paired_difference": {"simulation_minus_field_median_baseline": paired(psim, pbase)},
        "median_fold_error": {"simulation": fold(pooled, "simulated"), "field_median_baseline": fold(pooled, "baseline"),
                              "serial_sum": fold(pooled, "serial_sum"),
                              "bottleneck_rate": fold(pooled, "bottleneck_rate")}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "throughput_comparisons.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True, help="results.json written by 03_throughput/throughput.py")
    ap.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args()
    main(a.results, Path(a.out))
