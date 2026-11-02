"""Synthetic tests of model.py and evaluate.py: tie rules, the connection attachment rule, the bootstrap (replicates with
zero items dropped), the shuffled-label control and macro-F1. Every expected value is worked out by hand in the comment
next to it.
Run: python3 -m unittest test_evaluate -v   (from this folder)
The last test reads the database build when the environment variable SDL_DB gives its path, and is skipped otherwise.
"""
import os
import random
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate as ev  # noqa: E402
from model import Model, load_items  # noqa: E402

A, B = "module_type", "transfer_mode"


def it(l1, l2, l3, l4, y, paper="P", item="i"):
    return {"ctx": [l1, l2, l3, l4], "y": y, "paper": paper, "platform": paper + "/P1", "item": item}


class ModelTies(unittest.TestCase):
    def setUp(self):
        # i1, i2 share L1; i3 shares only L2 (and L4) with them; i4 is elsewhere.
        self.train = [it(("u", "S", "E", "t1"), ("u", "S", "E"), ("u", "t1"), ("u",), "X", item="1"),
                      it(("u", "S", "E", "t1"), ("u", "S", "E"), ("u", "t1"), ("u",), "Y", item="2"),
                      it(("u", "S", "E", "t2"), ("u", "S", "E"), ("u", "t2"), ("u",), "Y", item="3"),
                      it(("v", "S", "E", "t1"), ("v", "S", "E"), ("v", "t1"), ("v",), "Z", item="4")]
        self.q = it(("u", "S", "E", "t1"), ("u", "S", "E"), ("u", "t1"), ("u",), "?")

    def test_tie_broken_by_next_coarser_level(self):
        # L1 count 2 >= m = 1: X 1, Y 1 tie; L2 has X 1, Y 2 -> Y. Top-3: L1 ranking [Y, X], filled from L5 -> Z.
        self.assertEqual(Model(self.train, 1).predict(self.q), ("Y", ["Y", "X", "Z"], 1))

    def test_alphabetical_when_coarser_level_also_ties(self):
        train = self.train[:2]  # L1 and L2 both X 1, Y 1 -> alphabetical X
        self.assertEqual(Model(train, 1).predict(self.q)[0], "X")

    def test_min_count_moves_to_coarser_level(self):
        # m = 3: L1 has 2 items (< 3), L2 has 3 -> level 2, X 1 Y 2 -> Y.
        top1, _, level = Model(self.train, 3).predict(self.q)
        self.assertEqual((top1, level), ("Y", 2))

    def test_unseen_context_uses_all_items(self):
        q = it(("w", "S", "E", "t9"), ("w", "S", "E"), ("w", "t9"), ("w",), "?")
        # nothing matches L1-L4 -> L5: X 1, Y 2, Z 1 -> Y; level 5.
        self.assertEqual(Model(self.train, 1).predict(q), ("Y", ["Y", "X", "Z"], 5))
        # baseline: unseen unit operation -> overall most frequent Y, top-3 Y, X, Z (ties alphabetical)
        self.assertEqual(Model(self.train, 1).baseline(q), ("Y", ["Y", "X", "Z"]))

    def test_baseline_tie_alphabetical(self):
        # L4 ('u',) over the first two items: X 1, Y 1 -> X
        self.assertEqual(Model(self.train[:2], 1).baseline(self.q)[0], "X")


def synthetic_db(steps, conns):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE v_era (paper_id, first_public_year, era)")
    db.execute("CREATE TABLE v_step (paper_id, coding_id, platform_id, step_id, step_order, unit_operation, family, "
               "performed_by, primary_module_id, primary_module_type, first_field_tag, uncertain, era)")
    db.execute("CREATE TABLE v_connection (paper_id, platform_id, edge_id, from_module, to_module, transfer_mode, "
               "is_material, uncertain, era)")
    db.execute("INSERT INTO v_era VALUES ('P', 2020, 'train')")
    for plat, sid, order, uo, mod in steps:
        db.execute("INSERT INTO v_step VALUES ('P', 'c', ?, ?, ?, ?, ?, 'robot', ?, ?, 'chem', 0, 'train')",
                   (plat, sid, order, uo, "f" + uo, mod, None if mod is None else "type_" + mod))
    for plat, e, a, b, mode, mat in conns:
        db.execute("INSERT INTO v_connection VALUES ('P', ?, ?, ?, ?, ?, ?, 0, 'train')", (plat, e, a, b, mode, mat))
    return db


class Attachment(unittest.TestCase):
    def test_attachment_rule(self):
        steps = [("P1", "s1", 1, "u1", "A"), ("P1", "s2", 2, "u2", "C"), ("P1", "s3", 3, "u3", "B"), ("P1", "s4", 4, "u4", "A"),
                 ("P1", "s5", 5, "u5", "B"), ("P1", "s6", 6, "u6", None),
                 ("P2", "t1", 1, "u1", "A"), ("P2", "t2", 2, "u2", "D"), ("P2", "t3", 3, "u3", "B")]
        conns = [("P1", "E1", "A", "B", "tube", 1),   # consecutive pair (s4, s5); (s1, s3) is not consecutive
                 ("P1", "E2", "C", "A", "arm", 1),    # first A step s1 has no C before it -> unattached
                 ("P2", "E3", "A", "B", "arm", 1),    # no consecutive A->B; last A (t1) before first B (t3)
                 ("P2", "E4", "A", "D", "data", 0)]   # not material -> not read
        items, left_out = load_items(synthetic_db(steps, conns), era_only="train")
        self.assertEqual(dict(left_out), {"module_type_no_module": 1, "transfer_mode_unattached": 1})   # s6, E2
        b = {x["item"]: x["ctx"][1] for x in items[B]}
        self.assertEqual(b, {"E1": ("u4", "u5"), "E3": ("u1", "u3")})
        a = {x["item"]: x["ctx"][0] for x in items[A]}
        self.assertEqual(a["s5"], ("u5", "u4", "u6", "chem"))   # the module-less step s6 is still the next step
        self.assertEqual(a["s1"], ("u1", "START", "u2", "chem"))
        self.assertNotIn("s6", a)

    def test_several_a_before_first_b_takes_the_last(self):
        db = synthetic_db([("P1", "s1", 1, "u1", "A"), ("P1", "s2", 2, "u2", "A"), ("P1", "s3", 3, "u3", "C"),
                           ("P1", "s4", 4, "u4", "B")], [("P1", "E", "A", "B", "tube", 1)])
        # no consecutive A->B; first B is s4; A steps before it: s1, s2 -> the last, s2
        self.assertEqual(load_items(db, era_only="train")[0][B][0]["ctx"][1], ("u2", "u4"))

    def test_several_consecutive_pairs_takes_the_first(self):
        db = synthetic_db([("P1", "s1", 1, "u1", "A"), ("P1", "s2", 2, "u2", "B"), ("P1", "s3", 3, "u3", "A"),
                           ("P1", "s4", 4, "u4", "B")], [("P1", "E", "A", "B", "tube", 1)])
        self.assertEqual(load_items(db, era_only="train")[0][B][0]["ctx"][1], ("u1", "u2"))


class Bootstrap(unittest.TestCase):
    rows = [{"field": A, "paper": "P1", "y": "X", "model": "X", "base": "X"},
            {"field": A, "paper": "P1", "y": "X", "model": "X", "base": "Y"},
            {"field": A, "paper": "P2", "y": "X", "model": "Y", "base": "X"},
            {"field": B, "paper": "P3", "y": "T", "model": "T", "base": "U"}]

    def test_hand_replicates(self):
        sets = [["P1", "P1", "P1"], ["P2", "P2", "P3"], ["P1", "P2", "P3"]]
        # module type: set1 n 6, model 6, base 3 -> +0.5; set2 n 2, model 0, base 2 -> -1; set3 n 3, model 2, base 2 -> 0.
        # transfer mode: set1 has no P3 -> dropped; set2, set3: n 1, model 1, base 0 -> +1, +1.
        res = ev.boot(self.rows, sets)
        self.assertEqual(res[A]["replicates"], 3)
        self.assertEqual(res[B]["replicates"], 2)
        # n = 3: positions int(0.075) = 0 and int(2.925) - 1 = 1 of [-1, 0, 0.5]
        self.assertEqual(res[A]["diff_ci95"], (-1.0, 0.0))
        self.assertEqual(res[B]["diff_ci95"], (1.0, 1.0))

    def test_percentile_positions(self):
        # 2000 values 1..2000: positions 50 and 1949 -> 51 and 1950 (50 values below and 50 above)
        self.assertEqual(ev.pct(list(range(1, 2001))), (51, 1950))

    def test_boot_sets_follow_seed_one(self):
        rng = random.Random(1)
        expect = [[rng.choice(["P1", "P2", "P3"]) for _ in range(3)] for _ in range(5)]
        self.assertEqual(ev.boot_sets(["P1", "P2", "P3"], seed=1, b=5), expect)

    def test_dropped_replicates_match_sets_without_items(self):
        sets = ev.boot_sets(["P1", "P2", "P3"], seed=1, b=200)
        res = ev.boot(self.rows, sets)
        self.assertEqual(res[B]["replicates"], sum("P3" in s for s in sets))
        self.assertEqual(res[A]["replicates"], sum(("P1" in s) or ("P2" in s) for s in sets))

    def test_label_without_items_has_no_interval(self):
        res = ev.boot([r for r in self.rows if r["field"] == A], [["P1", "P2", "P3"]])
        self.assertEqual((res[B]["replicates"], res[B]["diff_ci95"]), (0, (None, None)))


class Measures(unittest.TestCase):
    def test_macro_f1(self):
        rows = [{"paper": "P1", "y": "X", "model": "X"}, {"paper": "P1", "y": "X", "model": "Y"},
                {"paper": "P2", "y": "Y", "model": "Y"}, {"paper": "P2", "y": "Z", "model": "Y"}]
        # X: tp 1 fp 0 fn 1 -> 2/3; Y: tp 1 fp 2 fn 0 -> 2/4; Z: tp 0 fp 0 fn 1 -> 0; mean 7/18
        self.assertAlmostEqual(ev.macro_f1(rows, "model"), 7 / 18)

    def test_shuffled_labels(self):
        train = {A: [{"y": y, "n": i} for i, y in enumerate("XXYZ")], B: [{"y": y, "n": i} for i, y in enumerate("TU")]}
        out = ev.shuffled_labels(train)
        rng = random.Random(20261024)
        la, lb = list("XXYZ"), list("TU")
        rng.shuffle(la)
        rng.shuffle(lb)   # module types first, then transfer modes, one generator
        self.assertEqual([x["y"] for x in out[A]], la)
        self.assertEqual([x["y"] for x in out[B]], lb)
        self.assertEqual([x["n"] for x in out[A]], [0, 1, 2, 3])   # inputs stay in place


class MoreModelCases(unittest.TestCase):
    def test_l4_tie_model_uses_l5_baseline_alphabetical(self):
        train = [it(("u", "a", "b", "t"), ("u", "a", "b"), ("u", "t"), ("u",), "Y", item="1"),
                 it(("u", "c", "d", "t"), ("u", "c", "d"), ("u", "t2"), ("u",), "X", item="2"),
                 it(("v", "a", "b", "t"), ("v", "a", "b"), ("v", "t"), ("v",), "Y", item="3")]
        q = it(("u", "e", "f", "t9"), ("u", "e", "f"), ("u", "t9"), ("u",), "?")
        # model: L1-L3 unseen, L4 ('u',) X 1, Y 1 tie -> L5 X 1, Y 2 -> Y; baseline: L4 tie -> alphabetical X
        self.assertEqual(Model(train, 1).predict(q)[0::2], ("Y", 4))
        self.assertEqual(Model(train, 1).baseline(q)[0], "X")

    def test_l4_below_m_goes_to_l5(self):
        train = [it(("u", "a", "b", "t"), ("u", "a", "b"), ("u", "t"), ("u",), "X", item="1"),
                 it(("v", "a", "b", "t"), ("v", "a", "b"), ("v", "t"), ("v",), "Y", item="2"),
                 it(("w", "a", "b", "t"), ("w", "a", "b"), ("w", "t"), ("w",), "Y", item="3")]
        q = it(("u", "a", "b", "t"), ("u", "a", "b"), ("u", "t"), ("u",), "?")
        # m = 2: every level of q has 1 item -> L5: X 1, Y 2 -> Y; the baseline ignores m -> X
        self.assertEqual(Model(train, 2).predict(q)[0::2], ("Y", 5))
        self.assertEqual(Model(train, 2).baseline(q)[0], "X")

    def test_top3_fill_with_ties_at_coarser_level(self):
        train = [it(("u", "a", "b", "t"), ("u", "a", "b"), ("u", "t"), ("u",), "X", item="1"),
                 it(("u", "c", "d", "t"), ("u", "c", "d"), ("u", "t"), ("u",), "Z", item="2"),
                 it(("u", "c", "d", "t"), ("u", "c", "d"), ("u", "t"), ("u",), "W", item="3"),
                 it(("v", "c", "d", "t"), ("v", "c", "d"), ("v", "t"), ("v",), "W", item="4")]
        q = it(("u", "a", "b", "t"), ("u", "a", "b"), ("u", "t"), ("u",), "?")
        # L1 [X]; L2 ('u','a','b') adds nothing; L3 ('u','t'): X 1, Z 1, W 1 tie, broken by L4 ('u',) (also 1 each)
        # -> alphabetical W, Z -> top-3 [X, W, Z]
        self.assertEqual(Model(train, 1).predict(q)[1], ["X", "W", "Z"])


@unittest.skipUnless(os.environ.get("SDL_DB"), "set SDL_DB to the database build to run this test")
class ShadowViews(unittest.TestCase):
    def test_temp_views_match_db_views(self):
        db = ev.open_db(os.environ["SDL_DB"])
        items, _ = load_items(db, era_only="train")
        sh = ev.shadow(os.environ["SDL_DB"], "extractor_a")
        self.assertEqual(ev.items_key_set(load_items(sh, era_only="train")[0]), ev.items_key_set(items))


if __name__ == "__main__":
    unittest.main()
