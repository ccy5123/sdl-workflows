"""Synthetic tests of human_involvement.py. Every database here is an in-memory SQLite database built from the schema
of the build (protocol/db-schema.sql) and filled by hand; the expected values are worked out by hand in the comments.
The real build is opened only by SchemaMatchesBuild, which reads sqlite_master (the schema), never a data row.
Run in this folder: python3 -m unittest test_human_involvement -v
Paths (defaults inside the project workspace, two levels up) can be changed with the environment variables
SDL_SCHEMA, SDL_TAXONOMY and SDL_DB.
"""
import csv
import hashlib
import json
import os
import random
import sqlite3
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parents[1]
sys.path.insert(0, str(HERE))
import human_involvement as hi  # noqa: E402

SCHEMA = Path(os.environ.get("SDL_SCHEMA", WS / "protocol" / "db-schema.sql"))
TAXONOMY = Path(os.environ.get("SDL_TAXONOMY", WS / "protocol" / "taxonomy-v1.json"))
REAL_DB = Path(os.environ.get("SDL_DB", WS / "db" / "sdl-db.sqlite"))
TAX = hi.P.configure(TAXONOMY)


class Synth:
    """Minimal hand-filled build: database-record codings (extractor_a, prompt-v1) unless role is given."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA.read_text(encoding="utf-8"))
        self.db.execute("PRAGMA foreign_keys = OFF")
        for fam, cs in TAX["unit_operation"].items():
            self.db.execute("INSERT INTO uo_family VALUES (?)", (fam,))
            for c in cs:
                self.db.execute("INSERT INTO unit_operation VALUES (?, ?)", (c, fam))
        self.db.execute("INSERT INTO uo_family VALUES ('unmapped')")
        self.db.execute("INSERT INTO unit_operation VALUES ('unmapped', 'unmapped')")
        for t in TAX["transfer_mode"] + ["unmapped"]:
            self.db.execute("INSERT INTO transfer_mode VALUES (?, ?)", (t, 0 if t == "data_transfer" else 1))
        self.n = {}

    def paper(self, pid, tags=("catalysis",), year=2022, gold=None, role="extractor_a", label="opus", model="m",
              add_paper=True):
        cid = f"{pid}|{role}|x"
        if add_paper:
            self.db.execute("INSERT INTO paper VALUES (?, NULL, NULL, NULL, ?, 'candidate_year')", (pid, year))
        if gold and add_paper:
            self.db.execute("INSERT INTO gold_membership VALUES (?, ?, 0, 0)", (pid, gold))
        self.db.execute("INSERT INTO coding (coding_id, paper_id, role, coder_label, model_id, prompt_path, prompt_sha256,"
                        " taxonomy_version, source_path) VALUES (?, ?, ?, ?, ?, 'extraction/prompt-v1.md', 'x', 'v1', ?)",
                        (cid, pid, role, label, model, f"codings/{pid}_{role}.json"))
        for i, t in enumerate(tags, 1):
            self.db.execute("INSERT INTO coding_field_tag VALUES (?, ?, ?)", (cid, t, i))
        return cid

    def platform(self, cid, plat, identity=None):
        self.db.execute("INSERT INTO platform (coding_id, platform_id, commercial_integrated) VALUES (?, ?, 0)", (cid, plat))
        if cid.split("|")[1] == "extractor_a":
            self.db.execute("INSERT INTO platform_identity_member VALUES (?, ?, ?, 'singleton', 'build-rule', NULL)",
                            (identity or plat, cid, plat))

    def module(self, cid, mid, on=1, mtype="liquid_handler"):
        self.db.execute("INSERT INTO module (coding_id, module_id, platform_id, module_type, on_platform) VALUES (?,?,?,?,?)",
                        (cid, mid, "/".join(mid.split("/")[:2]), mtype, on))

    def step(self, cid, sid, uo, pb="robot", modules=(), uncertain=False):
        k = int(sid.split("S")[-1])
        self.db.execute("INSERT INTO step (coding_id, step_id, platform_id, step_order, unit_operation, performed_by,"
                        " unmapped_note) VALUES (?,?,?,?,?,?,?)",
                        (cid, sid, "/".join(sid.split("/")[:2]), k, uo, pb, "n" if uo == "unmapped" else None))
        for j, m in enumerate(modules, 1):
            self.db.execute("INSERT INTO step_module VALUES (?, ?, ?, ?)", (cid, sid, m, j))
        if uncertain:
            self.db.execute("INSERT INTO item_flag VALUES (?, ?, 'step', 'uncertain', 'b', 'r')", (cid, sid))

    def conn(self, cid, eid, f, t, tm, uncertain=False):
        self.db.execute("INSERT INTO connection (coding_id, edge_id, platform_id, from_module, to_module, transfer_mode,"
                        " stated) VALUES (?,?,?,?,?,?,1)", (cid, eid, "/".join(eid.split("/")[:2]), f, t, tm))
        if uncertain:
            self.db.execute("INSERT INTO item_flag VALUES (?, ?, 'connection', 'uncertain', 'b', 'r')", (cid, eid))

    def simple(self, pid, uo_hd, tags=("catalysis",), identity=None, year=2022, gold=None):
        """Paper with one platform; uo_hd: list of (unit operation, depends on people via performed_by)."""
        c = self.paper(pid, tags, year, gold)
        self.platform(c, f"{pid}/P1", identity)
        self.module(c, f"{pid}/P1/M1")
        for i, (u, h) in enumerate(uo_hd, 1):
            self.step(c, f"{pid}/P1/S{i}", u, "human" if h else "robot", [f"{pid}/P1/M1"])
        return c


def comps_by_step(d):
    return {s["step_id"]: c for s, c in zip(d["steps"], hi.components(d["steps"], d["conns"]))}


class Indicator(unittest.TestCase):
    def setUp(self):
        s = Synth()
        c = s.paper("P")
        s.platform(c, "P/P1")
        for m, on in (("M1", 1), ("M2", 0), ("M3", 1), ("M4", 1), ("M5", 1), ("M6", 1), ("M7", 1), ("M8", 1)):
            s.module(c, f"P/P1/{m}", on)
        s.step(c, "P/P1/S1", "dispense_liquid", "human", ["P/P1/M1"])        # (a) only
        s.step(c, "P/P1/S2", "anneal", "robot", ["P/P1/M2"])                 # (b) only: primary M2 off-platform
        s.step(c, "P/P1/S3", "mix", "robot", ["P/P1/M3"])                    # (c) only: M3 -> M4 human_transfer
        s.step(c, "P/P1/S4", "filter", "robot", ["P/P1/M5"])                 # none: robot_arm_gantry only
        s.step(c, "P/P1/S5", "analyze_data", "software", [])                 # no primary module: not (b), on_platform NULL
        s.step(c, "P/P1/S6", "measure_optical", "robot", ["P/P1/M7", "P/P1/M8"])  # (c) via non-primary M8
        s.conn(c, "P/P1/E1", "P/P1/M3", "P/P1/M4", "human_transfer")
        s.conn(c, "P/P1/E2", "P/P1/M5", "P/P1/M6", "robot_arm_gantry")
        s.conn(c, "P/P1/E3", "P/P1/M6", "P/P1/M8", "human_transfer")
        self.db = s.db
        self.d = hi.load(s.db)

    def test_each_condition_alone(self):
        c = comps_by_step(self.d)
        self.assertEqual(c["P/P1/S1"], (True, False, False))
        self.assertEqual(c["P/P1/S2"], (False, True, False))
        self.assertEqual(c["P/P1/S3"], (False, False, True))
        self.assertEqual(c["P/P1/S4"], (False, False, False))

    def test_step_without_primary_module(self):
        s5 = [s for s in self.d["steps"] if s["step_id"] == "P/P1/S5"][0]
        self.assertIsNone(s5["on_platform"])
        self.assertEqual(comps_by_step(self.d)["P/P1/S5"], (False, False, False))

    def test_human_transfer_on_non_primary_module(self):
        # v_step carries only the primary module M7 (on-platform, no human transfer); M8 is in step_module only.
        s6 = [s for s in self.d["steps"] if s["step_id"] == "P/P1/S6"][0]
        self.assertEqual(s6["primary_module_id"], "P/P1/M7")
        self.assertEqual(comps_by_step(self.d)["P/P1/S6"], (False, False, True))

    def test_composite_and_paper_cells(self):
        ind = hi.composite(hi.components(self.d["steps"], self.d["conns"]))
        cl = hi.step_cells(self.d["steps"], ind)
        self.assertEqual(cl["P"], {"dispense_liquid": True, "anneal": True, "mix": True, "filter": False,
                                   "analyze_data": False, "measure_optical": True})

    def test_base_table_coding_steps_equal_view(self):
        # The paired comparison computes each coding from the base tables; on the database-record coding it must equal
        # the v_step-based indicator.
        got = hi.coding_steps(self.db, "P|extractor_a|x")
        ind = hi.composite(hi.components(self.d["steps"], self.d["conns"]))
        want = {s["step_id"]: (s["performed_by"], s["on_platform"], h, s["primary_module_id"])
                for s, h in zip(self.d["steps"], ind)}
        self.assertEqual(got, want)


class PaperCells(unittest.TestCase):
    def test_any_step_depending_on_people_makes_the_paper_depend(self):
        cl = hi.cells([("P", "mix", False), ("P", "mix", True), ("P", "filter", False), ("Q", "mix", False)])
        self.assertEqual(dict(cl), {"P": {"mix": True, "filter": False}, "Q": {"mix": False}})

    def test_steps_of_all_platforms_count(self):
        s = Synth()
        c = s.paper("P")
        s.platform(c, "P/P1")
        s.platform(c, "P/P2")
        s.module(c, "P/P1/M1")
        s.module(c, "P/P2/M1")
        s.step(c, "P/P1/S1", "mix", "robot", ["P/P1/M1"])
        s.step(c, "P/P2/S1", "mix", "human", ["P/P2/M1"])
        d = hi.load(s.db)
        cl = hi.step_cells(d["steps"], hi.composite(hi.components(d["steps"], d["conns"])))
        self.assertEqual(cl["P"], {"mix": True})


class Weights(unittest.TestCase):
    def test_component_weights(self):
        # A, B, C share identity I1 (one component of 3), D alone: w = 1/3, 1/3, 1/3, 1.
        s = Synth()
        for p in "ABC":
            s.simple(p, [("mix", False)], identity="I1")
        s.simple("D", [("mix", False)])
        d = hi.load(s.db)
        w = {p: Fraction(d["W"][p], d["L"]) for p in d["papers"]}
        self.assertEqual(w, {"A": Fraction(1, 3), "B": Fraction(1, 3), "C": Fraction(1, 3), "D": Fraction(1)})
        self.assertEqual(d["components"], [["A", "B", "C"], ["D"]])

    def test_chained_link_through_a_second_platform(self):
        # A-B share I1; B's second platform shares I2 with C: one component {A, B, C}; L = lcm(3, 1) = 3.
        s = Synth()
        s.simple("A", [("mix", False)], identity="I1")
        b = s.simple("B", [("mix", False)], identity="I1")
        s.platform(b, "B/P2", "I2")
        s.simple("C", [("mix", False)], identity="I2")
        s.simple("D", [("mix", False)])
        d = hi.load(s.db)
        self.assertEqual(d["components"], [["A", "B", "C"], ["D"]])
        self.assertEqual((d["W"], d["L"]), ({"A": 1, "B": 1, "C": 1, "D": 3}, 3))

    def test_identity_rows_of_other_codings_ignored(self):
        # A (record platform in I1) and B (record platform in I2) are separate; a platform_identity_member row of B's
        # reference coding in I1 must not link them.
        s = Synth()
        s.simple("A", [("mix", False)], identity="I1")
        s.simple("B", [("mix", False)], identity="I2")
        rc = s.paper("B", role="reference", add_paper=False)
        s.db.execute("INSERT INTO platform (coding_id, platform_id, commercial_integrated) VALUES (?, 'B/P1', 0)", (rc,))
        s.db.execute("INSERT INTO platform_identity_member VALUES ('I1', ?, 'B/P1', 'singleton', 'build-rule', NULL)", (rc,))
        d = hi.load(s.db)
        self.assertEqual((d["components"], d["W"], d["L"]), ([["A"], ["B"]], {"A": 1, "B": 1}, 1))

    def test_weighted_share(self):
        # A, B, C (w 1/3 each) contain mix, only A depends on people; D (w 1) contains mix and depends on people.
        # weighted n = 2, weighted hd = 1/3 + 1 = 4/3, share = 2/3.
        s = Synth()
        s.simple("A", [("mix", True)], identity="I1")
        s.simple("B", [("mix", False)], identity="I1")
        s.simple("C", [("mix", False)], identity="I1")
        s.simple("D", [("mix", True)])
        d = hi.load(s.db)
        cl = hi.step_cells(d["steps"], hi.composite(hi.components(d["steps"], d["conns"])))
        tb = hi.table(cl, d["W"], d["L"], d["papers"], hi.first_field_groups(d))
        n, hd = tb["t"][("mix", hi.ALL)]
        self.assertEqual((Fraction(n, d["L"]), Fraction(hd, d["L"])), (Fraction(2), Fraction(4, 3)))
        row = [r for r in hi.rows_of(tb, "main", "first_field_tag") if r["group"] == hi.ALL][0]
        self.assertAlmostEqual(row["share"], 2 / 3)

    def test_per_field_weighted_n(self):
        # catalysis: 6 singletons containing anneal -> n 6. battery_electrochem: 4 singletons + Y1, Y2 sharing identity
        # J (w 1/2 each) -> n exactly 5.0. nanomaterials: 4 singletons + Z1 (w 1/2, its component partner Z2 is in
        # materials_polymer_soft) -> n 4.5; materials_polymer_soft: n 0.5. Only the first two count as fields.
        s = Synth()
        for i in range(6):
            s.simple(f"C{i}", [("anneal", True)], tags=("catalysis",))
        for i in range(4):
            s.simple(f"Bt{i}", [("anneal", True)], tags=("battery_electrochem",))
            s.simple(f"N{i}", [("anneal", True)], tags=("nanomaterials",))
        s.simple("Y1", [("anneal", True)], tags=("battery_electrochem",), identity="J")
        s.simple("Y2", [("anneal", True)], tags=("battery_electrochem",), identity="J")
        s.simple("Z1", [("anneal", True)], tags=("nanomaterials",), identity="K")
        s.simple("Z2", [("anneal", True)], tags=("materials_polymer_soft",), identity="K")
        d = hi.load(s.db)
        cl = hi.step_cells(d["steps"], hi.composite(hi.components(d["steps"], d["conns"])))
        tb = hi.table(cl, d["W"], d["L"], d["papers"], hi.first_field_groups(d))
        n = {r["group"]: r["weighted_n"] for r in hi.rows_of(tb, "main", "first_field_tag")}
        self.assertEqual((n["catalysis"], n["battery_electrochem"], n["nanomaterials"], n["materials_polymer_soft"]),
                         (6.0, 5.0, 4.5, 0.5))
        self.assertEqual(tb["cnt"]["anneal"], [2, 0])


class FieldCounts(unittest.TestCase):
    def test_boundaries_exact(self):
        L = 6
        t = {("u", "F1"): [30, 15],   # n 5, share exactly 0.5 -> at or above half
             ("u", "F2"): [30, 16],   # n 5, share 0.533 -> at or above half
             ("u", "F3"): [29, 29],   # n 4.83 < 5 -> not counted
             ("u", "F4"): [30, 14],   # n 5, share 0.467 -> below half
             ("u", hi.ALL): [119, 74]}
        self.assertEqual(hi.field_counts(t, L)["u"], [2, 1])
        t[("u", "F3")] = [30, 15]     # now n exactly 5, share exactly 0.5
        self.assertEqual(hi.field_counts(t, L)["u"], [3, 1])

    def test_unmapped_field_and_unmapped_unit_operation_never_count(self):
        L = 1
        t = {("u", "F1"): [5, 5], ("u", "F2"): [5, 5], ("u", "unmapped"): [5, 5], ("u", None): [5, 5],
             ("unmapped", "F1"): [5, 5], ("unmapped", "F2"): [5, 5], ("unmapped", "F3"): [5, 5]}
        cnt = hi.field_counts(t, L)
        self.assertEqual(cnt["u"], [2, 0])
        self.assertNotIn("unmapped", cnt)

    def build(self, f3_hd, f3_papers=5, f3_tag="materials_polymer_soft"):
        """Fields F1, F2: 5 singleton papers containing anneal, 3 depending on people (share 0.6). F3: f3_papers
        singleton papers, f3_hd depending on people. Every paper also has 'unmapped' steps, all depending on people,
        and the second field tag analytical_chemistry (a second tag must not count as a field)."""
        s = Synth()
        k = 0
        for tag, n, h in (("catalysis", 5, 3), ("nanomaterials", 5, 3), (f3_tag, f3_papers, f3_hd)):
            for i in range(n):
                k += 1
                s.simple(f"X{k:03d}", [("anneal", i < h), ("unmapped", True)], tags=(tag, "analytical_chemistry"))
        d = hi.load(s.db)
        cl = hi.step_cells(d["steps"], hi.composite(hi.components(d["steps"], d["conns"])))
        return hi.table(cl, d["W"], d["L"], d["papers"], hi.first_field_groups(d))

    def test_three_fields_at_or_above_half(self):
        self.assertEqual(self.build(3)["cnt"]["anneal"], [3, 0])      # F3 share 0.6 with n 5

    def test_one_field_just_below_half(self):
        self.assertEqual(self.build(2)["cnt"]["anneal"], [2, 1])      # F3 share 0.4

    def test_field_just_below_n(self):
        self.assertEqual(self.build(4, f3_papers=4)["cnt"]["anneal"], [2, 0])   # F3 n 4 (share 1.0) -> not counted

    def test_unmapped_first_field_tag_not_a_field(self):
        tb = self.build(3, f3_tag="unmapped")
        self.assertEqual(tb["cnt"]["anneal"], [2, 0])
        # but those papers enter the overall share: n 15, hd 9
        self.assertEqual(tb["t"][("anneal", hi.ALL)], [15 * tb["L"], 9 * tb["L"]])

    def test_unmapped_unit_operation_in_table_not_counted(self):
        tb = self.build(3)
        self.assertNotIn("unmapped", tb["cnt"])
        self.assertEqual(tb["t"][("unmapped", hi.ALL)], [15, 15])   # reported in the table (L = 1)


class Bootstrap(unittest.TestCase):
    def setUp(self):
        s = Synth()
        s.simple("A", [("mix", True)], identity="I1")
        s.simple("B", [("mix", False)], identity="I1")
        s.simple("C", [("mix", False), ("filter", True)], identity="I1", tags=("nanomaterials",))
        s.simple("D", [("mix", True)])
        self.d = hi.load(s.db)
        self.cl = hi.step_cells(self.d["steps"], hi.composite(hi.components(self.d["steps"], self.d["conns"])))
        self.ff = hi.first_field_groups(self.d)

    def test_same_seed_same_output(self):
        a = hi.bootstrap(self.cl, self.d["W"], self.d["L"], self.d["papers"], self.ff, b=200, seed=1)
        b = hi.bootstrap(self.cl, self.d["W"], self.d["L"], self.d["papers"], self.ff, b=200, seed=1)
        self.assertEqual(a, b)

    def test_weights_fixed_and_empty_cells_dropped(self):
        # Replay the draws: random.Random(1).choice over the paper_id-sorted list, len(papers) draws per replicate;
        # each drawn paper adds its full-build weight (1/3 for A, B, C; 1 for D) however often it is drawn.
        w = {"A": Fraction(1, 3), "B": Fraction(1, 3), "C": Fraction(1, 3), "D": Fraction(1)}
        hd = {"A": 1, "B": 0, "C": 0, "D": 1}
        rng = random.Random(1)
        shares, filt = [], 0
        for _ in range(50):
            seq = [rng.choice(["A", "B", "C", "D"]) for _ in range(4)]
            shares.append(float(sum(w[p] * hd[p] for p in seq) / sum(w[p] for p in seq)))
            filt += "C" in seq
        shares.sort()
        ci, nb = hi.bootstrap(self.cl, self.d["W"], self.d["L"], self.d["papers"], self.ff, b=50, seed=1)
        self.assertEqual(ci[("mix", hi.ALL)], (shares[int(0.025 * 50)], shares[int(0.975 * 50) - 1], 50))
        # filter only in C: replicates without C have weighted n = 0 for that cell and are dropped
        self.assertEqual(ci[("filter", hi.ALL)][2], filt)
        self.assertLess(filt, 50)
        self.assertEqual(ci[("filter", hi.ALL)][:2], (1.0, 1.0))
        self.assertEqual(nb, 50)


class Relabel(unittest.TestCase):
    def conf(self, rows):
        f = Path(self.tmp.name) / "conf.csv"
        with open(f, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["field", "reference_label", "extraction_label", "count"])
            w.writerows(rows)
        return f

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.conf([
            ("unit_operation", "dispense_solid", "dispense_liquid", 3),   # extraction dispense_liquid -> dispense_solid
            ("unit_operation", "(extra)", "anneal", 2),                   # anneal steps deleted
            ("unit_operation", "mix", "(missed)", 1), ("unit_operation", "mix", "mix", 3),
            ("module_type", "liquid_handler", "mixer", 1),                # mixer always redrawn as liquid_handler
            ("transfer_mode", "(extra)", "human_transfer", 1),            # human transfers deleted
            ("transfer_mode", "robot_arm_gantry", "(missed)", 1), ("transfer_mode", "robot_arm_gantry", "robot_arm_gantry", 3),
            ("transfer_mode", "human_transfer", "(missed)", 2)])
        s = Synth()
        c = s.paper("P")
        s.platform(c, "P/P1")
        s.module(c, "P/P1/M1", 1, "mixer")
        s.module(c, "P/P1/M2", 1)
        s.module(c, "P/P1/M3", 1)
        s.step(c, "P/P1/S1", "dispense_liquid", "robot", ["P/P1/M1"])   # depends on people only through (c)
        s.step(c, "P/P1/S2", "anneal", "human", ["P/P1/M3"])            # deleted under relabelling
        s.step(c, "P/P1/S3", "mix", "robot", ["P/P1/M2"])               # mix -> mix
        s.conn(c, "P/P1/E1", "P/P1/M1", "P/P1/M2", "human_transfer")
        s.conn(c, "P/P1/E2", "P/P1/M2", "P/P1/M3", "robot_arm_gantry")
        self.d = hi.load(s.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_confusion_and_miss_rates(self):
        tab, miss = hi.read_confusion(self.path)
        self.assertEqual(tab["unit_operation"]["anneal"], (["(extra)"], [2]))
        self.assertEqual(tab["unit_operation"]["mix"], (["mix"], [3]))
        self.assertNotIn("(missed)", tab["transfer_mode"])
        self.assertEqual(miss["transfer_mode"]["robot_arm_gantry"], {"missed": 1, "reference_items": 4, "miss_rate": 0.25})
        self.assertEqual(miss["transfer_mode"]["human_transfer"]["miss_rate"], 1.0)   # 2 missed of 2 reference items
        self.assertEqual(miss["unit_operation"]["mix"]["miss_rate"], 0.25)

    def test_deterministic_relabel_and_extra_deletion(self):
        tab, _ = hi.read_confusion(self.path)
        # Recorded: dispense_liquid hd (via E1), anneal hd (human), mix hd (M2 is the to_module of human E1).
        # Relabelled: dispense_liquid -> dispense_solid; anneal deleted; E1 deleted, so no (c) anywhere:
        # dispense_solid share 0, mix share 0; anneal and dispense_liquid absent.
        r = hi.relabel(self.d, tab, b=5)
        self.assertEqual(sorted(r["per_unit_operation"]), ["dispense_solid", "mix"])
        for u in ("dispense_solid", "mix"):
            self.assertEqual(r["per_unit_operation"][u]["share"], {"median": 0.0, "q025": 0.0, "q975": 0.0})
            self.assertEqual(r["per_unit_operation"][u]["replicates"], 5)
        self.assertEqual(r["steps_deleted"]["median"], 1)
        self.assertEqual(r["connections_deleted"]["median"], 1)
        # three steps with a primary module; only the mixer one changes type
        self.assertEqual(r["primary_module_type_changed_share"]["median"], 1 / 3)

    def test_labels_outside_the_table_stay(self):
        r = hi.relabel(self.d, {}, b=2)
        cl = hi.step_cells(self.d["steps"], hi.composite(hi.components(self.d["steps"], self.d["conns"])))
        self.assertEqual(sorted(r["per_unit_operation"]), sorted(cl["P"]))
        self.assertTrue(all(v["share"]["median"] == 1.0 for v in r["per_unit_operation"].values()))


class UncertainExcluded(unittest.TestCase):
    def test_uncertain_items_excluded(self):
        s = Synth()
        c = s.paper("P")
        s.platform(c, "P/P1")
        for m in ("M1", "M2", "M3"):
            s.module(c, f"P/P1/{m}")
        s.step(c, "P/P1/S1", "mix", "robot", ["P/P1/M1"])
        s.step(c, "P/P1/S2", "filter", "human", ["P/P1/M2"], uncertain=True)
        s.step(c, "P/P1/S3", "anneal", "robot", ["P/P1/M3"])
        s.conn(c, "P/P1/E1", "P/P1/M1", "P/P1/M2", "human_transfer", uncertain=True)
        d = hi.load(s.db)
        tb = hi.uncertain_excluded(d)
        # mix loses its (c) (E1 excluded), filter disappears, anneal unchanged
        self.assertEqual({u: v for (u, g), v in tb["t"].items() if g == hi.ALL}, {"mix": [1, 0], "anneal": [1, 0]})
        self.assertEqual((tb["steps_excluded"], tb["connections_excluded"]), (1, 1))


class PairedComparison(unittest.TestCase):
    def test_kappa_toy_pair(self):
        # a = h h r r, b = h r r r: po = 3/4; pe = (2*1 + 2*3) / 16 = 1/2; kappa = (3/4 - 1/2) / (1/2) = 1/2
        pairs = [({"v": x}, {"v": y}) for x, y in zip("hhrr", "hrrr")]
        self.assertEqual(hi.agreement(pairs), {"n": 4, "agreement": 0.75, "kappa": 0.5})

    def test_pairing_and_agreement_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s = build_test_paper(root)
            r = hi.paired_comparison(s.db, root)
        # S1-S1 pair by evidence location (Fig. 2); S2-S2 by platform + family (react); record S3 unpaired.
        self.assertEqual((r["papers"], r["paired_steps"], r["reference_unpaired_steps"], r["db_record_unpaired_steps"]),
                         (1, 2, 0, 1))
        # performed_by (robot, robot), (human, robot): agreement 1/2; kappa: po 1/2, pe (1*2)/4 = 1/2 -> 0
        self.assertEqual(r["performed_by"], {"n": 2, "agreement": 0.5, "kappa": 0.0})
        # module pairs (M1, M1), (M2, M2); on_platform (1, 1), (1, 0): agreement 1/2, pe = (2*1)/4 -> kappa 0
        self.assertEqual(r["on_platform_module_pairs"], {"n": 2, "agreement": 0.5, "kappa": 0.0})
        self.assertEqual((r["module_pairs"], r["module_pair_conflicts"], r["reference_unpaired_modules"],
                          r["db_record_unpaired_modules"], r["paired_steps_without_primary_module"]), (2, 0, 0, 0, 0))
        # composite (F, F), (T, T): human in the reference, off-platform module in the record -> kappa 1
        self.assertEqual(r["composite"], {"n": 2, "agreement": 1.0, "kappa": 1.0})

    def test_module_pairs_deduplicated_conflicts_and_unpaired(self):
        # Each step pair shares a figure (rule R1). Step pairs give module pairs (M1, M1), (M2, M2), (M2, M2) again,
        # (M1, M3), and S5 has no record module. Distinct pairs: (M1, M1), (M1, M3), (M2, M2) -> 3; reference M1 is in
        # two pairs -> 1 conflict (reference side), 0 on the record side. Unpaired modules: reference M9, record M8.
        # on_platform: (1, 1), (1, 1) [M1, M3], (1, 0) [M2, M2] -> agreement 2/3; kappa: po = 2/3, record marginals
        # {1: 2, 0: 1}, reference {1: 3}: pe = 3*2/9 = 2/3 -> kappa 0.
        ev = lambda k: f"main; {k}; Fig. {k}"
        codings = {"reference": [("T/P1/S1", "dispense_liquid", "robot", "T/P1/M1", ev(1)),
                              ("T/P1/S2", "anneal", "robot", "T/P1/M2", ev(2)),
                              ("T/P1/S3", "anneal", "robot", "T/P1/M2", ev(3)),
                              ("T/P1/S4", "mix", "robot", "T/P1/M1", ev(4)),
                              ("T/P1/S5", "filter", "robot", "T/P1/M1", ev(5))],
                "extractor_a": [("T/P1/S1", "dispense_liquid", "robot", "T/P1/M1", ev(1)),
                                ("T/P1/S2", "anneal", "robot", "T/P1/M2", ev(2)),
                                ("T/P1/S3", "anneal", "robot", "T/P1/M2", ev(3)),
                                ("T/P1/S4", "mix", "robot", "T/P1/M3", ev(4)),
                                ("T/P1/S5", "filter", "robot", None, ev(5))]}
        on = {"reference": {"T/P1/M1": 1, "T/P1/M2": 1, "T/P1/M9": 1},
              "extractor_a": {"T/P1/M1": 1, "T/P1/M2": 0, "T/P1/M3": 1, "T/P1/M8": 0}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r = hi.paired_comparison(build_test_paper(root, codings, on).db, root)
        self.assertEqual((r["paired_steps"], r["paired_steps_without_primary_module"], r["module_pairs"]), (5, 1, 3))
        self.assertEqual((r["module_pair_conflicts_reference_side"], r["module_pair_conflicts_db_record_side"],
                          r["module_pair_conflicts"]), (1, 0, 1))
        self.assertEqual((r["reference_modules"], r["db_record_modules"], r["reference_unpaired_modules"],
                          r["db_record_unpaired_modules"]), (3, 4, 1, 1))
        self.assertEqual(r["on_platform_module_pairs"]["n"], 3)
        self.assertAlmostEqual(r["on_platform_module_pairs"]["agreement"], 2 / 3)
        self.assertAlmostEqual(r["on_platform_module_pairs"]["kappa"], 0.0)

    def test_changed_coding_file_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s = build_test_paper(root)
            (root / "codings" / "T_reference.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(SystemExit):
                hi.paired_comparison(s.db, root)


def build_test_paper(root, codings=None, on=None):
    """One test paper T: reference coding and database-record coding, with their JSON files and source_file rows.
    codings: role -> [(step_id, unit operation, performed_by, primary module or None, evidence)]; on: role -> {module: 0/1}."""
    s = Synth()
    (root / "codings").mkdir()
    codings = codings or {"reference": [("T/P1/S1", "dispense_liquid", "robot", "T/P1/M1", "main; 3; Fig. 2"),
                                  ("T/P1/S2", "anneal", "human", "T/P1/M2", "main; 4; Methods")],
                    "extractor_a": [("T/P1/S1", "dispense_liquid", "robot", "T/P1/M1", "main; 3; Fig. 2"),
                                    ("T/P1/S2", "anneal", "robot", "T/P1/M2", "main; 5; Methods"),
                                    ("T/P1/S3", "measure_optical", "robot", "T/P1/M1", "main; 6; Fig. 3")]}
    on = on or {"reference": {"T/P1/M1": 1, "T/P1/M2": 1}, "extractor_a": {"T/P1/M1": 1, "T/P1/M2": 0}}
    for role, steps in codings.items():
        ref = role == "reference"
        c = s.paper("T", gold="test" if ref else None, role=role, add_paper=ref,
                    label="fable-5.1-reference-test" if ref else "opus", model="claude-fable-5-1" if ref else "m")
        s.platform(c, "T/P1")
        for m, o in on[role].items():
            s.module(c, m, o)
        for sid, u, pb, m, ev in steps:
            s.step(c, sid, u, pb, [m] if m else [])
        js = {"paper_id": "T", "modules": [{"module_id": m, "module_type": "liquid_handler"} for m in on[role]],
              "steps": [{"step_id": sid, "unit_operation": u, "performed_by": pb, "module_ids": [m] if m else [],
                         "evidence": ev} for sid, u, pb, m, ev in steps], "connections": []}
        rel = f"codings/T_{role}.json"
        (root / rel).write_text(json.dumps(js), encoding="utf-8")
        s.db.execute("INSERT INTO source_file VALUES (?, ?, 'coding_json')",
                     (rel, hashlib.sha256((root / rel).read_bytes()).hexdigest()))
    # the build also stores the second extraction (run B) of the test papers; it must not be taken as either side
    s.paper("T", role="extractor_b", add_paper=False)
    return s


class EndToEnd(unittest.TestCase):
    def test_analyse_runs_and_reports_every_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s = build_test_paper(root)
            k = 0
            for tag, n, h in (("catalysis", 5, 3), ("nanomaterials", 5, 3), ("materials_polymer_soft", 5, 3)):
                for i in range(n):
                    k += 1
                    s.simple(f"X{k:03d}", [("anneal", i < h), ("mix", False)], tags=(tag,), year=2020 + i,
                             gold="dev" if k == 1 else None)
            conf = root / "conf.csv"
            conf.write_text("field,reference_label,extraction_label,count\nunit_operation,mix,mix,1\n", encoding="utf-8")
            res, rows, fc = hi.analyse(s.db, root, conf, b=20, s1_b=5)
        self.assertEqual(res["papers"], 16)
        self.assertEqual(res["main"]["fields"]["anneal"], {"fields_share_ge_half": 3, "fields_share_lt_half": 0})
        analyses = {r["analysis"] for r in rows}
        for a in ("main", "condition_a_performed_by_human", "condition_b_primary_module_off_platform",
                  "condition_c_human_transfer", "step_level", "unweighted", "all_field_tags", "period_early",
                  "period_late", "unit_operation_family", "without_independently_coded_papers",
                  "uncertain_items_excluded"):
            self.assertIn(a, analyses)
        fam = {(r["label"], r["group"]) for r in rows if r["analysis"] == "unit_operation_family"}
        self.assertIn(("react", hi.ALL), fam)
        # period: years 2020-2024 per field -> the 2024 papers are late (3 papers; T has year 2022)
        self.assertEqual(res["further"]["period"]["late"]["papers"], 3)
        self.assertEqual(res["paired_comparison"]["paired_steps"], 2)
        self.assertEqual({r["unit_operation"]: r["fields_share_ge_half"] for r in fc},
                         {"anneal": 3, "dispense_liquid": 0, "measure_optical": 0, "mix": 0})
        with tempfile.TemporaryDirectory() as tmp:
            od = Path(tmp) / "out"
            hi.write_outputs(res, rows, fc, od)
            self.assertEqual(sorted(p.name for p in od.iterdir()), ["field_counts.csv", "results.json", "shares.csv"])

    def test_edge_id_without_trailing_number_stops(self):
        s = Synth()
        c = s.simple("X", [("mix", False)])
        s.module(c, "X/P1/M2")
        s.conn(c, "X/P1/Ex", "X/P1/M1", "X/P1/M2", "robot_arm_gantry")
        with self.assertRaises(SystemExit):
            hi.load(s.db)


class SchemaMatchesBuild(unittest.TestCase):
    def test_schema_file_is_the_build_schema(self):
        mem = sqlite3.connect(":memory:")
        mem.executescript(SCHEMA.read_text(encoding="utf-8"))
        want = sorted(mem.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall())
        if not REAL_DB.exists():
            self.skipTest(f"{REAL_DB} not present")
        db = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
        got = sorted(db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall())   # schema only
        db.close()
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
