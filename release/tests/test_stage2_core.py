"""Stage 2: the core tables (literature, papers, platforms, coded items) are transformed from the internal build.
Expected values are worked out from the rows in fixture.py.
Run from the workspace root: python3 -m unittest discover release/tests -v
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import export_release as ex  # noqa: E402
from fixture import build_fixture  # noqa: E402


def export_fixture(db=None):
    db = db or build_fixture()
    rel = ex.new_release_db()
    ex.export_core(db, rel, ex.load_definitions(db))
    return rel


class Literature(unittest.TestCase):
    def setUp(self):
        self.rel = export_fixture()

    def test_html_entities_are_unescaped(self):
        self.assertEqual(self.rel.execute("SELECT venue FROM candidate WHERE cand_id = 'C0001'").fetchone()[0],
                         "Chem & Eng")

    def test_decided_by_is_split_into_actor_and_model(self):
        rows = self.rel.execute("SELECT cand_id, stage, decided_by, model_id FROM screening "
                                "WHERE stage = 'fulltext' ORDER BY cand_id").fetchall()
        # C0001 fulltext by 'researcher'; C0002 fulltext by 'claude-opus-5-5'
        self.assertEqual(rows, [("C0001", "fulltext", "researcher", None),
                                ("C0002", "fulltext", "model", "claude-opus-5-5")])
        # 'session-subagent' names no model: model, NULL
        self.assertEqual(self.rel.execute("SELECT decided_by, model_id FROM screening "
                                          "WHERE cand_id = 'C0003'").fetchone(), ("model", None))

    def test_all_screening_rows_are_kept(self):
        self.assertEqual(self.rel.execute("SELECT COUNT(*) FROM screening").fetchone()[0], 7)

    def test_free_text_reason_becomes_a_code(self):
        db = build_fixture()
        db.execute("UPDATE screening SET decision = 'unobtainable', reason_code = 'unretrievable (web item, no DOI)' "
                   "WHERE cand_id = 'C0003'")
        rel = export_fixture(db)
        self.assertEqual(rel.execute("SELECT reason_code FROM screening WHERE cand_id = 'C0003'").fetchone()[0],
                         "E_unretrievable")

    def test_unknown_reason_or_actor_fails(self):
        for sql in ("UPDATE screening SET reason_code = 'because' WHERE cand_id = 'C0003'",
                    "UPDATE screening SET decided_by = 'someone' WHERE cand_id = 'C0003'"):
            db = build_fixture()
            db.execute(sql)
            with self.assertRaises(ex.ExportError):
                export_fixture(db)


class Papers(unittest.TestCase):
    def setUp(self):
        self.rel = export_fixture()

    def test_paper_columns_come_from_the_record_coding(self):
        self.assertEqual(self.rel.execute("SELECT paper_id, first_public_year, hardware_location, sw_autonomy "
                                          "FROM paper ORDER BY 1").fetchall(),
                         [("Kim2025", 2025, "main", 2), ("Lee2020", 2020, "main", 2)])

    def test_field_tags_keep_their_order(self):
        self.assertEqual(self.rel.execute("SELECT field_tags FROM paper_field_tags WHERE paper_id = 'Lee2020'")
                         .fetchone()[0], "chemistry_synthesis;catalysis")


class PublishedVersions(unittest.TestCase):
    PAPERS = [("Kim2025", "C0002", "10.26434/chemrxiv-2025-x", 2025, "candidate_year", "main", 2, 2),
              ("Lee2020", "C0001", "10.1021/a", 2020, "candidate_year", "main", 2, 2)]

    def row(self, preprint="10.26434/chemrxiv-2025-x", published="10.1039/B"):
        return {"paper_id": "Kim2025", "preprint_doi": preprint, "published_doi": published}

    def test_only_the_doi_changes(self):
        self.assertEqual(ex.published_dois(self.PAPERS, [self.row()]),
                         [("Kim2025", "C0002", "10.1039/b", 2025, "candidate_year", "main", 2, 2), self.PAPERS[1]])

    def test_no_rows_leave_the_papers_as_they_are(self):
        self.assertEqual(ex.published_dois(self.PAPERS), self.PAPERS)

    def test_a_row_that_does_not_match_fails(self):
        for row in (self.row(preprint="10.26434/other"), self.row(published="10.48550/arxiv.1"),
                    self.row(published="10.1021/A"), dict(self.row(), paper_id="Nope2020")):
            with self.assertRaises(ex.ExportError):
                ex.published_dois(self.PAPERS, [row])


class Platforms(unittest.TestCase):
    def setUp(self):
        self.rel = export_fixture()

    def test_rule_a_keeps_only_the_paper_keys(self):
        row = self.rel.execute("SELECT identity_id, identity_rule, reuse_stated_in, reuse_of, shared_group_ref "
                               "FROM platform WHERE platform_id = 'Kim2025/P1'").fetchone()
        self.assertEqual(row, ("I001", "a_stated_reuse", "Kim2025", "Lee2020", None))

    def test_singleton_has_no_identity_details(self):
        row = self.rel.execute("SELECT identity_rule, reuse_stated_in, reuse_of, shared_group_ref "
                               "FROM platform WHERE platform_id = 'Lee2020/P1'").fetchone()
        self.assertEqual(row, ("singleton", None, None, None))

    def test_rule_b_keeps_only_the_group_ids(self):
        db = build_fixture()
        db.execute("UPDATE platform_identity_member SET rule = 'b_name_and_group', decided_by = 'build-rule', "
                   "evidence = 'name ''Robot One'' = ''Robot One''; shared corresponding group A1;A2 (bases x/y)' "
                   "WHERE platform_id = 'Kim2025/P1'")
        rel = export_fixture(db)
        self.assertEqual(rel.execute("SELECT identity_rule, reuse_stated_in, shared_group_ref FROM platform "
                                     "WHERE platform_id = 'Kim2025/P1'").fetchone(),
                         ("b_name_and_group", None, "A1;A2"))

    def test_unparseable_identity_evidence_fails(self):
        db = build_fixture()
        db.execute("UPDATE platform_identity_member SET evidence = 'reused, see Introduction' "
                   "WHERE platform_id = 'Kim2025/P1'")
        with self.assertRaises(ex.ExportError):
            export_fixture(db)

    def test_rule_a_naming_an_unknown_paper_fails(self):
        db = build_fixture()
        db.execute("UPDATE platform_identity_member SET evidence = 'Kim2025 states reuse of Nobody1999: main.txt' "
                   "WHERE platform_id = 'Kim2025/P1'")
        with self.assertRaises(ex.ExportError):
            export_fixture(db)

    def test_no_identity_evidence_text_is_exported(self):
        dump = "\n".join(self.rel.iterdump())
        self.assertNotIn("we reuse the robot", dump)


class Items(unittest.TestCase):
    def setUp(self):
        self.rel = export_fixture()

    def test_only_the_record_coding_is_exported(self):
        # extractor_a only: Lee2020 5 steps + Kim2025 3 steps; 4 + 2 connections; 4 + 3 modules
        counts = [self.rel.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("platform", "module", "step", "step_module", "connection")]
        self.assertEqual(counts, [2, 7, 8, 8, 6])
        # extractor_b coded S2 as 'mix'; the release has extractor_a's 'react_thermal'
        self.assertEqual(self.rel.execute("SELECT unit_operation FROM step WHERE step_id = 'Lee2020/P1/S2'")
                         .fetchone()[0], "react_thermal")

    def test_no_coding_id_column_anywhere(self):
        for (table,) in self.rel.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"):
            cols = [r[1] for r in self.rel.execute(f"PRAGMA table_info({table})")]
            self.assertNotIn("coding_id", cols, table)

    def test_uncertain_marks_the_flagged_items(self):
        self.assertEqual(self.rel.execute("SELECT step_id FROM step WHERE uncertain = 1").fetchall(),
                         [("Lee2020/P1/S2",)])
        self.assertEqual(self.rel.execute("SELECT COUNT(*) FROM connection WHERE uncertain = 1").fetchone()[0], 0)

    def test_integration_mode(self):
        # Lee2020: robot_arm_gantry + human_transfer -> mixed; Kim2025: fixed_tubing only
        self.assertEqual(self.rel.execute("SELECT paper_id, integration_mode FROM paper_integration ORDER BY 1")
                         .fetchall(), [("Kim2025", "fixed_tubing"), ("Lee2020", "mixed")])

    def test_foreign_keys_hold(self):
        self.assertEqual(self.rel.execute("PRAGMA foreign_key_check").fetchall(), [])


class QuotationCheck(unittest.TestCase):
    def test_primes_and_inch_marks_are_not_quotations(self):
        for text in ("plate reader 4'-model", "4'-bromo and 4'-chloroacetophenone mixed overnight",
                     'tee-pieces 1/16" and 1/8" PTFE tubing in a loop'):
            self.assertEqual(ex.quotations(text), [], text)

    def test_a_quoted_passage_is_found(self):
        self.assertEqual(ex.quotations('robot named "the self-driving lab of the future"'),
                         ['"the self-driving lab of the future"'])
        self.assertEqual(ex.quotations("called 'a very long quoted name' here"), ["'a very long quoted name'"])
        self.assertEqual(ex.quotations("short 'name' only"), [])

    def test_export_fails_on_a_quotation_in_a_free_text_column(self):
        db = build_fixture()
        db.execute("""UPDATE platform SET campaigns = 'as the authors put it, "we optimised the yield twice"' """
                   "WHERE platform_id = 'Lee2020/P1'")
        with self.assertRaises(ex.ExportError):
            export_fixture(db)

    def test_a_redaction_row_fixes_the_column(self):
        db = build_fixture()
        db.execute("""UPDATE platform SET campaigns = 'as the authors put it, "we optimised the yield twice"' """
                   "WHERE platform_id = 'Lee2020/P1'")
        rel = ex.new_release_db()
        ex.export_core(db, rel, ex.load_definitions(db),
                       redactions=[{"table": "platform", "key": "Lee2020/P1", "column": "campaigns",
                                    "value": "two yield optimisations", "reason": "quotation"}])
        self.assertEqual(rel.execute("SELECT campaigns FROM platform WHERE platform_id = 'Lee2020/P1'")
                         .fetchone()[0], "two yield optimisations")


@unittest.skipUnless(ex.INTERNAL_DB.exists(), "internal build not present")
class RecordedBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ex.open_internal()
        cls.rel = ex.new_release_db()
        ex.export_core(cls.db, cls.rel, ex.load_definitions(cls.db), redactions=ex.load_redactions())

    def count(self, rel_sql, db_sql=None):
        return self.rel.execute(rel_sql).fetchone()[0], (self.db.execute(db_sql).fetchone()[0] if db_sql else None)

    def test_foreign_keys_hold(self):
        self.assertEqual(self.rel.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_row_counts_match_the_internal_views(self):
        self.assertEqual(self.count("SELECT COUNT(*) FROM paper")[0], 237)
        self.assertEqual(self.count("SELECT COUNT(*) FROM step")[0], 2610)
        self.assertEqual(self.count("SELECT COUNT(*) FROM connection")[0], 1681)
        for table in ("platform", "module", "step_module"):
            rel_n, db_n = self.count(f"SELECT COUNT(*) FROM {table}",
                                     f"SELECT COUNT(*) FROM {table} JOIN db_record_coding USING (coding_id)")
            self.assertEqual(rel_n, db_n, table)
        for table in ("candidate", "screening", "paper_version_link", "platform_identity"):
            self.assertEqual(*self.count(f"SELECT COUNT(*) FROM {table}", f"SELECT COUNT(*) FROM {table}"))

    def test_uncertain_counts_match_the_flags(self):
        self.assertEqual(self.count("SELECT SUM(uncertain) FROM step")[0], 340)
        self.assertEqual(self.count("SELECT SUM(uncertain) FROM connection")[0], 155)

    def test_integration_modes_match_the_internal_view(self):
        sql = "SELECT integration_mode, COUNT(*) FROM {} GROUP BY 1 ORDER BY 1"
        self.assertEqual(self.rel.execute(sql.format("paper_integration")).fetchall(),
                         self.db.execute(sql.format("v_paper_integration")).fetchall())

    def test_screening_actors(self):
        self.assertEqual(self.rel.execute("SELECT decided_by, model_id, COUNT(*) FROM screening "
                                          "GROUP BY 1, 2 ORDER BY 1, 2").fetchall(),
                         [("model", None, 2926), ("model", "claude-opus-5-5", 313), ("researcher", None, 59)])

    def test_no_html_entities_left(self):
        n = self.rel.execute("SELECT COUNT(*) FROM candidate WHERE title LIKE '%&%;%' OR venue LIKE '%&%;%' "
                             "OR first_author LIKE '%&%;%'").fetchone()[0]
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
