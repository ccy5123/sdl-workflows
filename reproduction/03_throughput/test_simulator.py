"""Hand-computed synthetic tests of the throughput simulator (synthetic examples computed by hand; no DB paper is
read).

Run from this folder: python -m unittest test_simulator.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulator import Calendar, Platform, Step, Transfer, simulate  # noqa: E402

D = 1440.0


def S(sid, mods, minutes, n=None, human=False, own=True):
    return Step(sid, tuple(mods), human, minutes, n, own)


class SimulatorTests(unittest.TestCase):
    def test_serial_step(self):
        # one 60-min step, b = 1: one batch an hour, 24 experiments a day
        r = simulate(Platform([S("S1", "A", 60)]))
        self.assertAlmostEqual(r.throughput, 24.0)
        self.assertEqual(r.window_days, 28)
        self.assertAlmostEqual(r.utilisation["A"], 1.0)

    def test_jobs_and_units(self):
        # b = 4, n = 2 -> 2 jobs of 60 min; one unit: 120 min a batch -> 4 * 12 = 48 a day; two units: 96 a day
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 60, n=2)], batch_size=4)).throughput, 48.0)
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 60, n=2)], batch_size=4, units={"A": 2})).throughput, 96.0)
        # n missing: the whole batch is one job of 60 min -> 4 * 24 = 96 a day
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 60)], batch_size=4)).throughput, 96.0)

    def test_parallel_streams_share_a_module(self):
        # two streams, one unit: still one batch an hour; two units: two an hour
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 60)], parallel_units=2)).throughput, 24.0)
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 60)], parallel_units=2, units={"A": 2})).throughput, 48.0)

    def test_planning_before_first_step(self):
        # 30 min planning + 30 min step: one batch an hour
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 30)], planning=30)).throughput, 24.0)

    def test_plan_step_at_end(self):
        # plan step S2 (20 min) at the end, S1 40 min: one batch an hour
        p = Platform([S("S1", "A", 40), S("S2", "C", 0)], planning=20, plan_index=1)
        self.assertAlmostEqual(simulate(p).throughput, 24.0)

    def test_human_step_operating_hours(self):
        # 4 h human step, Mon-Fri 09-17: 2 batches a working day, 10 a week -> 10/7 a day
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 240, human=True)])).throughput, 10 / 7)
        # 5 h: 40 h a week / 5 h = 8 batches a week, the pause runs over the night
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 300, human=True)])).throughput, 8 / 7)
        # stated human hours 12 h, 7 d: 84 h a week / 4 h = 21 a week = 3 a day
        p = Platform([S("S1", "A", 240, human=True)], human_cal=Calendar(12, 7))
        self.assertAlmostEqual(simulate(p).throughput, 3.0)

    def test_shared_transfer_agent(self):
        # two streams; S1 30 min and S2 30 min on modules with 2 units; 90-min arm transfer before S2.
        # Two arms: each stream 150 min a batch, completions at 540 + 150 j; window [540 + 10080, 540 + 50400) holds
        # j = 68..335, 268 per stream -> 536 / 28 a day. One arm: 90 min per batch on the arm -> 16 a day.
        steps = [S("S1", "A", 30), S("S2", "B", 30)]
        kw = dict(parallel_units=2, units={"A": 2, "B": 2}, transfers=[Transfer(1, "robot_arm_gantry", 90)])
        self.assertAlmostEqual(simulate(Platform(steps, agents={"robot_arm_gantry": 2}, **kw)).throughput, 536 / 28)
        self.assertAlmostEqual(simulate(Platform(steps, **kw)).throughput, 16.0)

    def test_data_transfer_and_tubing(self):
        # data transfer adds nothing; a 30-min tubing delay makes 30 + 30 = 60 min a batch
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 60)], transfers=[Transfer(0, "data_transfer", 99)])).throughput, 24.0)
        r = simulate(Platform([S("S1", "A", 30)], transfers=[Transfer(0, "fixed_tubing", 30)]))
        self.assertAlmostEqual(r.throughput, 24.0)

    def test_covered_step_is_skipped(self):
        self.assertAlmostEqual(simulate(Platform([S("S1", "A", 60), S("S2", "B", 0)])).throughput, 24.0)

    def test_window_extension_and_flag(self):
        # 7-day step: warm-up ends at Monday 09:00 of week 2, which is also the window start; 4 batches in 28 days,
        # extended by one week to 5 batches in 35 days
        r = simulate(Platform([S("S1", "A", 7 * D)]))
        self.assertEqual((r.window_days, r.batches_in_window, r.flagged), (35, 5, False))
        self.assertAlmostEqual(r.throughput, 5 / 35)
        # 20-day step: window from week 6; batches end at days 60, 80, 100, 120 inside 84 days -> 4, flagged
        r = simulate(Platform([S("S1", "A", 20 * D)]))
        self.assertEqual((r.window_days, r.batches_in_window, r.flagged), (84, 4, True))
        self.assertAlmostEqual(r.throughput, 4 / 84)

    def test_own_share(self):
        r = simulate(Platform([S("S1", "A", 30), S("S2", "B", 30, own=False)]))
        self.assertAlmostEqual(r.own_share, 0.5)


if __name__ == "__main__":
    unittest.main()
