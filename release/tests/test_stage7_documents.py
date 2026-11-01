"""Stage 7: the data dictionary is generated from the column comments of release-schema.sql and covers every
column, and the documents are rendered from templates whose numbers come from the release tables and recorded files.
Run from the workspace root: python3 -m unittest discover release/tests -v
"""
import csv
import hashlib
import json
import re
import shutil
import sqlite3
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
from test_stage6_bundle import build, candidate_sources, evidence, fixture_db, info, quality_evidence  # noqa: E402

SCHEMA = """
-- @column *.note: Shared note.
-- @column t.b: Explicit wins.
CREATE TABLE t (
  a                   TEXT,                      -- first line
                                                 -- continued
  b                   INTEGER,                   -- overridden
  note                TEXT
  -- a section comment, not part of note
);
CREATE TABLE u (
  a                   TEXT                       -- other a
);
CREATE VIEW v AS SELECT b, note FROM t;
CREATE VIEW w AS SELECT a FROM t;
"""


class Comments(unittest.TestCase):
    def test_parsing(self):
        notes = ex.ddl_comments(SCHEMA)
        self.assertEqual(notes[("t", "a")], "first line continued")
        self.assertEqual(notes[("t", "b")], "Explicit wins.")
        self.assertEqual(notes[("*", "note")], "Shared note.")
        self.assertNotIn(("t", "note"), notes)      # the section comment below it is not a continuation

    def test_view_columns_inherit_only_an_unambiguous_description(self):
        rel = sqlite3.connect(":memory:")
        rel.executescript(SCHEMA.replace("CREATE VIEW w AS SELECT a FROM t;", ""))
        rows = {(o, c): d for o, _, c, _, d in ex.data_dictionary(rel, SCHEMA)}
        self.assertEqual(rows[("v", "b")], "Explicit wins.")
        self.assertEqual(rows[("v", "note")], "Shared note.")
        # w.a could be t.a or u.a: no description, so the dictionary refuses
        rel.execute("CREATE VIEW w AS SELECT a FROM t")
        with self.assertRaises(ex.ExportError):
            ex.data_dictionary(rel, SCHEMA)

    def test_release_schema_describes_every_column(self):
        rel = ex.new_release_db()
        rows = ex.data_dictionary(rel, ex.RELEASE_SCHEMA.read_text(encoding="utf-8"))
        n = sum(len(rel.execute(f"PRAGMA table_info({name})").fetchall())
                for (name,) in rel.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"))
        self.assertEqual(len(rows), n)
        self.assertTrue(all(r[4] for r in rows))

    def test_shipped_schema_names_no_internal_files(self):
        text = ex.RELEASE_SCHEMA.read_text(encoding="utf-8")
        for word in ("drafts/", "protocol/", "release/inputs", "extractor", "sdl-db", "evi-"):
            self.assertNotIn(word, text)


class Render(unittest.TestCase):
    def test_missing_value_fails(self):
        self.assertEqual(ex.render("{{a}} and {{b}}", {"a": 1, "b": "x"}), "1 and x")
        with self.assertRaises(ex.ExportError):
            ex.render("{{a}} and {{c}}", {"a": 1})


@needs_frozen_documents
class FixtureDocuments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = workspace()
        cls.out = Path(tempfile.mkdtemp())
        cls.bundle = build(cls.out, cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)
        shutil.rmtree(cls.out)

    def text(self, name):
        return (self.bundle / name).read_text(encoding="utf-8")

    def test_no_placeholder_left(self):
        for name in ex.DOCUMENTS.values():
            self.assertNotIn("{{", self.text(name), name)

    def test_numbers_come_from_the_tables(self):
        card = self.text("DATA_CARD.md")
        # fixture: 8 steps, Lee2020/P1/S2 flagged; 6 connections, none flagged
        self.assertIn("1 of 8 steps and 0 of 6 connections", card)
        # candidate routes: C0001 reference list, C0002 search, C0003 both
        self.assertIn("1 candidates came only from the reference lists, 1 only from the searches", card)
        self.assertIn("0.900 for the unit operation", card)

    def test_citation_and_licence_name_the_authors(self):
        self.assertIn('family-names: "Doe"', self.text("CITATION.cff"))
        self.assertIn("Copyright (c) 2026 Jane Doe", self.text("LICENSE-CODE"))

    def test_dictionary_covers_every_column_of_every_csv(self):
        with (self.bundle / "data_dictionary.csv").open(encoding="utf-8") as f:
            described = {(r["object"], r["column"]) for r in csv.DictReader(f)}
        sources = {f"core/{t}.csv": t for t in ex.release_tables(ex.new_release_db())}
        sources.update({f"modes/{m}/{n}": s for m, files in ex.MODE_FILES.items() for n, s in files.items()})
        sources.update({"modes/benchmark/split.csv": "benchmark_split",
                        "modes/benchmark/items_module_type.csv": "benchmark_item"})
        for path, obj in sources.items():
            with (self.bundle / path).open(encoding="utf-8") as f:
                header = next(csv.reader(f))
            for col in header:
                self.assertIn((obj, col), described, path)


@needs_frozen_documents
class Refusals(unittest.TestCase):
    def test_candidate_sources_must_match_the_candidates(self):
        db = fixture_db()
        meta = info(db)
        rel = ex.build_release_db(db, meta, workspace(), versions=[], additions=[], evidence=evidence())
        other = Path(tempfile.mkdtemp()) / "candidates.csv"
        other.write_text("cand_id,source_ids\nC0001,S0001\n", encoding="utf-8")
        with self.assertRaises(ex.ExportError):
            ex.document_values(rel, db, meta, other, quality_evidence())
        with self.assertRaises(ex.ExportError):
            ex.document_values(rel, db, dict(meta, authors=[]), candidate_sources(), quality_evidence())
        # the shipped instruction file must be the one recorded with the codings
        db.execute("UPDATE coding SET prompt_sha256 = ? WHERE role = 'extractor_a'", ("3" * 64,))
        with self.assertRaises(ex.ExportError):
            ex.document_values(rel, db, meta, candidate_sources(), quality_evidence())


class CandidatesAndIdentities(unittest.TestCase):
    ADD = {"cand_id": "C0003", "doi": "10.1000/REV2024", "title": "A review of robots, from its DOI record",
           "venue": "", "year": "", "source": "test"}

    def test_addition_fills_an_empty_title_only(self):
        db = build_fixture()
        db.execute("UPDATE candidate SET title = NULL WHERE cand_id = 'C0003'")
        rows = {r[0]: r for r in ex.candidate_rows(db, [self.ADD])}
        self.assertEqual(rows["C0003"][5], "A review of robots, from its DOI record")
        self.assertEqual(rows["C0003"][6], "Rev J")             # the venue was not empty and is kept

    def test_addition_that_would_replace_a_value_or_names_another_doi_fails(self):
        db = build_fixture()                                    # C0003 has a title
        with self.assertRaises(ex.ExportError):
            ex.candidate_rows(db, [self.ADD])
        db.execute("UPDATE candidate SET title = NULL WHERE cand_id = 'C0003'")
        with self.assertRaises(ex.ExportError):
            ex.candidate_rows(db, [dict(self.ADD, doi="10.1000/other")])

    def test_platform_found_in_one_paper_is_named_by_the_paper(self):
        db = build_fixture()
        # move Kim2025/P1 out of the shared group into an identity of its own, as the build names it
        db.execute("INSERT INTO platform_identity VALUES ('Kim2025/P1', 'Kim2025/P1', NULL)")
        db.execute("UPDATE platform_identity_member SET identity_id = 'Kim2025/P1', rule = 'singleton', "
                   "decided_by = 'build-rule', evidence = NULL WHERE platform_id = 'Kim2025/P1'")
        rel = ex.new_release_db()
        ex.export_core(db, rel, ex.load_definitions(db))
        names = dict(rel.execute("SELECT identity_id, canonical_name FROM platform_identity"))
        self.assertEqual(names["Kim2025/P1"], "Flow Two")       # the platform's name, not its id
        self.assertEqual(names["I001"], "Robot One")            # Lee2020's group keeps its name

    def test_release_table_has_no_internal_schema_label(self):
        cols = [c[1] for c in ex.new_release_db().execute("PRAGMA table_info(release)")]
        self.assertNotIn("source_schema_version", cols)


@needs_frozen_documents
class ZenodoDoi(unittest.TestCase):
    def setUp(self):
        self.db = fixture_db()
        self.meta = info(self.db)
        self.rel = ex.build_release_db(self.db, self.meta, workspace(), versions=[], additions=[], evidence=evidence())

    def values(self, doi):
        return ex.document_values(self.rel, self.db, dict(self.meta, zenodo_doi=doi), candidate_sources(),
                                  quality_evidence())

    def test_doi_appears_in_citation_and_readme_only_when_given(self):
        cff = (ex.TEMPLATES / "CITATION.cff").read_text(encoding="utf-8")
        self.assertNotIn("doi:", ex.render(cff, self.values(None)))
        with_doi = self.values("10.5281/zenodo.1234567")
        self.assertIn('doi: "10.5281/zenodo.1234567"\nauthors:', ex.render(cff, with_doi))
        self.assertIn("The DOI of this version is 10.5281/zenodo.1234567", with_doi["doi_sentence"])

    def test_malformed_doi_fails(self):
        with self.assertRaises(ex.ExportError):
            self.values("zenodo 1234567")


class Protocol(unittest.TestCase):
    @needs_frozen_documents
    def test_shipped_protocol_files(self):
        root, out = workspace(), Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        self.addCleanup(shutil.rmtree, out)
        bundle = build(out, root)
        for name, source in (("prompt-v1.md", ex.PROTOCOL_PROMPT), ("taxonomy-v1.json", ex.PROTOCOL_TAXONOMY),
                             ("coding-guideline.md", ex.GUIDELINE_TRANSLATION)):
            self.assertEqual((bundle / "protocol" / name).read_bytes(), source.read_bytes(), name)
        readme = (bundle / "protocol" / "README.md").read_text(encoding="utf-8")
        self.assertIn(hashlib.sha256(ex.GUIDELINE_ORIGINAL.read_bytes()).hexdigest(), readme)

    def test_no_korean_text_in_the_release_files(self):
        hangul = re.compile("[\\uac00-\\ud7a3]")
        for path in [ex.GUIDELINE_TRANSLATION, *ex.TEMPLATES.iterdir(), ex.RELEASE_SCHEMA]:
            self.assertIsNone(hangul.search(path.read_text(encoding="utf-8")), path)


@unittest.skipUnless(ex.INTERNAL_DB.exists() and (ex.ROOT / ex.CODER_INPUTS).exists(), "workspace files not present")
class RecordedBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        meta = json.loads(ex.RELEASE_INFO.read_text(encoding="utf-8"))
        db = ex.open_internal()
        rel = ex.build_release_db(db, meta)
        cls.values = ex.document_values(rel, db, meta)

    def test_recorded_values(self):
        v = self.values
        self.assertEqual((v["n_cand_seed_only"], v["n_cand_keyword_only"], v["n_cand_both"]), (857, 1231, 84))
        self.assertEqual((v["n_reference_papers"], v["n_reference_recent"], v["n_reference_older"]), (30, 13, 17))
        self.assertEqual((v["f1_unit_operation"], v["f1_module_type"], v["f1_transfer_mode"]),
                         ("0.905", "0.898", "0.891"))
        self.assertEqual((v["module_baseline"], v["module_reference"], v["transfer_low"]),
                         ("0.6681", "0.6881", "+0.0172"))
        self.assertEqual((v["n_eligible"], v["n_ineligible"], v["n_fulltext"]), (238, 231, 469))


if __name__ == "__main__":
    unittest.main()
