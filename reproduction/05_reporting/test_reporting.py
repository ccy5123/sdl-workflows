"""Synthetic tests of reporting.py (no real data). Run: python3 test_reporting.py   (from this folder)"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reporting as r  # noqa: E402


def paper(pid="X2020", steps=(), conns=(), sp=(), pi=(), hi="not_reported", url=()):
    plats = {s[0] for s in steps} | {c[0] for c in conns} | {f"{pid}/P1"}
    return {"platforms": plats,
            "steps": [{"platform": pl, "step": st, "order": int(st.rsplit("S", 1)[1]), "uo": uo, "by": by}
                      for pl, st, uo, by in steps],
            "conns": [{"platform": pl, "edge": e, "mode": m} for pl, e, m in conns],
            "sp": [{"step": s, "q": q, "qual": qual} for s, q, qual in sp],
            "pi": [{"kind": k, "target": t, "q": q, "qual": qual} for k, t, q, qual in pi],
            "human": {"human_intervention": hi, "unassisted_run_length": list(url)}}


P = "X2020/P1"


class Indicators(unittest.TestCase):
    def test_joint_duration_covers_later_steps(self):
        p = paper(steps=[(P, f"{P}/S1", "react", "robot"), (P, f"{P}/S2", "measure", "robot"),
                         (P, f"{P}/S3", "plan_next_experiment", "software")],
                  sp=[(f"{P}/S1", "duration", f"covers {P}/S1, {P}/S2")])
        self.assertEqual(r.indicators(p)["durations_every_step"], 1)

    def test_missing_duration_breaks_completeness(self):
        p = paper(steps=[(P, f"{P}/S1", "react", "robot"), (P, f"{P}/S2", "measure", "human")],
                  sp=[(f"{P}/S1", "duration", "")])
        ind = r.indicators(p)
        self.assertEqual(ind["durations_every_step"], 0)
        self.assertEqual(ind["at_least_one_step_duration"], 1)

    def test_only_software_steps_not_eligible(self):
        p = paper(steps=[(P, f"{P}/S1", "plan_next_experiment", "software")])
        self.assertIsNone(r.indicators(p)["durations_every_step"])

    def test_durations_use_first_platform_only(self):
        p = paper(steps=[(P, f"{P}/S1", "react", "robot"), ("X2020/P2", "X2020/P2/S1", "react", "robot")],
                  sp=[("X2020/P2/S1", "duration", "")])
        self.assertEqual(r.indicators(p)["durations_every_step"], 0)

    def test_planning_time_on_plan_step(self):
        p = paper(steps=[(P, f"{P}/S1", "plan_next_experiment", "software")], sp=[(f"{P}/S1", "duration", "")])
        self.assertEqual(r.indicators(p)["planning_time"], 1)

    def test_bounded_nominal_throughput(self):
        p = paper(pi=[("platform", "X2020/P2", "throughput", "nominal; upper bound")])
        ind = r.indicators(p)
        self.assertEqual((ind["any_throughput"], ind["measured_throughput"], ind["nominal_throughput_only"]), (1, 0, 1))

    def test_measured_throughput(self):
        p = paper(pi=[("platform", P, "throughput", "measured; N=10; T=2 d")])
        self.assertEqual(r.indicators(p)["measured_throughput"], 1)

    def test_transfer_time_eligibility(self):
        self.assertIsNone(r.indicators(paper(conns=[(P, f"{P}/E1", "data_transfer")]))["transfer_time"])
        p = paper(conns=[(P, f"{P}/E1", "robot_arm_gantry"), (P, f"{P}/E2", "data_transfer")],
                  pi=[("connection", f"{P}/E2", "transfer_time", "")])
        self.assertEqual(r.indicators(p)["transfer_time"], 0)
        p["pi"].append({"kind": "connection", "target": f"{P}/E1", "q": "transfer_time", "qual": ""})
        self.assertEqual(r.indicators(p)["transfer_time"], 1)

    def test_human_items(self):
        for hi, want in (("quantified", 1), ("none_stated", 1), ("described", 0), ("not_reported", 0)):
            self.assertEqual(r.indicators(paper(hi=hi))["human_intervention_number_or_none"], want)
        self.assertEqual(r.indicators(paper(url=[{"value": 2, "unit": "d"}]))["longest_unattended_run"], 1)

    def test_more_than_one_is_descriptive_only(self):
        ind = r.indicators(paper(pi=[("platform", P, "parallel_units", "")]))
        self.assertEqual(ind["parallel_streams_gt1"], 1)
        self.assertNotIn("parallel_streams_gt1", r.ITEMS)
        self.assertEqual(ind["items_reported"], 0)


def synth(n, prob, seed=0):
    rng = random.Random(seed)
    return {f"p{i:03d}": {k: int(rng.random() < prob) for k in r.ITEMS} for i in range(n)}


class Statistics(unittest.TestCase):
    def test_ineligible_excluded_from_share(self):
        ind = synth(50, 1.0)
        for p in list(ind)[:25]:
            ind[p]["transfer_time"] = None
        res = r.shares(ind, sorted(ind), b=50)["transfer_time"]
        self.assertEqual((res["n_eligible"], res["share"], res["ci95_lo"], res["ci95_hi"]), (25, 1.0, 1.0, 1.0))

    def test_bootstrap_follows_seed(self):
        ind = synth(20, 0.5)
        papers = sorted(ind)
        rng = random.Random(1)
        reps = []
        for _ in range(30):
            seq = [rng.choice(papers) for _ in papers]
            reps.append(sum(ind[p]["cost"] for p in seq) / len(seq))
        self.assertEqual((r.shares(ind, papers, b=30)["cost"]["ci95_lo"],), (r.ci(reps)[0],))

    def test_period_difference_and_strata(self):
        # early 4 papers, 1 reporting (0.25); late 2 papers, both reporting (1.0) -> difference 0.75; late resamples
        # are always 1.0, so every replicate difference is 1.0 minus an early share in {0, 0.25, 0.5, 0.75, 1}.
        papers = ["e1", "e2", "e3", "e4", "l1", "l2"]
        era = {"e1": "train", "e2": "train", "e3": "train", "e4": "train", "l1": "test", "l2": "test"}
        ind = {p: {k: int(p in ("e1", "l1", "l2")) for k in r.ITEMS} for p in papers}
        res = r.by_period(ind, era, papers, b=200)
        row = res["items"]["cost"]
        self.assertEqual((row["share_early"], row["share_late"], row["diff"]), (0.25, 1.0, 0.75))
        self.assertEqual((res["n_early"], res["n_late"], res["n_no_era"]), (4, 2, 0))
        self.assertTrue(0.0 <= row["ci95_lo"] <= row["ci95_hi"] <= 1.0)

    def test_permutation_p_with_separated_fields(self):
        # field a never reports, field b always: observed chi2 = n = 40 (complete separation); a random permutation
        # reaches it only by restoring the separation (chance 1 / C(40, 20)), so ge = 0 and p = 1 / (1 + 100).
        papers = [f"p{i:03d}" for i in range(40)]
        field = {p: ("a" if i < 20 else "b") for i, p in enumerate(papers)}
        ind = {p: {k: int(field[p] == "b") for k in r.ITEMS} for p in papers}
        row = r.by_field(ind, field, papers, perms=100)["items"]["cost"]
        self.assertAlmostEqual(row["chi2"], 40.0)
        self.assertEqual((row["fields"], row["n_tested"]), (["a", "b"], 40))
        self.assertAlmostEqual(row["p"], 1 / 101)

    def test_small_field_left_out(self):
        papers = [f"p{i:03d}" for i in range(60)]
        field = {p: ("big" if i < 55 else "small") for i, p in enumerate(papers)}
        ind = {p: {k: int(field[p] == "small") for k in r.ITEMS} for p in papers}
        row = r.by_field(ind, field, papers, perms=50)["items"]["batch_size"]
        self.assertEqual((row["fields"], row["p"], row["p_holm"]), (["big"], None, None))

    def test_quantile_and_holm(self):
        self.assertEqual(r.quantile([0, 1, 2, 3, 4], 0.5), 2)
        self.assertAlmostEqual(r.quantile([0, 10], 0.25), 2.5)
        adj = r.holm({"a": 0.01, "b": 0.04, "c": None})
        self.assertAlmostEqual(adj["a"], 0.02)
        self.assertAlmostEqual(adj["b"], 0.04)
        self.assertIsNone(adj["c"])

    def test_weighted_share(self):
        ind = {"p1": {k: 1 for k in r.ITEMS}, "p2": {k: 0 for k in r.ITEMS}, "p3": {k: 0 for k in r.ITEMS}}
        W = {"p1": 1.0, "p2": 0.5, "p3": 0.5}   # p2 and p3 share a platform group
        res = r.weighted_shares(ind, W, ["p1", "p2", "p3"])["cost"]
        self.assertEqual((res["weighted_share"], res["weighted_n"]), (0.5, 2.0))


if __name__ == "__main__":
    unittest.main()
