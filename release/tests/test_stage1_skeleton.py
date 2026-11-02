"""Stage 1: the test fixture is a valid internal build, the release schema loads, and the source-build digest is
computed the way db/build_db.py computes it.
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


class Fixture(unittest.TestCase):
    def test_fixture_is_a_valid_internal_build(self):
        db = build_fixture()
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        # one DB-record coding per paper (extractor_a with the frozen prompt)
        self.assertEqual(db.execute("SELECT paper_id FROM db_record_coding ORDER BY 1").fetchall(),
                         [("Kim2025",), ("Lee2020",)])
        # Lee2020: 5 steps, Kim2025: 3 steps (record codings only)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM v_step").fetchone()[0], 8)


class ReleaseSchema(unittest.TestCase):
    def test_release_schema_loads_empty(self):
        rel = ex.new_release_db()
        tables = {r[0] for r in rel.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("benchmark_item", tables)
        self.assertNotIn("coding", tables)
        self.assertEqual(rel.execute("PRAGMA foreign_keys").fetchone()[0], 1)


class SourceDigest(unittest.TestCase):
    def test_digest_ignores_the_db_build_row(self):
        a, b = build_fixture(), build_fixture()
        b.execute("UPDATE db_build SET built_at = '2030-01-01T00:00:00+09:00'")
        self.assertEqual(ex.internal_digest(a), ex.internal_digest(b))

    def test_digest_changes_with_content(self):
        a, b = build_fixture(), build_fixture()
        b.execute("UPDATE platform SET name = 'Other' WHERE platform_id = 'Lee2020/P1'")
        self.assertNotEqual(ex.internal_digest(a), ex.internal_digest(b))

    @unittest.skipUnless(ex.INTERNAL_DB.exists(), "internal build not present")
    def test_recorded_build_digest(self):
        # db/build-manifest.json and Evidence evi-obs-processbuild-20261102-112453 record this digest (the
        # 237-paper build of release 1.1.0, Snapp2023 removed; release 1.0.0 was exported from 6bc13fac...,
        # evi-obs-dbbuild-20261025-131159)
        db = ex.open_internal()
        self.assertEqual(ex.internal_digest(db),
                         "57b39af53554a4b7dbccbdfebfc3b254f88f6af050a378b3cb1f9435deeaa08a")

    @unittest.skipUnless(ex.INTERNAL_DB.exists(), "internal build not present")
    def test_internal_build_opens_read_only(self):
        db = ex.open_internal()
        with self.assertRaises(Exception):
            db.execute("CREATE TABLE should_fail (x)")


if __name__ == "__main__":
    unittest.main()
