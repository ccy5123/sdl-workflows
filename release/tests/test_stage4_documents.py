"""Stage 4: paper_document lists every document the coder read, with its file hash, the version of the main text
and the basis of its page numbers. A temporary workspace holds the files the fixture papers point to.
Run from the workspace root: python3 -m unittest discover release/tests -v
"""
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
from fixture import build_fixture  # noqa: E402


def put(root, rel, data):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workspace():
    """Lee2020 is a database paper (inputs manifest, researcher-supplied main text, a docx supplement and a
    spreadsheet the coder did not get as text); Kim2025 is an sdl-db-01 paper whose main text was downloaded from
    arXiv (paperforge record beside the PDF) and whose supplement is a PDF."""
    root = Path(tempfile.mkdtemp())
    lee = put(root, "collection/db/lee.pdf", "%PDF lee")
    put(root, "collection/db/lee_si.docx", "docx lee")
    put(root, "collection/db/lee_data.xlsx", "xlsx lee")
    put(root, "extraction/db/inputs-manifest.csv",
        "paper_id,cand_id,main_source,si_sources\n"
        "Lee2020,C0001,collection/db/lee.pdf,collection/db/lee_data.xlsx;collection/db/lee_si.docx\n")
    put(root, "collection/db_supplied_match.csv", f"file,sha256,cand_id,doi\nlee.pdf,{lee},C0001,10.1000/LEE2020\n")
    put(root, "extraction/inputs/Lee2020/si_1.txt", "# source file: lee_si.docx\n=== SI1 (docx) ===\ntext\n")
    put(root, "runs/sdl-db-01/literature/pdfs/Kim2025.pdf", "%PDF kim")
    put(root, "runs/sdl-db-01/literature/pdfs/Kim2025.json", json.dumps(
        {"resolution": {"doi": "10.1000/kim2025", "version": "submittedVersion",
                        "pdf_url": "https://arxiv.org/pdf/2501.00001v2"}}))
    put(root, "collection/fulltext_pdfs/supplied/si/C0002/kim_si.pdf", "%PDF kim si")
    put(root, "extraction/inputs/Kim2025/si_1.txt", "# source file: kim_si.pdf\n=== SI1 pdf p.1 ===\ntext\n")
    put_human(root, HUMAN_FILES)
    return root


# Human-intervention extraction of the fixture papers (human-v1.md output format): Lee2020 names a human task
# without a number; Kim2025 states an unattended campaign with a lower-bound run length.
HUMAN_FILES = {
    "Lee2020": {"paper_id": "Lee2020", "coder": "opus-5.5-human", "record_coding": "extraction/db/opus_a/Lee2020.json",
                "human_intervention": "described", "human_intervention_evidence": "main ; pdf p.3 ; §2 ¶1",
                "unassisted_run_length": [], "notes": "a person moves the plate, as the paper says \"by hand every time\""},
    "Kim2025": {"paper_id": "Kim2025", "coder": "opus-5.5-human", "record_coding": "extraction/db/opus_a/Kim2025.json",
                "human_intervention": "none_stated", "human_intervention_evidence": "SI1 ; pdf p.1 ; Table S1",
                "unassisted_run_length": [{"value": 48, "unit": "h", "qualifier": "lower bound, approximately; the whole "
                                           "campaign", "evidence": "main ; pdf p.2 ; §3 ¶2"}],
                "notes": "ran unattended"},
}


def put_human(root, files, record=True):
    """Write the human-intervention files and, if record, a record naming their set digest."""
    for pid, x in files.items():
        put(root, ex.HUMAN_DIR / f"{pid}.json", json.dumps(x, ensure_ascii=False))
    if record:
        digest, n = ex.file_set_digest(root / ex.HUMAN_DIR)
        put(root, ex.HUMAN_RECORD, json.dumps({"result": {"finding": json.dumps({"set_sha256": digest,
                                                                                  "n_files": n})}}))


def documents(root, db=None, versions=()):
    db = db or build_fixture()
    rel = ex.new_release_db()
    ex.export_core(db, rel, ex.load_definitions(db))
    ex.export_documents(db, rel, root, list(versions))
    return rel


class Documents(unittest.TestCase):
    def setUp(self):
        self.root = workspace()
        self.addCleanup(shutil.rmtree, self.root)

    def test_rows(self):
        rel = documents(self.root)
        rows = rel.execute("SELECT paper_id, doc, file_format, version, source_doi, source_url, page_basis "
                           "FROM paper_document ORDER BY 1, 2").fetchall()
        self.assertEqual(rows, [
            ("Kim2025", "SI1", "pdf", None, None, None, "pdf_page"),
            # arXiv download: the preprint's own DOI comes from its URL, not the journal DOI of the record
            ("Kim2025", "main", "pdf", "preprint", "10.48550/arxiv.2501.00001",
             "https://arxiv.org/pdf/2501.00001v2", "pdf_page"),
            ("Lee2020", "SI1", "docx", None, None, None, "si_internal_page"),
            ("Lee2020", "main", "pdf", "journal", "10.1000/lee2020", None, "pdf_page")])
        self.assertEqual(rel.execute("SELECT sha256 FROM paper_document WHERE paper_id = 'Lee2020' AND doc = 'SI1'")
                         .fetchone()[0], hashlib.sha256(b"docx lee").hexdigest())

    def test_first_page_judgment_comes_first(self):
        rel = documents(self.root, versions=[{"paper_id": "Kim2025", "version": "accepted_manuscript",
                                              "source_doi": "", "source_url": "", "basis": "page 1"}])
        self.assertEqual(rel.execute("SELECT version, source_doi FROM paper_document "
                                     "WHERE paper_id = 'Kim2025' AND doc = 'main'").fetchone(),
                         ("accepted_manuscript", None))

    def test_main_text_without_a_version_record_fails(self):
        (self.root / "runs/sdl-db-01/literature/pdfs/Kim2025.json").unlink()
        with self.assertRaises(ex.ExportError):
            documents(self.root)

    def test_supplement_naming_an_unknown_file_fails(self):
        put(self.root, "extraction/inputs/Kim2025/si_1.txt", "# source file: other.pdf\n")
        with self.assertRaises(ex.ExportError):
            documents(self.root)

    def test_version_row_for_an_unknown_paper_fails(self):
        with self.assertRaises(ex.ExportError):
            documents(self.root, versions=[{"paper_id": "Nobody1999", "version": "journal", "source_doi": "",
                                            "source_url": "", "basis": "page 1"}])

    def test_cited_document_without_a_row_fails(self):
        db = build_fixture()
        db.execute("UPDATE step SET ev_doc = 'SI2' WHERE step_id = 'Lee2020/P1/S1'")
        with self.assertRaises(ex.ExportError):
            documents(self.root, db)


class SidecarVersion(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(ex.sidecar_version({"version": "publishedVersion", "doi": "10.1/X", "pdf_url": "u"}),
                         ("journal", "10.1/x", "u"))
        self.assertEqual(ex.sidecar_version({"version": "acceptedVersion", "doi": "10.1/x", "pdf_url": "u"}),
                         ("accepted_manuscript", None, "u"))
        # a repository copy of a preprint has no DOI of its own here
        self.assertEqual(ex.sidecar_version({"version": "submittedVersion", "doi": "10.1/x", "pdf_url": "u"}),
                         ("preprint", None, "u"))
        self.assertEqual(ex.sidecar_version({}), (None, None, None))


@unittest.skipUnless(ex.INTERNAL_DB.exists() and (ex.ROOT / ex.CODER_INPUTS).exists(), "workspace files not present")
class RecordedBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ex.open_internal()
        cls.rel = ex.new_release_db()
        ex.export_core(cls.db, cls.rel, ex.load_definitions(cls.db), redactions=ex.load_redactions(),
                       published=ex.load_rows(ex.PUBLISHED_VERSIONS))
        ex.export_documents(cls.db, cls.rel)

    def test_main_text_versions(self):
        self.assertEqual(self.rel.execute("SELECT version, COUNT(*) FROM paper_document WHERE doc = 'main' "
                                          "GROUP BY 1 ORDER BY 1").fetchall(),
                         [("accepted_manuscript", 6), ("journal", 201), ("preprint", 29), ("repository_copy", 1)])

    def test_supplements(self):
        self.assertEqual(self.rel.execute("SELECT file_format, COUNT(*) FROM paper_document WHERE doc <> 'main' "
                                          "GROUP BY 1 ORDER BY 1").fetchall(), [("docx", 26), ("pdf", 249)])

    def test_items_citing_a_docx_supplement(self):
        n = 0
        for t in ("platform", "module", "step", "connection"):
            n += self.rel.execute(f"SELECT COUNT(*) FROM {t} x JOIN platform p USING (platform_id) "
                                  "JOIN paper_document d ON d.paper_id = p.paper_id AND d.doc = x.ev_doc "
                                  "WHERE d.page_basis = 'si_internal_page'").fetchone()[0]
        self.assertEqual(n, 144)

    def test_journal_rows_carry_the_paper_doi(self):
        self.assertEqual(self.rel.execute("SELECT COUNT(*) FROM paper_document d JOIN paper p USING (paper_id) "
                                          "WHERE d.doc = 'main' AND d.version = 'journal' "
                                          "AND d.source_doi IS NOT LOWER(p.doi)").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
