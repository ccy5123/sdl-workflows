"""Stage 6: the bundle is written in the layout of schema-design.md section 6, two builds from the same inputs give
the same files, the platform graphs and task files pass their JSON Schemas, and the shipped evaluate.py reproduces
the recorded values inside the bundle.
Run from the workspace root: python3 -m unittest discover release/tests -v
"""
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import export_release as ex  # noqa: E402
from fixture import build_fixture, needs_frozen_documents  # noqa: E402
from test_stage4_documents import workspace  # noqa: E402


def fixture_db():
    """The fixture with Kim2025 (2025) as a test paper instead of an excluded development paper, and with the
    hashes of the shipped instruction and taxonomy files recorded, as in the real build."""
    db = build_fixture()
    db.execute("DELETE FROM gold_membership WHERE paper_id = 'Kim2025'")
    db.execute("UPDATE coding SET prompt_sha256 = ? WHERE role = 'extractor_a'",
               (hashlib.sha256(ex.PROTOCOL_PROMPT.read_bytes()).hexdigest(),))
    db.execute("UPDATE taxonomy_version SET source_sha256 = ?",
               (hashlib.sha256(ex.PROTOCOL_TAXONOMY.read_bytes()).hexdigest(),))
    return db


def evidence(a_tool=1 / 3):
    """Values worked out by hand for fixture_db(); training items are Lee2020's.
    module_type, 3 test items (Kim2025 S1-S3):
      S1 dispense_liquid, truth fluidics: baseline (unit operation) liquid_handler; reference: L1, L2 unseen,
         L3 (dispense_liquid, chemistry_synthesis) seen -> liquid_handler. Both wrong.
      S2 react_flow, truth flow_reactor: unseen everywhere -> all items: software 2 -> software. Both wrong.
      S3 plan_next_experiment, truth software: baseline software; reference L3 -> software. Both right.
      -> 1/3 and 1/3; one test paper, so every replicate's difference is 0: interval [0, 0].
    transfer_mode, 1 test item (Kim2025 M1 -> M2 fixed_tubing, steps S1 -> S2, families prepare -> react):
      baseline (prepare, react) -> robot_arm_gantry; reference L3 (prepare, react, chemistry_synthesis) ->
      robot_arm_gantry. Both wrong -> 0 and 0, interval [0, 0]."""
    rec = {"a_items": 3, "a_tool": a_tool, "a_baseline": 1 / 3, "a_diff_ci95": [0.0, 0.0],
           "b_items": 1, "b_tool": 0.0, "b_baseline": 0.0, "b_diff_ci95": [0.0, 0.0]}
    path = Path(tempfile.mkdtemp()) / "evi.json"
    path.write_text(json.dumps({"id": "evi-fixture", "result": {"finding": json.dumps(rec)}}), encoding="utf-8")
    return path


def info(db):
    return {"release_version": "0.0.1", "released_on": "2026-11-01", "source_build_digest": ex.internal_digest(db),
            "license": "data: CC-BY-4.0; code: MIT", "zenodo_doi": None,
            "authors": [{"family-names": "Doe", "given-names": "Jane", "orcid": "https://orcid.org/0000-0000-0000-0000"}]}


def candidate_sources():
    """Search routes of the fixture candidates: C0001 from a review's reference list, C0002 from a keyword search,
    C0003 from both."""
    path = Path(tempfile.mkdtemp()) / "candidates.csv"
    path.write_text("cand_id,source_ids\nC0001,S0001\nC0002,K0001\nC0003,S0002;K0002\n", encoding="utf-8")
    return path


def quality_evidence():
    """Agreement values for the documents; fixture_db() has no reference-coded paper."""
    rec = {"n_papers": 0}
    for f, v in (("unit_operation", 0.9), ("module_type", 0.8), ("transfer_mode", 0.7)):
        rec.update({f"{f}_strict_micro_f1": v, f"{f}_ci95_lower": v - 0.05})
    path = Path(tempfile.mkdtemp()) / "evi-quality.json"
    path.write_text(json.dumps({"result": {"finding": json.dumps(rec)}}), encoding="utf-8")
    return path


def build(out, root, evidence_path=None, db=None):
    db = db or fixture_db()
    meta = info(db)
    rel = ex.build_release_db(db, meta, root, evidence_path or evidence(), versions=[], additions=[])
    values = ex.document_values(rel, db, meta, candidate_sources(), quality_evidence(), additions=[])
    return ex.write_bundle(rel, meta, values, out)


def manifest(bundle):
    return dict(reversed(line.split("  ", 1)) for line in (bundle / "MANIFEST.sha256").read_text().splitlines())


@needs_frozen_documents
class FixtureBundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = workspace()
        cls.out = Path(tempfile.mkdtemp())
        cls.bundle = build(cls.out, cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)
        shutil.rmtree(cls.out)

    def test_layout(self):
        files = set(manifest(self.bundle))
        self.assertEqual(self.bundle.name, "sdl-workflows-0.0.1")
        for name in ("sdl-workflows.sqlite", "core/step.csv", "core/step.parquet", "core/release.csv",
                     "modes/builder/platforms.csv", "modes/builder/steps.csv", "modes/builder/connections.csv",
                     "modes/builder/platform_graphs.jsonl", "modes/trends/papers.csv", "modes/trends/candidates.csv",
                     "modes/trends/screening.csv", "modes/trends/screening_reasons.csv",
                     "modes/benchmark/split.csv", "modes/benchmark/items_module_type.csv",
                     "modes/benchmark/items_transfer_mode.csv", "modes/benchmark/tasks/chrono2023-module_type.json",
                     "modes/benchmark/evaluate.py", "modes/benchmark/reference_results.json",
                     "modes/taxonomy/classes.csv", "modes/taxonomy/correspondence.csv",
                     "schema/release-schema.sql", "schema/platform-graph.schema.json",
                     "schema/benchmark-task.schema.json", "README.md", "DATA_CARD.md", "CHANGELOG.md",
                     "CITATION.cff", "LICENSE-DATA", "LICENSE-CODE", "data_dictionary.csv",
                     "modes/simulation/README.md", "protocol/README.md", "protocol/prompt-v1.md",
                     "protocol/taxonomy-v1.json", "protocol/coding-guideline.md"):
            self.assertIn(name, files)
        on_disk = {p.relative_to(self.bundle).as_posix() for p in self.bundle.rglob("*") if p.is_file()}
        self.assertEqual(on_disk - {"MANIFEST.sha256"}, files)

    def test_every_table_in_core(self):
        rel = ex.new_release_db()
        for table in ex.release_tables(rel):
            self.assertTrue((self.bundle / "core" / f"{table}.csv").exists(), table)
            self.assertTrue((self.bundle / "core" / f"{table}.parquet").exists(), table)

    def test_csv_and_parquet_hold_the_same_rows(self):
        import pyarrow.parquet as pq
        with (self.bundle / "core" / "step.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        table = pq.read_table(self.bundle / "core" / "step.parquet").to_pylist()
        self.assertEqual(len(rows), 8)
        self.assertEqual([r["step_id"] for r in rows], [r["step_id"] for r in table])
        self.assertEqual(table[0]["step_order"], 1)        # INTEGER stays an integer in Parquet

    def test_platform_graph(self):
        lines = (self.bundle / "modes/builder/platform_graphs.jsonl").read_text(encoding="utf-8").splitlines()
        graphs = {g["platform_id"]: g for g in map(json.loads, lines)}
        lee = graphs["Lee2020/P1"]
        # Lee2020: 4 modules, 5 steps, 4 connections; S4 and S5 run on the software module M4
        self.assertEqual([len(lee[k]) for k in ("modules", "steps", "connections")], [4, 5, 4])
        self.assertEqual(lee["steps"][4]["modules"], ["Lee2020/P1/M4"])
        self.assertEqual(lee["field_tags"], ["chemistry_synthesis", "catalysis"])
        self.assertEqual([c["is_material"] for c in lee["connections"]], [True, True, False, False])
        self.assertTrue(lee["steps"][1]["uncertain"])

    def test_wide_correspondence(self):
        with (self.bundle / "modes/taxonomy/correspondence.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 30 + 21 + 5)
        wash = next(r for r in rows if r["class"] == "wash_extract")
        self.assertEqual(wash["XDL"], "Extract (exact); Separate (exact); Wash (exact)")
        self.assertEqual(wash["OntoLab_SAREF"], "")       # module types only

    def test_reference_results(self):
        res = json.loads((self.bundle / "modes/benchmark/reference_results.json").read_text(encoding="utf-8"))
        self.assertEqual(res["chrono2023-module_type"]["n_test_items"], 3)
        self.assertAlmostEqual(res["chrono2023-module_type"]["reference_model_top1"], 1 / 3)
        self.assertEqual(res["chrono2023-transfer_mode"]["baseline_top1"], 0.0)

    def test_release_row(self):
        with (self.bundle / "core/release.csv").open(encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        self.assertEqual((row["release_version"], row["n_papers"], row["taxonomy_version"]), ("0.0.1", "2", "v1"))

    def test_a_second_build_gives_the_same_files(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out)
        again = build(out, self.root)
        self.assertEqual(manifest(again), manifest(self.bundle))
        self.assertEqual(ex.sqlite_dump_digest(again / "sdl-workflows.sqlite"),
                         ex.sqlite_dump_digest(self.bundle / "sdl-workflows.sqlite"))


@needs_frozen_documents
class Refusals(unittest.TestCase):
    def setUp(self):
        self.root = workspace()
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.addCleanup(shutil.rmtree, self.out)

    def test_another_source_build_fails(self):
        db = fixture_db()
        meta = dict(info(db), source_build_digest="0" * 64)
        with self.assertRaises(ex.ExportError):
            ex.build_release_db(db, meta, self.root, evidence(), versions=[], additions=[])

    def test_evaluate_not_reproducing_the_record_fails(self):
        with self.assertRaises(ex.ExportError):
            build(self.out, self.root, evidence(a_tool=0.9))
        self.assertFalse((self.out / "sdl-workflows-0.0.1" / "MANIFEST.sha256").exists())


@unittest.skipUnless(ex.INTERNAL_DB.exists() and (ex.ROOT / ex.CODER_INPUTS).exists(), "workspace files not present")
class RecordedBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.info = json.loads(ex.RELEASE_INFO.read_text(encoding="utf-8"))
        cls.outs = [Path(tempfile.mkdtemp()) for _ in range(2)]
        cls.bundles = []
        for o in cls.outs:
            db = ex.open_internal()
            rel = ex.build_release_db(db, cls.info)
            cls.bundles.append(ex.write_bundle(rel, cls.info, ex.document_values(rel, db, cls.info), o))

    @classmethod
    def tearDownClass(cls):
        for o in cls.outs:
            shutil.rmtree(o)

    def test_two_builds_are_identical(self):
        a, b = self.bundles
        self.assertEqual(manifest(a), manifest(b))
        self.assertEqual(ex.sqlite_dump_digest(a / "sdl-workflows.sqlite"),
                         ex.sqlite_dump_digest(b / "sdl-workflows.sqlite"))

    def test_row_counts(self):
        def n(rel_path):
            with (self.bundles[0] / rel_path).open(encoding="utf-8") as f:
                return sum(1 for _ in csv.DictReader(f))
        self.assertEqual([n("core/paper.csv"), n("core/step.csv"), n("core/connection.csv")], [238, 2621, 1687])
        self.assertEqual(n("modes/builder/steps.csv"), 2621)
        self.assertEqual(len((self.bundles[0] / "modes/builder/platform_graphs.jsonl")
                             .read_text(encoding="utf-8").splitlines()), 280)

    def test_release_row_names_the_source_build(self):
        with (self.bundles[0] / "core/release.csv").open(encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        self.assertEqual(row["source_build_digest"], "6bc13fac0303d08817c63b1615ef7c0e0c15161982b5853b808cd1226bef320a")
        self.assertEqual(row["n_papers"], "238")


if __name__ == "__main__":
    unittest.main()
