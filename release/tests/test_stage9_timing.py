"""Stage 9 (release 1.1.0): the timing data and the human-intervention reporting. Only values, units, the
categorical parts of each qualifier and locations reach the release; the reference timing extraction does not;
every item a value names is an item of the release; the human-intervention files must be the recorded set; and the
tables of 1.0.0 keep their rows.
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
import check_release as cr  # noqa: E402
import export_release as ex  # noqa: E402
from fixture import needs_frozen_documents  # noqa: E402
from test_stage4_documents import HUMAN_FILES, put_human, workspace  # noqa: E402
from test_stage6_bundle import build, evidence, fixture_db, info  # noqa: E402

PROCESS_SHA = hashlib.sha256(ex.PROCESS_PROMPT.read_bytes()).hexdigest()


def timing_db(reference=True):
    """fixture_db() with a timing extraction of Lee2020 on its record coding and, if reference, a reference
    extraction of Kim2025 that must not reach the release (the documents need one reference paper per coding
    reference paper, and fixture_db() has none). Expected release rows are worked out in the tests below."""
    db = fixture_db()
    ins = lambda table, row: db.execute(f"INSERT INTO {table} VALUES ({','.join('?' * len(row))})", row)
    lee, kim = "Lee2020|process-extractor|p", "Kim2025|process-reference|p"
    for xid, pid, role, rec in ((lee, "Lee2020", "extractor", "Lee2020|extractor_a|p1"),
                                (kim, "Kim2025", "reference", "Kim2025|extractor_a|p1")):
        src = f"extraction/process/{role}/{pid}.json"
        ins("source_file", (src, "4" * 64, "process_json"))
        ins("process_extraction", (xid, pid, role, f"{role}-label", "claude-opus-5-5", "extraction/process-v1.md",
                                   PROCESS_SHA, rec, src, 'notes with "a quoted passage from the paper"'))
    c = "Lee2020|extractor_a|p1"
    for sid, q, v, u, qual, doc in (
            ("S1", "duration", 30, "min", "range 20-40 min; residence time chosen by the planner", "main"),
            ("S2", "duration", 2, "h", "approximately; covers Lee2020/P1/S2, Lee2020/P1/S3", "SI1"),
            ("S2", "duration_batch_size", 96, "samples", "one plate shaken together", "SI1"),
            ("S4", "duration", 70, "s", "upper bound; range 20 s-2 min", "main")):
        ins("step_process", (lee, c, f"Lee2020/P1/{sid}", q, v, u, qual, doc, 4, "Table S1"))
    ins("step_process", (kim, "Kim2025|extractor_a|p1", "Kim2025/P1/S2", "duration", 5, "min", "", "main", 2, "Fig. 1"))
    for kind, tid, q, v, u, qual in (
            ("platform", "Lee2020/P1", "batch_size", 1, "samples", "sequential simplex: one experiment at a time"),
            ("platform", "Lee2020/P1", "throughput", 12, "experiments/d", "measured; N=24; T=2 d; per working day"),
            ("platform", "Lee2020/P1", "throughput_less_automated", 4, "experiments/d",
             "Lee2020/P1/S3, Lee2020/P1/E2; nominal"),
            ("platform", "Lee2020/P1", "throughput_automated", 12, "experiments/d", "measured; N=24; T=2 d"),
            ("platform", "Lee2020/P1", "operating_hours_per_day", 8, "h", "human"),
            ("platform", "Lee2020/P1", "transfer_agent_count", 2, "count", "robot_arm_gantry"),
            ("platform", "Lee2020/P1", "cost", 5000, "USD", "approximately; all purchased hardware"),
            ("module", "Lee2020/P1/M2", "units", 2, "count", ""),
            ("connection", "Lee2020/P1/E1", "transfer_time", 30, "s", "upper bound")):
        ins("process_item", (lee, c, kind, tid, q, v, u, qual, "main", 3, "§2 ¶1"))
    ins("process_item", (kim, "Kim2025|extractor_a|p1", "platform", "Kim2025/P1", "batch_size", 1, "samples", "",
                         "main", 2, "Fig. 1"))
    if not reference:
        for table in ("step_process", "process_item", "process_extraction"):
            db.execute(f"DELETE FROM {table} WHERE process_id = ?", (kim,))
    return db


def timing_tables(db, root):
    rel = ex.build_release_db(db, info(db), root, evidence(), versions=[], additions=[], published=[])
    rel.row_factory = None
    return rel


class Qualifiers(unittest.TestCase):
    def test_categorical_parts(self):
        parts, _ = ex.qualifier_parts("upper bound; approximately; range 2-4 h", 3)
        self.assertEqual(parts, {"bound": "upper", "approximate": 1, "range_midpoint": 1, "range_low": 2.0,
                                 "range_high": 4.0})

    def test_range_in_another_unit_keeps_only_the_flag(self):
        parts, _ = ex.qualifier_parts("range 20 s-2 min", 70)
        self.assertEqual((parts["range_midpoint"], parts["range_low"], parts["range_high"]), (1, None, None))

    def test_free_text_gives_nothing(self):
        parts, segs = ex.qualifier_parts("the paper says it ran approximately overnight (upper bound unclear)", 8)
        self.assertEqual((parts["bound"], parts["approximate"], parts["range_midpoint"]), (None, 0, 0))
        self.assertEqual(len(segs), 1)

    def test_commas_separate_parts_of_a_run_length_qualifier_only_when_asked(self):
        self.assertEqual(ex.qualifier_parts("range 2-4 h, approximately", 3, ";,")[0]["approximate"], 1)
        self.assertEqual(ex.qualifier_parts("range 2-4 h, approximately", 3)[0]["approximate"], 0)

    def test_two_bounds_fail(self):
        with self.assertRaises(ex.ExportError):
            ex.qualifier_parts("upper bound; lower bound", 3)

    def test_location(self):
        self.assertEqual(ex.evidence_location("SI2 ; pdf p.14 ; Table S3"), ("SI2", 14, "Table S3"))
        self.assertEqual(ex.evidence_location(""), (None, None, None))
        with self.assertRaises(ex.ExportError):
            ex.evidence_location("main p.4 Fig. 2")


@needs_frozen_documents
class TimingExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = workspace()
        cls.rel = timing_tables(timing_db(), cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def rows(self, sql):
        return self.rel.execute(sql).fetchall()

    def test_step_timing(self):
        rows = self.rows("SELECT step_id, quantity, value, unit, bound, approximate, range_midpoint, range_low, "
                         "range_high, covers_steps, ev_doc FROM step_timing ORDER BY step_id, quantity")
        self.assertEqual(rows, [
            ("Lee2020/P1/S1", "duration", 30.0, "min", None, 0, 1, 20.0, 40.0, None, "main"),
            ("Lee2020/P1/S2", "duration", 2.0, "h", None, 1, 0, None, None, "Lee2020/P1/S2;Lee2020/P1/S3", "SI1"),
            ("Lee2020/P1/S2", "duration_batch_size", 96.0, "samples", None, 0, 0, None, None, None, "SI1"),
            ("Lee2020/P1/S4", "duration", 70.0, "s", "upper", 0, 1, None, None, None, "main")])

    def test_reference_extraction_is_not_released(self):
        self.assertEqual(self.rows("SELECT COUNT(*) FROM step_timing WHERE step_id LIKE 'Kim2025/%' UNION ALL "
                                   "SELECT COUNT(*) FROM process_value WHERE target_id LIKE 'Kim2025/%'"), [(0,), (0,)])

    def test_process_values(self):
        rows = {r[0]: r[1:] for r in self.rows(
            "SELECT quantity, target_kind, target_id, platform_id, value, unit, throughput_kind, n_experiments, "
            "elapsed_time, elapsed_time_unit, per_working_day, agent, manual_items, bound, approximate "
            "FROM process_value")}
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows["throughput"], ("platform", "Lee2020/P1", "Lee2020/P1", 12.0, "experiments/d",
                                              "measured", 24.0, 2.0, "d", 1, None, None, None, 0))
        self.assertEqual(rows["throughput_automated"][9], 0)                   # not per working day
        self.assertEqual(rows["throughput_less_automated"][5:12],
                         ("nominal", None, None, None, 0, None, "Lee2020/P1/S3;Lee2020/P1/E2"))
        self.assertEqual(rows["operating_hours_per_day"][10], "human")
        self.assertEqual(rows["transfer_agent_count"][10], "robot_arm_gantry")
        self.assertEqual(rows["units"][:3], ("module", "Lee2020/P1/M2", "Lee2020/P1"))
        self.assertEqual(rows["transfer_time"][12], "upper")
        self.assertEqual(rows["cost"][13], 1)
        self.assertEqual(rows["batch_size"][5:], (None,) * 8 + (0,))

    def test_no_free_text_reaches_the_release(self):
        for table in ("step_timing", "process_value", "human_intervention"):
            for row in self.rows(f"SELECT * FROM {table}"):
                for v in row:
                    if isinstance(v, str):
                        for word in ("simplex", "planner", "plate", "hardware", "quoted", "campaign", "hand"):
                            self.assertNotIn(word, v, (table, row))

    def test_human_intervention(self):
        rows = self.rows("SELECT * FROM human_intervention ORDER BY paper_id")
        self.assertEqual(rows, [
            ("Kim2025", "none_stated", "SI1", 1, "Table S1", 48.0, "h", "lower", 1, 0, None, None, "main", 2, "§3 ¶2"),
            ("Lee2020", "described", "main", 3, "§2 ¶1") + (None,) * 10])


@needs_frozen_documents
class TimingRefusals(unittest.TestCase):
    def setUp(self):
        self.root = workspace()
        self.addCleanup(shutil.rmtree, self.root)

    def refused(self, *sql, db=None):
        db = db or timing_db()
        for s in sql:
            db.execute(s)
        with self.assertRaises(ex.ExportError):
            timing_tables(db, self.root)

    def test_joint_duration_not_on_its_first_step(self):
        self.refused("UPDATE step_process SET qualifier = 'covers Lee2020/P1/S1, Lee2020/P1/S2' "
                     "WHERE step_id = 'Lee2020/P1/S2' AND quantity = 'duration'")

    def test_joint_duration_naming_an_unknown_step(self):
        self.refused("UPDATE step_process SET qualifier = 'covers Lee2020/P1/S2, S3' "
                     "WHERE step_id = 'Lee2020/P1/S2' AND quantity = 'duration'")

    def test_throughput_without_its_kind(self):
        self.refused("UPDATE process_item SET qualifier = 'N=24; T=2 d' WHERE quantity = 'throughput'")

    def test_less_automated_items_outside_the_platform(self):
        self.refused("UPDATE process_item SET qualifier = 'Kim2025/P1/S1; nominal' "
                     "WHERE quantity = 'throughput_less_automated'")

    def test_agent_missing(self):
        self.refused("UPDATE process_item SET qualifier = '' WHERE quantity = 'operating_hours_per_day'")

    def test_quotation_in_a_location(self):
        self.refused("""UPDATE step_process SET ev_locator = '§2 "the reactor was heated overnight"' """
                     "WHERE step_id = 'Lee2020/P1/S1'")

    def test_cited_document_the_coder_did_not_read(self):
        self.refused("UPDATE step_process SET ev_doc = 'SI7' WHERE step_id = 'Lee2020/P1/S1'")

    def test_human_files_other_than_the_recorded_set(self):
        put_human(self.root, {"Lee2020": dict(HUMAN_FILES["Lee2020"], human_intervention="quantified")}, record=False)
        self.refused()

    def test_human_file_read_with_another_coding(self):
        put_human(self.root, {"Lee2020": dict(HUMAN_FILES["Lee2020"],
                                              record_coding="extraction/db/opus_b/Lee2020.json")})
        self.refused()

    def test_human_location_for_not_reported(self):
        put_human(self.root, {"Lee2020": dict(HUMAN_FILES["Lee2020"], human_intervention="not_reported")})
        self.refused()


@needs_frozen_documents
class TimingBundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = workspace()
        cls.out = Path(tempfile.mkdtemp())
        cls.db = timing_db(reference=False)
        cls.bundle = build(cls.out, cls.root, db=timing_db(reference=False))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)
        shutil.rmtree(cls.out)

    def test_files(self):
        def n(path):
            with (self.bundle / path).open(encoding="utf-8") as f:
                return sum(1 for _ in csv.DictReader(f))
        self.assertEqual([n("core/step_timing.csv"), n("core/process_value.csv"), n("core/human_intervention.csv")],
                         [4, 9, 2])
        self.assertEqual(n("modes/simulation/step_timing.csv"), 4)
        self.assertEqual(n("modes/trends/human_intervention.csv"), 2)
        for name in ("process-v1.md", "human-v1.md"):
            self.assertEqual((self.bundle / "protocol" / name).read_bytes(),
                             (ex.ROOT / "extraction" / name).read_bytes())
        readme = (self.bundle / "protocol" / "README.md").read_text(encoding="utf-8")
        self.assertIn(PROCESS_SHA, readme)
        self.assertIn(hashlib.sha256(ex.HUMAN_PROMPT.read_bytes()).hexdigest(), readme)

    def test_documents_count_the_new_rows(self):
        card = (self.bundle / "DATA_CARD.md").read_text(encoding="utf-8")
        self.assertIn("3 step durations and\n1 numbers of samples", card)
        self.assertIn("0 papers state a number for it", card)
        self.assertIn("1 papers state a stretch of the campaign", card)
        self.assertIn("4 rows", (self.bundle / "CHANGELOG.md").read_text(encoding="utf-8").split("\n## 1.0.0")[0])

    def test_check_release_passes_and_counts_the_new_tables(self):
        results = cr.check(self.bundle, self.db, evidence(), info(self.db)["source_build_digest"])
        self.assertEqual([(name, ok) for name, ok, _ in results], [(name, True) for name, _, _ in results],
                         [r for r in results if not r[1]])

    def test_check_release_fails_a_dropped_timing_row_and_an_unknown_item(self):
        import sqlite3
        for sql, name in (("DELETE FROM step_timing WHERE step_id = 'Lee2020/P1/S1'", "4 row counts"),
                          ("UPDATE process_value SET manual_items = 'Lee2020/P1/S9' "
                           "WHERE quantity = 'throughput_less_automated'", "1 integrity")):
            with self.subTest(condition=name):
                copy = Path(tempfile.mkdtemp()) / self.bundle.name
                shutil.copytree(self.bundle, copy)
                self.addCleanup(shutil.rmtree, copy.parent)
                con = sqlite3.connect(copy / "sdl-workflows.sqlite")
                con.execute(sql)
                con.commit()
                con.close()
                results = {n: ok for n, ok, _ in cr.check(copy, self.db, evidence(),
                                                           info(self.db)["source_build_digest"])}
                self.assertFalse(results[name], results)


@unittest.skipUnless(ex.INTERNAL_DB.exists() and (ex.ROOT / ex.CODER_INPUTS).exists()
                     and (ex.ROOT / ex.HUMAN_DIR).exists(), "workspace files not present")
class RecordedTiming(unittest.TestCase):
    PREVIOUS = ex.OUT / "sdl-workflows-1.0.0"

    @classmethod
    def setUpClass(cls):
        cls.info = json.loads(ex.RELEASE_INFO.read_text(encoding="utf-8"))
        cls.out = Path(tempfile.mkdtemp())
        db = ex.open_internal()
        rel = ex.build_release_db(db, cls.info)
        cls.bundle = ex.write_bundle(rel, cls.info, ex.document_values(rel, db, cls.info), cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def n(self, path):
        with (self.bundle / path).open(encoding="utf-8") as f:
            return sum(1 for _ in csv.DictReader(f))

    def test_row_counts(self):
        self.assertEqual([self.n("core/step_timing.csv"), self.n("core/process_value.csv"),
                          self.n("core/human_intervention.csv")], [639, 472, 237])

    def test_human_categories_are_the_recorded_ones(self):
        # Evidence evi-obs-humanset-20261102-112611 records 25 / 73 / 51 / 88 and 48 run lengths
        with (self.bundle / "core/human_intervention.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        counts = {c: sum(r["category"] == c for r in rows) for c in ex.HUMAN_CATEGORIES}
        self.assertEqual(counts, {"quantified": 25, "described": 73, "none_stated": 51, "not_reported": 88})
        self.assertEqual(sum(r["run_length_value"] != "" for r in rows), 48)

    # The only changes 1.1.0 makes to 1.0.0 rows (listed in CHANGELOG.md): the reason given for the benchmark's
    # excluded papers, 'pdf p.' written as 'p.' in the Gottstein2026 correspondence locators, the published-version
    # DOI of the papers in release/inputs/published-versions.csv, the article DOI of Christensen2021's main text,
    # and the removal of Snapp2023 (C1176), the preprint of Snapp2024 (C1499): its rows go, C1176's full-text
    # decision and the version link C1176-C1499 are recorded, Snapp2024 is dated 2023 by that link and moves to the
    # training papers of the benchmark, and Gongora2020's platform-identity row names Snapp2024 as the paper that
    # states the reuse. benchmark_task holds the reference values of the corrected benchmark (test_stage5).
    REMOVED_PAPER = b"Snapp2023"
    REWORDED = {"benchmark_split.csv": [(b"used to develop the extraction instructions",
                                         b"one of the 10 development papers of the coding instructions"),
                                        (b"chrono2023,Snapp2024,test,", b"chrono2023,Snapp2024,train,")],
                "benchmark_item.csv": [(b",Snapp2024,Snapp2024/P1,test,", b",Snapp2024,Snapp2024/P1,train,")],
                "taxonomy_correspondence.csv": [(b" ; pdf p.", b" ; p.")],
                "paper.csv": [(f",{r['preprint_doi']},".encode(), f",{r['published_doi']},".encode())
                              for r in ex.load_rows(ex.PUBLISHED_VERSIONS)]
                + [(b"Snapp2024,C1499,10.1038/s41467-024-48534-4,2024,", b"Snapp2024,C1499,10.1038/s41467-024-48534-4,2023,")],
                "paper_document.csv": [(b",journal,10.26434/chemrxiv.13146404.v1,",
                                        b",journal,10.1038/s42004-021-00550-x,")],
                "platform.csv": [(b",Snapp2023,Gongora2020,", b",Snapp2024,Gongora2020,")],
                "screening.csv": [(b"C1176,fulltext,2,eligible,,model,claude-opus-5-5",
                                   b"C1176,fulltext,2,ineligible,E_duplicate_version,researcher,")]}
    ADDED = {"paper_version_link.csv": [b"C1176,C1499,duplicate_version"]}

    @unittest.skipUnless((ex.OUT / "sdl-workflows-1.0.0").exists(), "1.0.0 bundle not present")
    def test_tables_of_1_0_0_keep_their_rows(self):
        def removed(line):
            return any(f == self.REMOVED_PAPER or f.startswith(self.REMOVED_PAPER + b"/") for f in line.split(b","))

        for old in sorted((self.PREVIOUS / "core").glob("*.csv")):
            if old.name in ("release.csv", "benchmark_task.csv"):
                continue
            expected = old.read_bytes()
            for before, after in self.REWORDED.get(old.name, []):
                expected = expected.replace(before, after)
            lines = [line for line in expected.splitlines() if not removed(line)]
            got = (self.bundle / "core" / old.name).read_bytes().splitlines()
            with self.subTest(table=old.name):
                if old.name in self.ADDED:
                    self.assertEqual(got[0], lines[0])
                    self.assertEqual(sorted(got[1:]), sorted(lines[1:] + self.ADDED[old.name]))
                else:
                    self.assertEqual(got, lines)


if __name__ == "__main__":
    unittest.main()
