"""Stage 8: check_release.py passes a good bundle and fails each of six bundles broken on purpose, one per release
condition. The broken bundles are copies of the fixture bundle with one change.
Run from the workspace root: python3 -m unittest discover release/tests -v
"""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import check_release as cr  # noqa: E402
import export_release as ex  # noqa: E402
from fixture import needs_frozen_documents  # noqa: E402
from test_stage4_documents import workspace  # noqa: E402
from test_stage6_bundle import build, evidence, fixture_db, info  # noqa: E402


def edit_sqlite(bundle, *sql):
    db = sqlite3.connect(bundle / "sdl-workflows.sqlite")
    db.execute("PRAGMA foreign_keys = OFF")
    for s in sql:
        db.execute(s)
    db.commit()
    db.close()


def edit_task(bundle):
    path = bundle / "modes/benchmark/tasks/chrono2023-module_type.json"
    task = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(dict(task, baseline_top1=0.9)), encoding="utf-8")


BREAKS = {
    "1 integrity": lambda b: edit_sqlite(b, "UPDATE module SET module_type = 'robot_arm' "
                                           "WHERE module_id = 'Lee2020/P1/M1'"),
    "2 quotations": lambda b: edit_sqlite(b, """UPDATE platform SET campaigns = 'they wrote "we optimised the """
                                             """yield twice"' WHERE platform_id = 'Lee2020/P1'"""),
    "3 benchmark": edit_task,
    "4 row counts": lambda b: edit_sqlite(b, "DELETE FROM step_module WHERE step_id = 'Lee2020/P1/S5'",
                                          "DELETE FROM step WHERE step_id = 'Lee2020/P1/S5'"),
    "5 source build": lambda b: edit_sqlite(b, "UPDATE release SET source_build_digest = '" + "0" * 64 + "'"),
    "6 HTML entities": lambda b: edit_sqlite(b, "UPDATE candidate SET title = 'A robot &amp; a reactor' "
                                                "WHERE cand_id = 'C0001'"),
}


@needs_frozen_documents
class BrokenBundles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = workspace()
        cls.out = Path(tempfile.mkdtemp())
        cls.evidence = evidence()
        cls.db = fixture_db()
        cls.digest = info(cls.db)["source_build_digest"]
        cls.bundle = build(cls.out, cls.root, cls.evidence, fixture_db())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)
        shutil.rmtree(cls.out)

    def results(self, bundle):
        return {name: ok for name, ok, _ in cr.check(bundle, self.db, self.evidence, self.digest)}

    def test_good_bundle_passes(self):
        self.assertEqual(self.results(self.bundle), {name: True for name in ["manifest", *BREAKS]})

    def test_each_broken_bundle_fails_its_condition(self):
        for name, breaker in BREAKS.items():
            with self.subTest(condition=name):
                copy = Path(tempfile.mkdtemp()) / self.bundle.name
                shutil.copytree(self.bundle, copy)
                self.addCleanup(shutil.rmtree, copy.parent)
                breaker(copy)
                results = self.results(copy)
                self.assertFalse(results[name], results)
                self.assertFalse(results["manifest"])          # any edit also changes a listed hash

    def test_csv_short_of_its_table_fails_the_row_counts(self):
        copy = Path(tempfile.mkdtemp()) / self.bundle.name
        shutil.copytree(self.bundle, copy)
        self.addCleanup(shutil.rmtree, copy.parent)
        path = copy / "core" / "step.csv"
        path.write_text("".join(path.read_text(encoding="utf-8").splitlines(keepends=True)[:-1]), encoding="utf-8")
        self.assertFalse(self.results(copy)["4 row counts"])

    def test_unlisted_file_fails_the_manifest(self):
        copy = Path(tempfile.mkdtemp()) / self.bundle.name
        shutil.copytree(self.bundle, copy)
        self.addCleanup(shutil.rmtree, copy.parent)
        (copy / "notes.txt").write_text("extra", encoding="utf-8")
        results = self.results(copy)
        self.assertFalse(results["manifest"])
        self.assertTrue(all(ok for name, ok in results.items() if name != "manifest"))


@unittest.skipUnless(ex.INTERNAL_DB.exists() and (ex.ROOT / ex.CODER_INPUTS).exists(), "workspace files not present")
class RecordedBundle(unittest.TestCase):
    def test_release_bundle_passes_every_check(self):
        meta = json.loads(ex.RELEASE_INFO.read_text(encoding="utf-8"))
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out)
        db = ex.open_internal()
        rel = ex.build_release_db(db, meta)
        bundle = ex.write_bundle(rel, meta, ex.document_values(rel, db, meta), out)
        results = cr.check(bundle, ex.open_internal(), ex.BENCHMARK_EVIDENCE, meta["source_build_digest"])
        self.assertEqual([(n, ok) for n, ok, _ in results], [(n, True) for n, _, _ in results],
                         [r for r in results if not r[1]])


if __name__ == "__main__":
    unittest.main()
