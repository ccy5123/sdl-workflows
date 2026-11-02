"""Synthetic tests of throughput.py (configuration, attachment, sets, pools, statistics, breakdowns) and of the
timing-data agreement scoring. No DB paper is read.

Run from this folder: python -m unittest test_throughput.py
"""
import json
import math
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agreement_scoring as S  # noqa: E402
import throughput as H  # noqa: E402
import timing_agreement as TA  # noqa: E402
from simulator import simulate  # noqa: E402


def step(sid, order, mods, uo="synthesize", fam="synthesis", by="robot", pmt="reactor"):
    return {"sid": sid, "order": order, "uo": uo, "family": fam, "by": by, "pmt": pmt, "tag": "chem", "modules": mods}


def item(kind, tid, q, v, unit, qual=""):
    return {"target_kind": kind, "target_id": tid, "quantity": q, "value": v, "unit": unit, "qualifier": qual}


def platform(name, steps, conns=(), items=(), sp=None, units=None, ttime=None):
    pv = defaultdict(list)
    for it in items:
        pv[it["quantity"]].append(it)
    return {"pid": f"{name}/P1", "tag": "chem", "steps": steps, "conns": list(conns), "pv": pv, "units": units or {},
            "ttime": ttime or {}, "sp": sp or {}}


def paper(name, pl):
    return {"paper": name, "tag": "chem", "items": [r for v in pl["pv"].values() for r in v], "platforms": [pl]}


class EvalTests(unittest.TestCase):
    def test_attach_rule(self):
        st = [step("X/P1/S1", 1, ["X/P1/M1"]), step("X/P1/S2", 2, ["X/P1/M2"]), step("X/P1/S3", 3, ["X/P1/M3"])]
        conns = [{"eid": "X/P1/E1", "a": "X/P1/M1", "b": "X/P1/M2", "mode": "robot_arm_gantry", "material": 1},
                 {"eid": "X/P1/E2", "a": "X/P1/M1", "b": "X/P1/M3", "mode": "fixed_tubing", "material": 1},
                 {"eid": "X/P1/E3", "a": "X/P1/M3", "b": "X/P1/M1", "mode": "human_transfer", "material": 1},
                 {"eid": "X/P1/E4", "a": "X/P1/M2", "b": "X/P1/M3", "mode": "data_transfer", "material": 0}]
        att, un = H.attach(platform("X", st, conns))
        self.assertEqual([(j, c["eid"]) for j, c in att], [(1, "X/P1/E1"), (2, "X/P1/E2")])
        self.assertEqual(un, 1)

    def test_configure_own_pooled_and_covered(self):
        # target paper X: S1 joint 60 min covering S2, S3 has no duration, S4 plan step; planning_time 10 min
        st = [step("X/P1/S1", 1, ["X/P1/M1"]), step("X/P1/S2", 2, ["X/P1/M2"]), step("X/P1/S3", 3, ["X/P1/M3"]),
              step("X/P1/S4", 4, ["X/P1/M4"], uo="plan_next_experiment", fam="plan", by="software")]
        sp = {"X/P1/S1": {"duration": (60.0, "covers X/P1/S1, X/P1/S2")}}
        x = platform("X", st, items=[item("platform", "X/P1", "planning_time", 10, "min")], sp=sp)
        others = {}
        for i, d in enumerate((20.0, 40.0, 30.0)):     # three other papers with one synthesize/reactor step each
            n = f"O{i}"
            others[n] = paper(n, platform(n, [step(f"{n}/P1/S1", 1, [f"{n}/P1/M1"])], sp={f"{n}/P1/S1": {"duration": (d, "")}}))
        papers = {"X": paper("X", x), **others}
        entries = H.pool_entries(papers)
        self.assertEqual(len(entries["steps"]), 3)     # the joint duration of X is not pooled
        p, _ = H.configure(x, "own", H.Pools(entries, "X"))
        self.assertEqual([s.duration for s in p.steps], [60.0, 0.0, 30.0, 0.0])   # S3 = median of 20, 40, 30
        self.assertEqual([s.own for s in p.steps], [True, True, False, True])
        self.assertEqual((p.planning, p.plan_index), (10, 3))
        q, _ = H.configure(x, "pooled", H.Pools(entries, "X"))
        self.assertEqual([s.duration for s in q.steps][:3], [30.0, 30.0, 30.0])
        self.assertEqual(q.planning, 0.0)              # empty planning pool apart from X itself
        self.assertGreater(simulate(p).throughput, 0)

    def test_sets_and_reported(self):
        st = [step("X/P1/S1", 1, ["X/P1/M1"]), step("X/P1/S2", 2, ["X/P1/M2"])]
        x = platform("X", st, items=[item("platform", "X/P1", "throughput", 2, "experiments/h", "measured")],
                     sp={"X/P1/S1": {"duration": (30.0, "")}})
        y = platform("Y", st, items=[item("platform", "Y/P1", "throughput", 1, "experiments/h", "nominal"),
                                     item("platform", "Y/P1", "throughput_less_automated", 1, "experiments/d", "Y/P1/S1; nominal"),
                                     item("platform", "Y/P1", "throughput_automated", 3, "experiments/d", "nominal")])
        own_set, pooled_set, gain_set = H.sets({"X": paper("X", x), "Y": paper("Y", y)})
        self.assertEqual([r["paper"] for r in own_set], ["X"])   # Y has no own duration
        self.assertEqual([r["paper"] for r in pooled_set], ["X", "Y"])
        self.assertEqual([r["paper"] for r in gain_set], ["Y"])
        self.assertEqual(H.reported(x), (48.0, "measured"))

    def test_cases(self):
        st = [step("X/P1/S1", 1, ["X/P1/M1"], by="human"), step("X/P1/S2", 2, ["X/P1/M2"])]
        conns = [{"eid": f"X/P1/E{i}", "a": "X/P1/M1", "b": "X/P1/M2", "mode": "robot_arm_gantry", "material": 1} for i in (1, 2)]
        x = platform("X", st, conns, items=[item("platform", "X/P1", "batch_size", 4, "samples")],
                     sp={"X/P1/S1": {"duration": (100.0, "")}, "X/P1/S2": {"duration": (10.0, "")}})
        p, _ = H.configure(x, "own", H.Pools({"steps": [], "transfers": [], "planning": []}, "X"))
        self.assertEqual(H.cases_of(x, p), H.CASES[:4])

    def test_statistics(self):
        per = {f"P{i:02d}": {"log10_r": 0.0 if i < 15 else 1.0, "flagged": False} for i in range(25)}
        s = H.own_stat(per)
        self.assertEqual((s["n"], s["n_within_1p5x"], s["share_within_1p5x"]), (25, 15, 0.6))
        self.assertTrue(s["ci95"][0] <= 0.6 <= s["ci95"][1])
        per["P00"]["log10_r"] = None                 # a failed simulation counts as outside 1.5x
        s = H.own_stat(per)
        self.assertAlmostEqual(s["share_within_1p5x"], 14 / 25)
        self.assertEqual(s["n_simulated"], 24)
        self.assertEqual(H.own_stat({})["share_within_1p5x"], None)
        per2 = {f"P{i:02d}": {"d": -0.5, "flagged": False} for i in range(20)}
        per2["P99"] = {"d": None, "flagged": False}  # failed: left out of the mean, counted
        s2 = H.pooled_stat(per2)
        self.assertEqual((s2["n"], s2["n_simulated"], s2["mean_d"], s2["ci95"]), (21, 20, -0.5, [-0.5, -0.5]))
        self.assertTrue(all(k != v for k, v in H.derangement([str(i) for i in range(10)]).items()))

    def test_analytic(self):
        st = [step("X/P1/S1", 1, ["X/P1/M1"]), step("X/P1/S2", 2, ["X/P1/M2"])]
        x = platform("X", st, sp={"X/P1/S1": {"duration": (30.0, "")}, "X/P1/S2": {"duration": (60.0, "")}})
        p, _ = H.configure(x, "own", H.Pools({"steps": [], "transfers": [], "planning": []}, "X"))
        serial, bottleneck = H.analytic(p)
        self.assertAlmostEqual(serial, 1440 / 90)
        self.assertAlmostEqual(bottleneck, 1440 / 90)   # one stream: the closed loop binds before the 60-min step

    def test_breakdowns(self):
        per = {H.OWN: {f"P{i:02d}": {"log10_r": 0.05 * i, "kind": "measured", "cases": [H.CASES[0]], "field": "chem",
                                     "serial_sum": 10.0, "bottleneck_rate": 12.0, "reported": 10.0, "flagged": False,
                                     "error": None, "own_share": 0.6, "bottleneck": "M1"} for i in range(22)},
               H.POOLED: {f"P{i:02d}": {"d": -0.1, "kind": "nominal", "cases": [], "field": "chem", "serial_sum": None,
                                        "bottleneck_rate": None, "reported": 10.0, "flagged": False, "error": None,
                                        "baseline": 5.0} for i in range(22)}}
        bd = H.breakdowns(per)
        self.assertEqual(bd[H.OWN]["by_kind"]["measured"]["n"], 22)
        self.assertEqual(bd[H.OWN]["by_own_duration_coverage"]["0.5-0.75"]["n"], 22)
        self.assertEqual(bd[H.OWN]["simple_estimates_within_1p5x"], {"serial_sum": 1.0, "bottleneck_rate": 1.0})
        self.assertAlmostEqual(bd[H.POOLED]["by_field"]["chem"]["mean_d"], -0.1)
        self.assertIsNone(bd[H.POOLED]["simple_estimates_within_1p5x"]["serial_sum"])


class AgreementTests(unittest.TestCase):
    def test_agree_and_share(self):
        self.assertTrue(S.agree(1.0, 1.1))
        self.assertFalse(S.agree(1.0, 1.2))
        self.assertFalse(S.agree(None, 1.0))
        per = {"A": {"a": [("x", 1.0, 1.05)]}, "B": {"a": [("y", 1.0, None), ("z", 2.0, 2.0)]}}
        self.assertEqual(S.share(per, "a", ["A", "B"]), (2 / 3, 3))
        lo, hi = S.boot(per, "a", ["A", "B"])
        self.assertTrue(0.5 <= lo <= hi <= 1.0)

    def test_per_day_normalisation(self):
        pv = {"batch_size": [{"value": 8}]}
        self.assertAlmostEqual(S.per_day({"unit": "batches/d", "value": 2}, pv), 16.0)
        self.assertAlmostEqual(S.per_day({"unit": "h/experiment", "value": 2}, {}), 12.0)

    def test_timing_agreement_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for d in ("ext", "ref", "rec"):
                (root / d).mkdir()
            for i, (va, vb) in enumerate(((10, 10.5), (20, 30), (5, 5))):
                pid = f"P{i}"
                rec = {"platforms": [{"platform_id": f"{pid}/P1"}], "steps": [{"step_id": f"{pid}/P1/S1"}]}
                (root / "rec" / f"{pid}.json").write_text(json.dumps(rec))
                for d, v in (("ext", va), ("ref", vb)):
                    x = {"record_coding": f"rec/{pid}.json",
                         "process_items": [item("platform", f"{pid}/P1", "throughput", v, "experiments/d", "measured")],
                         "step_process": [{"step_id": f"{pid}/P1/S1", "quantity": "duration", "value": v, "unit": "min",
                                           "qualifier": ""}]}
                    (root / d / f"{pid}.json").write_text(json.dumps(x))
            papers, _, items, other, kinds = TA.per_paper_items(root / "ext", root / "ref", root, derange=False)
            res = TA.field_stats(papers, items)
            self.assertEqual(res["throughput_per_platform"]["items"], 3)
            self.assertAlmostEqual(res["throughput_per_platform"]["agreement"], 2 / 3)
            self.assertEqual(kinds, [3, 3])
            _, pair, items_nc, _, _ = TA.per_paper_items(root / "ext", root / "ref", root, derange=True)
            self.assertTrue(all(k != v for k, v in pair.items()))
            self.assertTrue(math.isfinite(TA.field_stats(papers, items_nc)["step_duration_per_step"]["items"]))


if __name__ == "__main__":
    unittest.main()
