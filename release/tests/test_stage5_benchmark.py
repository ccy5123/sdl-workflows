"""Stage 5: the benchmark tables are built with sdl-db-02's own item code and its recorded values, and the shipped
evaluate.py reproduces them from the release files alone. The hand-worked examples are those of
analysis/sdl-db-02/test_h1_evaluate.py, in the release's item format.
Run from the workspace root: python3 -m unittest discover release/tests -v
"""
import csv
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import evaluate as ev  # noqa: E402
import export_release as ex  # noqa: E402
from fixture import build_fixture  # noqa: E402


def it(l1, l2, l3, l4, label, paper="P", item="i"):
    return {"ctx": [l1, l2, l3, l4], "label": label, "paper": paper, "item": item}


class ModelTies(unittest.TestCase):
    def setUp(self):
        # i1, i2 share L1; i3 shares only L2 (and L4) with them; i4 is elsewhere.
        self.train = [it(("u", "S", "E", "t1"), ("u", "S", "E"), ("u", "t1"), ("u",), "X", item="1"),
                      it(("u", "S", "E", "t1"), ("u", "S", "E"), ("u", "t1"), ("u",), "Y", item="2"),
                      it(("u", "S", "E", "t2"), ("u", "S", "E"), ("u", "t2"), ("u",), "Y", item="3"),
                      it(("v", "S", "E", "t1"), ("v", "S", "E"), ("v", "t1"), ("v",), "Z", item="4")]
        self.q = it(("u", "S", "E", "t1"), ("u", "S", "E"), ("u", "t1"), ("u",), "?")

    def test_tie_broken_by_next_coarser_context(self):
        # L1 count 2: X 1, Y 1 tie; L2 has X 1, Y 2 -> Y. Top-3: L1 ranking [Y, X], filled from all items -> Z.
        self.assertEqual(ev.Model(self.train).reference(self.q), ("Y", ["Y", "X", "Z"], 1))

    def test_alphabetical_when_the_coarser_context_also_ties(self):
        self.assertEqual(ev.Model(self.train[:2]).reference(self.q)[0], "X")

    def test_min_count_moves_to_a_coarser_context(self):
        # min count 3: L1 has 2 items, L2 has 3 -> level 2, X 1 Y 2 -> Y
        top1, _, level = ev.Model(self.train, min_count=3).reference(self.q)
        self.assertEqual((top1, level), ("Y", 2))

    def test_unseen_context_uses_all_items(self):
        q = it(("w", "S", "E", "t9"), ("w", "S", "E"), ("w", "t9"), ("w",), "?")
        self.assertEqual(ev.Model(self.train).reference(q), ("Y", ["Y", "X", "Z"], 5))
        self.assertEqual(ev.Model(self.train).baseline(q), ("Y", ["Y", "X", "Z"]))

    def test_baseline_tie_alphabetical(self):
        self.assertEqual(ev.Model(self.train[:2]).baseline(self.q)[0], "X")


class Bootstrap(unittest.TestCase):
    def test_hand_replicates(self):
        test = [{"paper": "P1", "label": "X"}, {"paper": "P1", "label": "X"}, {"paper": "P2", "label": "X"}]
        first, second = ["X", "X", "Y"], ["X", "Y", "X"]
        sets = [["P1", "P1", "P1"], ["P2", "P2", "P3"], ["P1", "P2", "P3"]]
        # set1 n 6, first 6, second 3 -> +0.5; set2 n 2, 0, 2 -> -1; set3 n 3, 2, 2 -> 0.
        # n = 3: positions int(0.075) = 0 and int(2.925) - 1 = 1 of [-1, 0, 0.5]
        a1, a2, diff, ci, reps = ev.paired_difference(test, first, second, ["P1", "P2", "P3"], sets)
        self.assertEqual((a1, a2, ci, reps), (2 / 3, 2 / 3, (-1.0, 0.0), 3))

    def test_replicate_without_items_is_dropped(self):
        test = [{"paper": "P3", "label": "T"}]
        _, _, _, ci, reps = ev.paired_difference(test, ["T"], ["U"], ["P1", "P2", "P3"],
                                                 [["P1", "P1", "P1"], ["P2", "P2", "P3"], ["P1", "P2", "P3"]])
        self.assertEqual((ci, reps), ((1.0, 1.0), 2))

    def test_interval_positions(self):
        self.assertEqual(ev.interval(list(range(2000, 0, -1))), (51, 1950))

    def test_sets_follow_seed_one(self):
        rng = random.Random(1)
        expect = [[rng.choice(["P1", "P2", "P3"]) for _ in range(3)] for _ in range(5)]
        self.assertEqual(ev.bootstrap_sets(["P1", "P2", "P3"], b=5), expect)


def benchmark_folder(items, papers, task):
    """A benchmark folder with one module_type task."""
    folder = Path(tempfile.mkdtemp())
    (folder / "tasks").mkdir()
    cols = ["task_id", "item_id", "paper_id", "platform_id", "split", "label", "field_tag", "unit_operation",
            "prev_unit_operation", "next_unit_operation", "from_unit_operation", "to_unit_operation", "from_family",
            "to_family", "uncertain"]
    with (folder / "items_module_type.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols, restval="")
        w.writeheader()
        w.writerows(items)
    with (folder / "split.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["benchmark_id", "paper_id", "split", "exclusion_reason"])
        w.writerows(papers)
    (folder / "tasks" / "chrono2023-module_type.json").write_text(json.dumps(task), encoding="utf-8")
    return folder


class EvaluateFiles(unittest.TestCase):
    def setUp(self):
        def row(i, paper, split, label, u):
            return {"task_id": "chrono2023-module_type", "item_id": i, "paper_id": paper, "platform_id": paper + "/P1",
                    "split": split, "label": label, "field_tag": "chem", "unit_operation": u,
                    "prev_unit_operation": "START", "next_unit_operation": "END", "uncertain": 0}
        # train: mix -> mixer twice, batch_reactor once; react_thermal -> batch_reactor.
        # test: T1 (mix, truth mixer) right by both; T2 (react_thermal, truth flow_reactor) wrong by both; T3 in a
        # paper of the excluded split is never scored.
        items = [row("A1", "P1", "train", "mixer", "mix"), row("A2", "P1", "train", "mixer", "mix"),
                 row("A3", "P1", "train", "batch_reactor", "mix"),
                 row("A4", "P1", "train", "batch_reactor", "react_thermal"),
                 row("T1", "P2", "test", "mixer", "mix"), row("T2", "P3", "test", "flow_reactor", "react_thermal"),
                 row("T3", "P4", "excluded", "mixer", "mix")]
        papers = [("chrono2023", "P1", "train", ""), ("chrono2023", "P2", "test", ""),
                  ("chrono2023", "P3", "test", ""), ("chrono2023", "P4", "excluded", "development")]
        self.task = {"task_id": "chrono2023-module_type", "benchmark_id": "chrono2023", "target": "module_type",
                     "n_test_items": 2, "n_test_papers": 2, "baseline_top1": 0.5, "reference_model_top1": 0.5,
                     "diff_ci95_low": 0.0, "diff_ci95_high": 0.0}
        self.folder = benchmark_folder(items, papers, self.task)
        self.addCleanup(shutil.rmtree, self.folder)

    def test_scores_and_match(self):
        task, result, predictions = ev.evaluate(self.folder, "chrono2023-module_type")
        self.assertEqual([p["item_id"] for p in predictions], ["T1", "T2"])
        self.assertEqual((result["baseline_top1"], result["reference_model_top1"]), (0.5, 0.5))
        self.assertEqual(ev.mismatches(task, result), [])
        self.assertEqual(ev.mismatches(dict(task, baseline_top1=0.6), result), [("baseline_top1", 0.6, 0.5)])

    def test_your_predictions(self):
        pred = self.folder / "mine.csv"
        pred.write_text("item_id,prediction\nT1,mixer\nT2,flow_reactor\n", encoding="utf-8")
        res = ev.score_predictions(self.folder, "chrono2023-module_type", pred)
        self.assertEqual((res["predictions_top1"], res["baseline_top1"], res["difference"]), (1.0, 0.5, 0.5))
        pred.write_text("item_id,prediction\nT1,mixer\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            ev.score_predictions(self.folder, "chrono2023-module_type", pred)


class ExportFixture(unittest.TestCase):
    def evidence(self, a_items, b_items):
        path = Path(tempfile.mkdtemp()) / "evi.json"
        rec = {"a_items": a_items, "a_tool": 0.5, "a_baseline": 0.4, "a_diff_ci95": [0.0, 0.2],
               "b_items": b_items, "b_tool": 0.5, "b_baseline": 0.4, "b_diff_ci95": [0.0, 0.2]}
        path.write_text(json.dumps({"id": "evi-test", "result": {"finding": json.dumps(rec)}}), encoding="utf-8")
        return path

    def test_split_and_items(self):
        db = build_fixture()
        rel = ex.new_release_db()
        ex.export_core(db, rel, ex.load_definitions(db))
        ex.export_benchmark(db, rel, self.evidence(0, 0))
        # Lee2020 (2020) trains; Kim2025 (2025) is a development paper of a test year -> excluded
        self.assertEqual(rel.execute("SELECT paper_id, split, exclusion_reason FROM benchmark_split ORDER BY 1")
                         .fetchall(), [("Kim2025", "excluded", ex.EXCLUSION_REASON), ("Lee2020", "train", None)])
        # Lee2020 steps: dispense_liquid (M1), react_thermal (M2, flagged), measure_optical (M3), analyze_data and
        # plan_next_experiment (M4); first field tag chemistry_synthesis
        self.assertEqual(rel.execute("SELECT unit_operation, prev_unit_operation, next_unit_operation, label, "
                                     "field_tag, uncertain, split FROM benchmark_item "
                                     "WHERE item_id = 'Lee2020/P1/S2'").fetchone(),
                         ("react_thermal", "dispense_liquid", "measure_optical", "batch_reactor",
                          "chemistry_synthesis", 1, "train"))
        # M1 -> M2 by robot arm attaches to the consecutive steps S1, S2; data transfers are not items
        self.assertEqual(rel.execute("SELECT from_unit_operation, to_unit_operation, from_family, to_family "
                                     "FROM benchmark_item WHERE task_id = 'chrono2023-transfer_mode' "
                                     "AND paper_id = 'Lee2020' AND label = 'robot_arm_gantry'").fetchall(),
                         [("dispense_liquid", "react_thermal", "prepare", "react")])
        self.assertEqual(rel.execute("SELECT COUNT(*) FROM benchmark_item WHERE label = 'data_transfer'")
                         .fetchone()[0], 0)
        self.assertEqual(rel.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_item_count_differing_from_the_record_fails(self):
        db = build_fixture()
        rel = ex.new_release_db()
        ex.export_core(db, rel, ex.load_definitions(db))
        with self.assertRaises(ex.ExportError):
            ex.export_benchmark(db, rel, self.evidence(1199, 426))


@unittest.skipUnless(ex.INTERNAL_DB.exists(), "internal build not present")
class RecordedBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = ex.open_internal()
        rel = ex.new_release_db()
        ex.export_core(db, rel, ex.load_definitions(db), redactions=ex.load_redactions())
        ex.export_benchmark(db, rel)
        cls.rel = rel
        cls.folder = Path(tempfile.mkdtemp())
        ex.write_benchmark_files(rel, cls.folder)
        cls.results = {t: ev.evaluate(cls.folder, t) for t in ev.ITEM_FILES}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder)

    def test_split(self):
        self.assertEqual(self.rel.execute("SELECT split, COUNT(*) FROM benchmark_split GROUP BY 1 ORDER BY 1")
                         .fetchall(), [("excluded", 4), ("test", 99), ("train", 135)])

    def test_evaluate_reproduces_the_recorded_values(self):
        for task_id, (task, result, _) in self.results.items():
            self.assertEqual(ev.mismatches(task, result), [], task_id)
        self.assertEqual(round(self.results["chrono2023-module_type"][1]["baseline_top1"], 4), 0.6681)
        self.assertEqual(round(self.results["chrono2023-transfer_mode"][1]["reference_model_top1"], 4), 0.5117)
        self.assertEqual([self.results[t][1]["n_test_items"] for t in sorted(ev.ITEM_FILES)], [1199, 426])

    def test_shipped_script_runs_alone(self):
        # a copy beside the files, isolated mode: nothing from the workspace can be imported
        copy = self.folder / "evaluate.py"
        shutil.copy(ex.HERE / "evaluate.py", copy)
        run = subprocess.run([sys.executable, "-I", str(copy), str(self.folder)], capture_output=True, text=True,
                             cwd=self.folder, timeout=200)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stdout.count("matches the recorded values"), 2)

    @unittest.skipUnless((ex.SDL_DB_02 / "out/evaluation/predictions.csv").exists(), "sdl-db-02 predictions absent")
    def test_per_item_predictions_match_sdl_db_02(self):
        field = {"a": "chrono2023-module_type", "b": "chrono2023-transfer_mode"}
        with (ex.SDL_DB_02 / "out/evaluation/predictions.csv").open(encoding="utf-8") as f:
            old = {(field[r["field"]], r["item"]): (r["y"], r["tool_top1"], r["tool_top3"], r["tool_level"],
                                                    r["baseline_top1"], r["baseline_top3"])
                   for r in csv.DictReader(f) if r["set"] == "main"}
        new = {(p["task_id"], p["item_id"]): (p["label"], p["reference_top1"], p["reference_top3"],
                                              str(p["reference_level"]), p["baseline_top1"], p["baseline_top3"])
               for _, _, preds in self.results.values() for p in preds}
        self.assertEqual(len(old), 1625)
        self.assertEqual(new, old)


if __name__ == "__main__":
    unittest.main()
