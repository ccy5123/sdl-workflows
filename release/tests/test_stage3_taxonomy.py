"""Stage 3: every taxonomy class and exclusion reason gets its definition from release/inputs/definitions.csv, and
the frozen correspondence tables are read cell by cell into long-form rows, with override rows for the cells the
reading rules do not cover.
Run from the workspace root: python3 -m unittest discover release/tests -v
"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import export_release as ex  # noqa: E402
from fixture import build_fixture, needs_frozen_documents  # noqa: E402


def rewritten(path, edit):
    """A temporary copy of a CSV input with its rows passed through edit(rows)."""
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    tmp = Path(tempfile.mkdtemp()) / path.name
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(edit(rows))
    return tmp


class CellRules(unittest.TestCase):
    """Cells in the frozen document's Korean wording, built from the module's escaped constants; the English notes
    stand in for the Korean notes, which the rules ignore except for their first upper/lower word."""
    UP, LOW, P = ex.KO_UPPER, ex.KO_LOWER, ex.PARTIAL
    KO_OF = "\uc758"                                        # Korean possessive particle

    def test_no_match(self):
        self.assertEqual(ex.correspondence_cell(ex.NO_MATCH), [("none", "none")])

    def test_exact_cell_splits_targets_and_drops_notes(self):
        self.assertEqual(ex.correspondence_cell("pump; valve (liquid backbone)"),
                         [("pump", "exact"), ("valve", "exact")])
        self.assertEqual(ex.correspondence_cell("stir (named as a substep of Recrystallize)"), [("stir", "exact")])
        self.assertEqual(ex.correspondence_cell("Structural characterization (task; technique: XRD)"),
                         [("Structural characterization", "exact")])

    def test_partial_cell_takes_its_direction_from_the_note(self):
        self.assertEqual(ex.correspondence_cell(f"{self.P}add ({self.UP}; liquid and solid not separated)"),
                         [("add", "broader")])
        self.assertEqual(ex.correspondence_cell(f"{self.P}Recrystallize (one purification method, {self.LOW})"),
                         [("Recrystallize", "narrower")])
        # the first segment that starts with the upper or lower word decides
        self.assertEqual(ex.correspondence_cell(f"{self.P}material synthesis ({self.UP}; {self.LOW} task e.g. "
                                                "polymerization)"), [("material synthesis", "broader")])

    def test_cells_outside_the_rules_are_not_read(self):
        for cell in (f"{self.P}fraction collector",
                     f"{self.P}heat (the class above heat treatment, ending in {self.UP})",
                     f"{self.P}analysis task{self.KO_OF} technique (e.g. neural network)"):
            self.assertIsNone(ex.correspondence_cell(cell), cell)

    def test_evidence_column(self):
        self.assertEqual(ex.correspondence_sources(f"X: Mehr2020 ; p.9 ; {ex.KO_MAIN_TEXT} / L: Leong2022 ; p.2 ; "
                                                   "Proposal"),
                         {"XDL": "Mehr2020 ; p.9 ; main text", "Leong2022": "Leong2022 ; p.2 ; Proposal"})
        self.assertEqual(ex.correspondence_sources("—"), {})
        self.assertIsNone(ex.correspondence_sources("Z: Somebody2020 ; p.1 ; Fig. 1"))
        self.assertIsNone(ex.correspondence_sources("W: Schilling2026 ; p.4 ; \uadf8\ub9bc"))   # untranslated word


class Definitions(unittest.TestCase):
    def test_every_class_and_reason_has_a_definition(self):
        db = build_fixture()
        rel = ex.new_release_db()
        ex.export_core(db, rel, ex.load_definitions(db))
        for table in ex.TAXONOMY_TABLES + ("screening_reason",):
            self.assertEqual(rel.execute(f"SELECT COUNT(*) FROM {table} WHERE TRIM(definition) = ''")
                             .fetchone()[0], 0, table)
        self.assertEqual(rel.execute("SELECT COUNT(*) FROM unit_operation").fetchone()[0], 31)

    def test_missing_extra_or_empty_definition_fails(self):
        edits = (lambda rows: [r for r in rows if r["name"] != "react_flow"],
                 lambda rows: rows + [{"kind": "module_type", "name": "robot_arm", "definition": "A robot arm."}],
                 lambda rows: [dict(r, definition="") if r["name"] == "E_review" else r for r in rows])
        db = build_fixture()
        for edit in edits:
            with self.assertRaises(ex.ExportError):
                ex.load_definitions(db, rewritten(ex.DEFINITIONS, edit))


@needs_frozen_documents
class Correspondence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = build_fixture()
        cls.overrides = ex.load_rows(ex.CORRESPONDENCE_OVERRIDES)
        cls.rel = ex.new_release_db()
        ex.export_correspondence(cls.db, cls.rel, cls.overrides)

    def rows(self, cls, vocabulary):
        return self.rel.execute("SELECT target, match FROM taxonomy_correspondence WHERE class = ? AND vocabulary = ? "
                                "ORDER BY target", (cls, vocabulary)).fetchall()

    def test_row_counts(self):
        self.assertEqual(self.rel.execute("SELECT COUNT(*) FROM taxonomy_correspondence").fetchone()[0], 280)
        self.assertEqual(self.rel.execute("SELECT COUNT(*) FROM taxonomy_correspondence "
                                          "WHERE vocabulary = 'Gottstein2026'").fetchone()[0], 56)

    def test_every_class_has_every_vocabulary(self):
        n = self.rel.execute("SELECT COUNT(*) FROM (SELECT DISTINCT class_kind, class, vocabulary "
                             "FROM taxonomy_correspondence)").fetchone()[0]
        # 30 unit operations x 4 + 21 module types x 5 + 5 transfer modes x 4
        self.assertEqual(n, 30 * 4 + 21 * 5 + 5 * 4)

    def test_cells_read_as_written(self):
        self.assertEqual(self.rows("wash_extract", "XDL"), [("Extract", "exact"), ("Separate", "exact"),
                                                            ("Wash", "exact")])
        self.assertEqual(self.rows("react_flow", "Leong2022"), [("flow reactors", "narrower")])
        self.assertEqual(self.rows("react_thermal", "Leong2022"), [("material synthesis", "broader")])
        self.assertEqual(self.rel.execute("SELECT target, match, source_ref FROM taxonomy_correspondence "
                                          "WHERE class = 'generate_instructions' AND vocabulary = 'XDL'").fetchall(),
                         [("none", "none", "Mehr2020")])

    def test_overrides_fill_the_unread_cells(self):
        self.assertEqual(self.rows("human", "Leong2022"), [("Manual task", "broader"), ("manual tool", "narrower")])

    def test_a_missing_override_fails(self):
        with self.assertRaises(ex.ExportError):
            ex.correspondence_rows(self.db, overrides=[r for r in self.overrides if r["class"] != "anneal"])

    def test_an_override_for_a_readable_cell_fails(self):
        extra = {"class_kind": "unit_operation", "class": "filter", "vocabulary": "XDL", "target": "Filter",
                 "match": "exact", "reason": "test"}
        with self.assertRaises(ex.ExportError):
            ex.correspondence_rows(self.db, overrides=self.overrides + [extra])

    def test_no_korean_text_in_the_rows(self):
        for row in self.rel.execute("SELECT * FROM taxonomy_correspondence"):
            self.assertFalse(any(ex.HANGUL.search(v) for v in row), row)


@unittest.skipUnless(ex.INTERNAL_DB.exists(), "internal build not present")
class RecordedBuild(unittest.TestCase):
    def test_definitions_and_correspondence_cover_the_recorded_taxonomy(self):
        db = ex.open_internal()
        rel = ex.new_release_db()
        ex.export_core(db, rel, ex.load_definitions(db), redactions=ex.load_redactions())
        ex.export_correspondence(db, rel, ex.load_rows(ex.CORRESPONDENCE_OVERRIDES))
        self.assertEqual(rel.execute("SELECT COUNT(*) FROM taxonomy_class WHERE TRIM(definition) = ''")
                         .fetchone()[0], 0)
        self.assertEqual(rel.execute("SELECT COUNT(*) FROM taxonomy_correspondence").fetchone()[0], 280)
        self.assertEqual(rel.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
