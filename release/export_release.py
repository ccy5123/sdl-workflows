"""Export the sdl-workflows public release from one recorded internal build.

Reads db/sdl-db.sqlite read-only, transforms it into the release tables (release/schema/release-schema.sql) in an
in-memory database, and writes the release bundle to release/out/. The release is a build artefact: nothing in it
is edited by hand, and hand-written inputs live in release/inputs/. Design: drafts/dataset/schema-design.md;
plan: drafts/dataset/export-plan.md.
"""
import csv
import hashlib
import html
import json
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INTERNAL_DB = ROOT / "db" / "sdl-db.sqlite"
RELEASE_SCHEMA = HERE / "schema" / "release-schema.sql"
INPUTS = HERE / "inputs"
REDACTIONS = INPUTS / "redactions.csv"
DEFINITIONS = INPUTS / "definitions.csv"
BIB_ADDITIONS = INPUTS / "bibliographic-additions.csv"
CORRESPONDENCE = ROOT / "protocol" / "taxonomy-correspondence.md"
GOTTSTEIN = INPUTS / "correspondence-gottstein2026.csv"
CORRESPONDENCE_OVERRIDES = INPUTS / "correspondence-overrides.csv"
DOCUMENT_VERSIONS = INPUTS / "document-versions.csv"
SDL_DB_02 = ROOT / "analysis" / "sdl-db-02"
BENCHMARK_EVIDENCE = ROOT / "release" / "inputs" / "benchmark-reference.json"


def open_internal(path=INTERNAL_DB):
    """Open the internal build read-only."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def internal_digest(db):
    """Content digest as db/build_db.py computes it: sha256 of the SQL dump without the db_build row."""
    # iterdump on the connection itself: Connection.backup() retries forever while that connection holds an
    # uncommitted write, and the dump text is the same either way.
    dump = "\n".join(line for line in db.iterdump() if not line.startswith('INSERT INTO "db_build"'))
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


def new_release_db():
    """An empty in-memory database with the release schema."""
    rel = sqlite3.connect(":memory:")
    rel.execute("PRAGMA foreign_keys = ON")
    rel.executescript(RELEASE_SCHEMA.read_text(encoding="utf-8"))
    return rel


# Core tables -----------------------------------------------------------------------------------------------
# Exclusion reasons: the 11 codes of drafts/sdl-db-02/elig/instructions.md, plus the researcher's own reading and
# the one free-text reason of the internal record, which the export turns into a code.
KNOWN_REASONS = {"E_not_paper", "E_review", "E_off_topic", "E_duplicate_version", "E_computational",
                 "E_software_only", "E_no_robot", "E_measure_only", "E_open_loop", "E_not_closed",
                 "E_hardware_not_described", "E_researcher_read", "E_unretrievable"}
REASON_REWRITES = {"unretrievable (web item, no DOI)": "E_unretrievable"}

# Free-text columns that must carry no quotation, with the key column a redaction row addresses them by.
FREE_TEXT = {"platform": ("platform_id", ("name", "campaigns")),
             "module": ("module_id", ("name_in_paper", "unmapped_note")),
             "step": ("step_id", ("unmapped_note",)),
             "connection": ("edge_id", ("unmapped_note",))}
TAXONOMY_TABLES = ("uo_family", "unit_operation", "module_type", "transfer_mode", "field_tag")

RULE_A = re.compile(r"\s*(\S+) states reuse of (\S+?)[:,;. ]")
RULE_B = re.compile(r"shared corresponding group (\S+)")
# A quote mark right after a digit is a prime or an inch mark (4'-bromo..., 1/16" tubing), not a quotation mark.
AFTER_DIGIT = re.compile(r"(?<=\d)['\"]")
QUOTATION = re.compile("(?<!\\w)\"[^\"]{12,}\"(?!\\w)|(?<!\\w)'.{12,}?'(?!\\w)"
                       "|“[^”]{12,}”|‘[^’]{12,}’")


class ExportError(Exception):
    """The internal build holds something the export has no rule for; nothing is written."""


def quotations(text):
    """Quoted passages of 12 or more characters in text."""
    return QUOTATION.findall(AFTER_DIGIT.sub("", text or ""))


def screening_reason(code):
    code = REASON_REWRITES.get(code, code)
    if code is not None and code not in KNOWN_REASONS:
        raise ExportError(f"screening reason without a code: {code!r}")
    return code


def screening_actor(decided_by):
    """Internal decided_by -> (decided_by, model_id). 'session-subagent' was a model the record does not name."""
    if decided_by == "researcher":
        return "researcher", None
    if decided_by == "session-subagent":
        return "model", None
    if decided_by.startswith("claude-"):
        return "model", decided_by
    raise ExportError(f"unknown screening actor: {decided_by!r}")


def identity_details(rule, evidence, papers):
    """(reuse_stated_in, reuse_of, shared_group_ref) from the identity evidence; the evidence text itself is dropped."""
    if rule == "singleton":
        return None, None, None
    if rule == "a_stated_reuse":
        m = RULE_A.match(evidence or "")
        if not m or not {m.group(1), m.group(2)} <= papers:
            raise ExportError(f"rule a evidence names no two known papers: {evidence!r}")
        return m.group(1), m.group(2), None
    m = RULE_B.search(evidence or "")
    if rule == "b_name_and_group" and m:
        return None, None, m.group(1)
    raise ExportError(f"identity evidence not understood ({rule}): {evidence!r}")


def taxonomy_classes(db, table):
    return [name for (name,) in db.execute(f"SELECT {'family' if table == 'uo_family' else table} FROM {table}")]


def load_definitions(db, path=DEFINITIONS):
    """(kind, name) -> definition from release/inputs/definitions.csv: exactly one non-empty definition for every
    taxonomy class of db and every exclusion reason code, and nothing else."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    defs = {}
    for r in rows:
        key = (r["kind"], r["name"])
        if key in defs or not r["definition"].strip():
            raise ExportError(f"definition duplicated or empty: {key}")
        defs[key] = r["definition"].strip()
    expected = {(t, n) for t in TAXONOMY_TABLES for n in taxonomy_classes(db, t)}
    expected |= {("screening_reason", code) for code in KNOWN_REASONS}
    if defs.keys() != expected:
        raise ExportError(f"definitions missing: {sorted(expected - defs.keys())}; "
                          f"without a class: {sorted(defs.keys() - expected)}")
    return defs


def load_rows(path):
    """Rows of a hand-written input CSV; a missing file has none."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_redactions(path=REDACTIONS):
    return load_rows(path)


def definition(defs, kind, name):
    if (kind, name) not in defs:
        raise ExportError(f"no definition for {kind} {name!r}")
    return defs[(kind, name)]


def candidate_rows(db, additions=()):
    """Candidate rows with HTML entities unescaped and empty title, venue or year filled from the DOI records in
    release/inputs/bibliographic-additions.csv. An addition for a field that is not empty, or whose DOI differs from
    the candidate's, fails the export."""
    def unescape(s):
        return html.unescape(s) if s is not None else None

    rows = {c: [c, doi, ax, unescape(au), yr, unescape(ti), unescape(ve)] for c, doi, ax, au, yr, ti, ve in db.execute(
        "SELECT cand_id, doi, arxiv_id, first_author, year, title, venue FROM candidate ORDER BY cand_id")}
    for a in additions:
        row = rows.get(a["cand_id"])
        if row is None or (row[1] or "").lower() != a["doi"].lower():
            raise ExportError(f"bibliographic addition does not match a candidate and its DOI: {a}")
        for field, i, value in (("title", 5, a["title"]), ("venue", 6, a["venue"]),
                                ("year", 4, int(a["year"]) if a["year"] else None)):
            if value in ("", None):
                continue
            if row[i] not in (None, ""):
                raise ExportError(f"{a['cand_id']}: {field} is not empty, the addition would replace it")
            row[i] = value
    return [tuple(r) for r in rows.values()]


def export_core(db, rel, defs, redactions=(), additions=()):
    """Fill the release taxonomy, literature, paper, platform and item tables from the DB-record coding of db."""
    def ins(table, rows):
        if rows:
            rel.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)

    def q(sql):
        return db.execute(sql).fetchall()

    ins("uo_family", [(f, definition(defs, "uo_family", f)) for (f,) in q("SELECT family FROM uo_family")])
    ins("unit_operation", [(u, f, definition(defs, "unit_operation", u))
                           for u, f in q("SELECT unit_operation, family FROM unit_operation")])
    ins("module_type", [(m, definition(defs, "module_type", m)) for (m,) in q("SELECT module_type FROM module_type")])
    ins("transfer_mode", [(t, mat, definition(defs, "transfer_mode", t))
                          for t, mat in q("SELECT transfer_mode, is_material FROM transfer_mode")])
    ins("field_tag", [(t, definition(defs, "field_tag", t)) for (t,) in q("SELECT field_tag FROM field_tag")])

    ins("candidate", candidate_rows(db, additions))
    screening = [(c, st, rd, dec, screening_reason(rc), *screening_actor(by))
                 for c, st, rd, dec, rc, by in
                 q("SELECT cand_id, stage, round, decision, reason_code, decided_by FROM screening")]
    used = sorted({row[4] for row in screening if row[4] is not None})
    ins("screening_reason", [(code, definition(defs, "screening_reason", code)) for code in used])
    ins("screening", screening)
    ins("paper_version_link", q("SELECT cand_id, other_cand_id, relation FROM paper_version_link"))

    papers = q("SELECT p.paper_id, p.cand_id, p.doi, p.first_public_year, p.year_basis, "
               "c.hardware_location, c.sw_autonomy, c.hw_autonomy "
               "FROM paper p JOIN db_record_coding r USING (paper_id) JOIN coding c ON c.coding_id = r.coding_id")
    if len(papers) != q("SELECT COUNT(*) FROM paper")[0][0]:
        raise ExportError("a paper has no DB-record coding")
    ins("paper", papers)
    ins("paper_field_tag", q("SELECT r.paper_id, t.field_tag, t.position FROM coding_field_tag t "
                             "JOIN db_record_coding r USING (coding_id)"))

    paper_ids = {p[0] for p in papers}
    ins("platform_identity", q("SELECT identity_id, canonical_name, group_ref FROM platform_identity"))
    platforms = []
    for (pid, paper, name, ci, camp, idn, rule, evidence, doc, page, loc) in q(
            "SELECT p.platform_id, r.paper_id, p.name, p.commercial_integrated, p.campaigns, m.identity_id, m.rule, "
            "m.evidence, p.ev_doc, p.ev_page, p.ev_locator FROM platform p JOIN db_record_coding r USING (coding_id) "
            "LEFT JOIN platform_identity_member m USING (coding_id, platform_id)"):
        if idn is None:
            raise ExportError(f"platform without an identity: {pid}")
        platforms.append((pid, paper, name, ci, camp, idn, rule, *identity_details(rule, evidence, paper_ids),
                          doc, page, loc))
    ins("platform", platforms)
    # The internal build names a platform found in one paper by its platform id; the release gives it the name the
    # paper uses (NULL if none), so that canonical_name always holds a name.
    rel.execute("UPDATE platform_identity SET canonical_name = (SELECT NULLIF(p.name, '') FROM platform p "
                "WHERE p.identity_id = platform_identity.identity_id) WHERE identity_id IN (SELECT identity_id "
                "FROM platform GROUP BY identity_id HAVING COUNT(*) = 1 AND MAX(identity_rule) = 'singleton')")

    record = "JOIN db_record_coding r USING (coding_id)"
    flagged = "EXISTS (SELECT 1 FROM item_flag f WHERE f.coding_id = x.coding_id AND f.item_id = x.{})"
    ins("module", q(f"SELECT module_id, platform_id, module_type, name_in_paper, on_platform, unmapped_note, "
                    f"ev_doc, ev_page, ev_locator FROM module x {record}"))
    ins("step", q(f"SELECT step_id, platform_id, step_order, unit_operation, performed_by, unmapped_note, "
                  f"{flagged.format('step_id')}, ev_doc, ev_page, ev_locator FROM step x {record}"))
    ins("step_module", q(f"SELECT step_id, module_id, position FROM step_module x {record}"))
    ins("connection", q(f"SELECT edge_id, platform_id, from_module, to_module, transfer_mode, stated, unmapped_note, "
                        f"{flagged.format('edge_id')}, ev_doc, ev_page, ev_locator FROM connection x {record}"))

    for r in redactions:
        if r["table"] not in FREE_TEXT or r["column"] not in FREE_TEXT[r["table"]][1]:
            raise ExportError(f"redaction outside the free-text columns: {r}")
        key = FREE_TEXT[r["table"]][0]
        n = rel.execute(f"UPDATE {r['table']} SET {r['column']} = ? WHERE {key} = ?", (r["value"], r["key"])).rowcount
        if n != 1:
            raise ExportError(f"redaction matches {n} rows: {r}")

    found = []
    for table, (key, cols) in FREE_TEXT.items():
        for col in cols:
            for k, text in rel.execute(f"SELECT {key}, {col} FROM {table} WHERE {col} IS NOT NULL"):
                found += [(table, k, col, s) for s in quotations(text)]
    if found:
        raise ExportError(f"quotations in free-text columns (fix with {REDACTIONS.name}): {found}")
    violations = rel.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise ExportError(f"foreign-key violations: {violations[:10]}")


# Taxonomy correspondence -----------------------------------------------------------------------------------
# Tables A-C of the frozen correspondence: our class kind and the vocabulary of each middle column. The first
# column is our class, the last the evidence locations, each prefixed X/W/L/O by vocabulary.
# The frozen document is written in Korean. The Korean strings its tables use are written as escapes so that this
# file stays English; the comment beside each gives its meaning.
KO_TABLE = "\ud45c"                                   # "table" (headings "## Table A." ...)
KO_MAIN_TEXT = "\ubcf8\ubb38"                         # "main text"
KO_LIST = "\ubaa9\ub85d"                              # "list"
NO_MATCH = "\ub300\uc751 \uc5c6\uc74c"                # "no match"
PARTIAL = "\ubd80\ubd84 \ub300\uc751: "               # "partial match: "
KO_UPPER, KO_LOWER = "\uc0c1\uc704", "\ud558\uc704"   # "upper" (broader), "lower" (narrower)
CORRESPONDENCE_TABLES = {f"## {KO_TABLE} A.": ("unit_operation", ("XDL", "WCSO", "Leong2022")),
                         f"## {KO_TABLE} B.": ("module_type", ("XDL", "WCSO", "Leong2022", "OntoLab_SAREF")),
                         f"## {KO_TABLE} C.": ("transfer_mode", ("XDL", "WCSO", "Leong2022"))}
SOURCE_PREFIX = {"X": "XDL", "W": "WCSO", "L": "Leong2022", "O": "OntoLab_SAREF"}
# A 'no match' cell has no evidence location; its row cites the source that was searched.
VOCABULARY_SOURCE = {"XDL": "Mehr2020", "WCSO": "Schilling2026", "Leong2022": "Leong2022", "OntoLab_SAREF": "Bai2024"}
SOURCE_WORDS = ((f"{KO_MAIN_TEXT} action {KO_LIST}", "main text, list of actions"), (KO_MAIN_TEXT, "main text"))
HANGUL = re.compile("[\uac00-\ud7a3]")
DIRECTION = {KO_UPPER: "broader", KO_LOWER: "narrower"}


def split_outside_parens(text, sep):
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += (ch == "(") - (ch == ")")
        if depth == 0 and text.startswith(sep, i):
            parts.append(text[start:i])
            start = i + len(sep)
    return [p.strip() for p in parts + [text[start:]]]


def trailing_note(part):
    """('name', 'note') for 'name (note)', ('name', None) without a note, (None, None) if unbalanced."""
    if not part.endswith(")"):
        return part, None
    depth = 0
    for i in range(len(part) - 1, -1, -1):
        depth += (part[i] == ")") - (part[i] == "(")
        if depth == 0:
            return part[:i].strip(), part[i + 1:-1]
    return None, None


def correspondence_cell(cell):
    """[(target, match)] for one cell of the frozen tables, or None when the cell does not follow that document's
    reading rules: NO_MATCH is no match; 'PARTIAL<classes> (KO_UPPER|KO_LOWER ...)' is broader or narrower, decided
    by the first note segment that starts with KO_UPPER or KO_LOWER; anything else is exact. Targets are split on ';' and the
    note after each class name is dropped."""
    if cell == NO_MATCH:
        return [("none", "none")]
    match = "exact"
    if cell.startswith(PARTIAL):
        cell, match = cell[len(PARTIAL):], None
    targets, notes = [], []
    for part in split_outside_parens(cell, ";"):
        name, note = trailing_note(part)
        if not name or HANGUL.search(name):
            return None
        targets.append(name)
        notes += [note] if note else []
    if match is None:
        words = [seg.split()[0] for note in notes for seg in re.split("[;,]", note) if seg.split()]
        match = next((DIRECTION[w] for w in words if w in DIRECTION), None)
        if match is None:
            return None
    return [(t, match) for t in targets]


def correspondence_sources(cell):
    """vocabulary -> evidence locations from the last column, or None if that column cannot be read."""
    if cell == "—":
        return {}
    out = {}
    for part in split_outside_parens(cell, " / "):
        prefix, sep, refs = part.partition(": ")
        if not sep or prefix not in SOURCE_PREFIX or SOURCE_PREFIX[prefix] in out:
            return None
        for ko, en in SOURCE_WORDS:
            refs = refs.replace(ko, en)
        if HANGUL.search(refs):
            return None
        out[SOURCE_PREFIX[prefix]] = refs
    return out


def correspondence_rows(db, path=CORRESPONDENCE, gottstein=GOTTSTEIN, overrides=()):
    """Correspondence rows (class_kind, class, vocabulary, target, match, source_ref): tables A-C of the frozen
    document read cell by cell, the Gottstein 2026 rows, and override rows that replace the cells the reading rules
    do not cover. Every class except 'unmapped' must have rows for every vocabulary of its kind."""
    over = {}
    for r in overrides:
        over.setdefault((r["class_kind"], r["class"], r["vocabulary"]), []).append((r["target"], r["match"]))
    rows, problems, used = [], [], set()
    lines = path.read_text(encoding="utf-8").splitlines()
    vocabularies = {}
    for heading, (kind, vocabs) in CORRESPONDENCE_TABLES.items():
        vocabularies[kind] = vocabs + ("Gottstein2026",)
        start = next(i for i, line in enumerate(lines) if line.startswith(heading))
        body = []
        for line in lines[start + 1:]:
            if line.startswith("|"):
                body.append(line)
            elif body:
                break
        for line in body[2:]:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != len(vocabs) + 2:
                problems.append((kind, line))
                continue
            cls, sources = cells[0].strip("`"), correspondence_sources(cells[-1])
            if sources is None:
                problems.append((kind, cls, "evidence column", cells[-1]))
                continue
            for vocab, cell in zip(vocabs, cells[1:-1]):
                key = (kind, cls, vocab)
                parsed = correspondence_cell(cell)
                if key in over:
                    if parsed is not None:
                        problems.append((*key, f"override for a cell the rules read: {cell}"))
                    parsed = over[key]
                    used.add(key)
                if parsed is None:
                    problems.append((*key, cell))
                    continue
                for target, match in parsed:
                    source = sources.get(vocab) or (VOCABULARY_SOURCE[vocab] if match == "none" else None)
                    if source is None:
                        problems.append((*key, "no evidence location"))
                    rows.append((kind, cls, vocab, target, match, source))
    if over.keys() - used:
        problems.append(("overrides without a cell", sorted(over.keys() - used)))
    rows += [tuple(r[c] for c in ("class_kind", "class", "vocabulary", "target", "match", "source_ref"))
             for r in load_rows(gottstein)]
    expected = {(kind, c, v) for kind, vocabs in vocabularies.items()
                for c in taxonomy_classes(db, kind) if c != "unmapped" for v in vocabs}
    got = {r[:3] for r in rows}
    if got != expected:
        problems.append(("coverage", "missing", sorted(expected - got), "unknown", sorted(got - expected)))
    if problems:
        raise ExportError("correspondence not read:\n" + "\n".join(map(str, problems)))
    return rows


def export_correspondence(db, rel, overrides=()):
    rel.executemany("INSERT INTO taxonomy_correspondence VALUES (?, ?, ?, ?, ?, ?)",
                    correspondence_rows(db, overrides=overrides))


# Paper documents --------------------------------------------------------------------------------------------
# Where the coder's documents came from, relative to the workspace root. A paper with a row in the database
# inputs manifest was prepared by extraction/prepare_db_inputs.py; the sdl-db-01 papers by prepare_inputs.py and
# prepare_test_inputs.py, from the literature store and the researcher-supplied supplement folders.
CODER_INPUTS = Path("extraction/inputs")
INPUTS_MANIFEST = Path("extraction/db/inputs-manifest.csv")
GOLD_MAIN = Path("runs/sdl-db-01/literature/pdfs")
GOLD_SI = Path("collection/fulltext_pdfs/supplied/si")
SUPPLIED_MATCHES = "collection/*supplied_match.csv"
PREPRINT_DOI = ("10.26434/", "10.48550/", "10.1101/", "10.21203/", "10.20944/", "10.31224/", "10.2139/")
SIDECAR_VERSION = {"publishedVersion": "journal", "acceptedVersion": "accepted_manuscript",
                   "submittedVersion": "preprint"}
ARXIV_PDF = re.compile(r"https?://arxiv\.org/pdf/([^/?#]+?)(?:v\d+)?(?:\.pdf)?$")  # arXiv DOIs carry no version
PAGE_BASIS = {"pdf": "pdf_page", "docx": "si_internal_page"}
SI_HEADER = re.compile(r"# source file: (.+)")


def document_file(path, doc):
    """(file_format, sha256, page_basis) of a document the coder read."""
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in PAGE_BASIS:
        raise ExportError(f"{doc}: no page basis for a .{fmt} file ({path})")
    return fmt, hashlib.sha256(path.read_bytes()).hexdigest(), PAGE_BASIS[fmt]


def sidecar_version(res):
    """(version, source_doi, source_url) from the resolution paperforge recorded beside a downloaded PDF. A
    preprint's own DOI is the arXiv DOI of its URL, or the recorded DOI when that is a preprint DOI."""
    version = SIDECAR_VERSION.get(res.get("version"))
    url, doi = res.get("pdf_url"), (res.get("doi") or "").lower() or None
    if version == "accepted_manuscript":
        doi = None
    elif version == "preprint":
        m = ARXIV_PDF.match(url or "")
        doi = f"10.48550/arxiv.{m.group(1)}" if m else (doi if doi and doi.startswith(PREPRINT_DOI) else None)
    return version, doi, url


def document_rows(db, root=ROOT, versions=None):
    """paper_document rows: each paper's main text and every supplement the coder was given as text; a
    supplement's input file (extraction/inputs/<paper>/si_<k>.txt) names its source file on its first line. The
    main text's version comes, in this order, from the first-page judgment in release/inputs/document-versions.csv,
    from the DOI of a researcher-supplied file (matched by sha256), or from paperforge's download record."""
    versions = {r["paper_id"]: r for r in (load_rows(DOCUMENT_VERSIONS) if versions is None else versions)}
    manifest = {r["paper_id"]: r for r in load_rows(root / INPUTS_MANIFEST)}
    supplied = {}
    for f in sorted(root.glob(SUPPLIED_MATCHES)):
        for r in load_rows(f):
            supplied.setdefault(r["sha256"], set()).add(r["doi"].lower())
    rows = []
    papers = db.execute("SELECT paper_id, cand_id FROM paper ORDER BY paper_id").fetchall()
    for pid, cid in papers:
        m = manifest.get(pid)
        main = root / m["main_source"] if m else root / GOLD_MAIN / f"{pid}.pdf"
        fmt, sha, basis = document_file(main, f"{pid} main")
        if pid in versions:
            v = versions[pid]
            version, doi, url = v["version"], v["source_doi"] or None, v["source_url"] or None
        elif sha in supplied:
            if len(supplied[sha]) != 1:
                raise ExportError(f"{pid}: supplied file matched to several DOIs {sorted(supplied[sha])}")
            (doi,) = supplied[sha]
            version, url = ("preprint" if doi.startswith(PREPRINT_DOI) else "journal"), None
        else:
            side = main.with_suffix(".json")
            res = (json.loads(side.read_text(encoding="utf-8")).get("resolution") or {}) if side.exists() else {}
            version, doi, url = sidecar_version(res)
            if version is None:
                raise ExportError(f"{pid}: no record of the main text's version")
        rows.append((pid, "main", fmt, sha, version, doi, url, basis))

        if m:
            sources = [root / s for s in m["si_sources"].split(";") if s]
        else:
            sources = sorted((root / GOLD_SI / cid).iterdir()) if (root / GOLD_SI / cid).exists() else []
        for si in sorted((root / CODER_INPUTS / pid).glob("si_*.txt"), key=lambda p: int(p.stem[3:])):
            with si.open(encoding="utf-8") as f:
                name = SI_HEADER.fullmatch(f.readline().rstrip("\n"))
            found = [s for s in sources if name and s.name == name.group(1)]
            if len(found) != 1:
                raise ExportError(f"{pid} {si.name}: source file not found once among {[s.name for s in sources]}")
            doc = f"SI{si.stem[3:]}"
            fmt, sha, basis = document_file(found[0], f"{pid} {doc}")
            rows.append((pid, doc, fmt, sha, None, None, None, basis))
    unknown = versions.keys() - {pid for pid, _ in papers}
    if unknown:
        raise ExportError(f"document versions for papers not in the build: {sorted(unknown)}")
    return rows


def export_documents(db, rel, root=ROOT, versions=None):
    """Fill paper_document; every document an exported item cites must have a row."""
    rel.executemany("INSERT INTO paper_document VALUES (?, ?, ?, ?, ?, ?, ?, ?)", document_rows(db, root, versions))
    missing = rel.execute(
        "SELECT DISTINCT p.paper_id, x.ev_doc FROM (SELECT platform_id, ev_doc FROM platform UNION "
        "SELECT platform_id, ev_doc FROM module UNION SELECT platform_id, ev_doc FROM step UNION "
        "SELECT platform_id, ev_doc FROM connection) x JOIN platform p USING (platform_id) "
        "WHERE x.ev_doc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM paper_document d "
        "WHERE d.paper_id = p.paper_id AND d.doc = x.ev_doc)").fetchall()
    if missing:
        raise ExportError(f"cited documents without a paper_document row: {missing[:10]}")


# Benchmark ---------------------------------------------------------------------------------------------------
# chrono2023 is the sdl-db-02 H1 evaluation: items are built by its own code (analysis/sdl-db-02/h1_tool.py) from
# the same build, and the reference values are read from its recorded Evidence, never typed in.
BENCHMARK_ID = "chrono2023"
EXCLUSION_REASON = "used to develop the extraction instructions"
METRIC = ("top-1 accuracy over the test items; 95% interval of a difference by paper-level paired cluster "
          "bootstrap over the test papers (B = 2000, seed 1)")
TASKS = {
    "a": {"task_id": "chrono2023-module_type", "target": "module_type",
          "item_rule": "every step that has a primary module (its first listed module); the label is that "
                       "module's type",
          "inputs": "the paper's first field tag; the step's unit operation and those of the previous and next "
                    "steps of the same platform in step order (START and END at the ends)",
          "baseline_rule": "most frequent module type of the unit operation in the training items; an unseen unit "
                           "operation falls back to the most frequent module type of all training items; ties "
                           "alphabetical",
          "reference_model": "back-off conditional-frequency model (sdl-db-02 H1): the finest context seen in "
                             "training among (unit operation, previous, next, field tag), (unit operation, previous, "
                             "next), (unit operation, field tag), (unit operation), all items; its most frequent "
                             "label, ties by the next coarser context, then alphabetical"},
    "b": {"task_id": "chrono2023-transfer_mode", "target": "transfer_mode",
          "item_rule": "every material connection that attaches to a pair of steps of its platform: the first "
                       "consecutive step pair whose first modules are the connection's source and target modules; "
                       "otherwise the last step on the source module before the first step on the target module, "
                       "and that step; connections that attach to no pair are not items",
          "inputs": "the paper's first field tag; the unit operations and families of the two attached steps",
          "baseline_rule": "most frequent transfer mode of the family pair in the training items; an unseen pair "
                           "falls back to the most frequent transfer mode of all training items; ties alphabetical",
          "reference_model": "back-off conditional-frequency model (sdl-db-02 H1): the finest context seen in "
                             "training among (from unit operation, to unit operation, field tag), (from, to), "
                             "(from family, to family, field tag), (from family, to family), all items; its most "
                             "frequent label, ties by the next coarser context, then alphabetical"},
}


def benchmark_items(db):
    """sdl-db-02's items of the build, from its own loader."""
    sys.path.insert(0, str(SDL_DB_02))
    try:
        from h1_tool import load_items
    finally:
        sys.path.remove(str(SDL_DB_02))
    return load_items(db)[0]


def export_benchmark(db, rel, evidence=BENCHMARK_EVIDENCE):
    """Fill benchmark_split, benchmark_item and benchmark_task. Training papers: first_public_year <= 2023; test
    papers: 2024 or later, except the sdl-db-01 development papers of those years, which are excluded."""
    split = {}
    for pid, era, gold in db.execute("SELECT e.paper_id, e.era, g.gold_set FROM v_era e "
                                     "LEFT JOIN gold_membership g USING (paper_id)"):
        if era is None:
            raise ExportError(f"{pid}: no first public year, no split")
        split[pid] = "excluded" if era == "test" and gold == "dev" else era
    rel.executemany("INSERT INTO benchmark_split VALUES (?, ?, ?, ?)",
                    [(BENCHMARK_ID, p, s, EXCLUSION_REASON if s == "excluded" else None)
                     for p, s in sorted(split.items())])

    rows = []
    for field, items in benchmark_items(db).items():
        task_id = TASKS[field]["task_id"]
        for it in items:
            c = it["ctx"]
            if field == "a":
                ctx = (c[0][0], c[0][1], c[0][2], None, None, None, None)
            else:
                ctx = (None, None, None, c[1][0], c[1][1], c[3][0], c[3][1])
            rows.append((task_id, it["item"], it["paper"], it["platform"], split[it["paper"]], it["y"], it["t"],
                         *ctx, int(it["uncertain"])))

    rec = json.loads(evidence.read_text(encoding="utf-8"))
    for field, task in TASKS.items():
        test = [r for r in rows if r[0] == task["task_id"] and r[4] == "test"]
        n_items, n_papers = len(test), len({r[2] for r in test})
        if n_items != rec[f"{field}_items"]:
            raise ExportError(f"{task['task_id']}: {n_items} test items, the reference values have {rec[field + '_items']}")
        rel.execute(f"INSERT INTO benchmark_task VALUES ({','.join('?' * 15)})",
                    (task["task_id"], BENCHMARK_ID, task["target"], task["item_rule"], task["inputs"], METRIC,
                     task["baseline_rule"], rec[f"{field}_baseline"], task["reference_model"], rec[f"{field}_tool"],
                     *rec[f"{field}_diff_ci95"], n_items, n_papers, rec["recorded_in"]))
    rel.executemany(f"INSERT INTO benchmark_item VALUES ({','.join('?' * 15)})", rows)


def write_benchmark_files(rel, folder):
    """The benchmark folder evaluate.py reads: split.csv, items_<target>.csv, tasks/<task_id>.json."""
    folder = Path(folder)
    (folder / "tasks").mkdir(parents=True, exist_ok=True)

    def write(name, sql, args=()):
        cur = rel.execute(sql, args)
        with (folder / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow([d[0] for d in cur.description])
            w.writerows(["" if v is None else v for v in row] for row in cur)

    write("split.csv", "SELECT * FROM benchmark_split ORDER BY benchmark_id, paper_id")
    cur = rel.execute("SELECT * FROM benchmark_task ORDER BY task_id")
    cols = [d[0] for d in cur.description]
    for row in cur.fetchall():
        task = dict(zip(cols, row))
        write(f"items_{task['target']}.csv", "SELECT * FROM benchmark_item WHERE task_id = ? ORDER BY item_id",
              (task["task_id"],))
        (folder / "tasks" / f"{task['task_id']}.json").write_text(json.dumps(task, indent=1) + "\n",
                                                                   encoding="utf-8")


# Bundle --------------------------------------------------------------------------------------------------------
# Layout: drafts/dataset/schema-design.md section 6. Every file is written in a fixed row order so that two builds
# from the same inputs give the same bytes; the SQLite file is compared by its SQL dump instead.
RELEASE_INFO = INPUTS / "release.json"
OUT = HERE / "out"
SCHEMA_DIR = HERE / "schema"
VOCABULARIES = ("XDL", "WCSO", "Leong2022", "OntoLab_SAREF", "Gottstein2026")
MODE_FILES = {"builder": {"platforms.csv": "builder_platform", "steps.csv": "builder_step",
                          "connections.csv": "builder_connection"},
              "trends": {"papers.csv": "trends_paper", "candidates.csv": "candidate", "screening.csv": "screening",
                         "screening_reasons.csv": "screening_reason"},
              "taxonomy": {"classes.csv": "taxonomy_class"}}


def release_tables(rel):
    return [n for (n,) in rel.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]


def rows_in_order(rel, name):
    """Cursor over a table or view, ordered by every column in turn."""
    n = len(rel.execute(f"SELECT * FROM {name} LIMIT 0").description)
    return rel.execute(f"SELECT * FROM {name} ORDER BY {', '.join(str(i + 1) for i in range(n))}")


def write_csv(path, cur):
    """A query result as UTF-8 CSV; NULL is an empty field."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([d[0] for d in cur.description])
        w.writerows(["" if v is None else v for v in row] for row in cur)


def write_parquet(path, rel, table):
    """A table as Parquet, column types from the declared SQLite types."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    kinds = {"INTEGER": pa.int64(), "REAL": pa.float64()}
    cols = [(name, kinds.get(decl.upper(), pa.string())) for _, name, decl, *_ in rel.execute(f"PRAGMA table_info({table})")]
    rows = rows_in_order(rel, table).fetchall()
    data = {name: pa.array([r[i] for r in rows], type=t) for i, (name, t) in enumerate(cols)}
    pq.write_table(pa.table(data, schema=pa.schema(cols)), path)


def platform_graphs(rel):
    """One document per platform: modules, steps (with their modules in position order) and connections."""
    def ev(r):
        return {"doc": r["ev_doc"], "page": r["ev_page"], "locator": r["ev_locator"]}

    rel.row_factory = sqlite3.Row
    try:
        tags = {p: t.split(";") for p, t in rel.execute("SELECT paper_id, field_tags FROM paper_field_tags")}
        by_platform = defaultdict(lambda: {"modules": [], "steps": [], "connections": []})
        for r in rel.execute("SELECT * FROM module ORDER BY platform_id, CAST(substr(module_id, "
                             "instr(module_id, '/M') + 2) AS INTEGER)"):
            by_platform[r["platform_id"]]["modules"].append(
                {"module_id": r["module_id"], "module_type": r["module_type"], "name_in_paper": r["name_in_paper"],
                 "on_platform": bool(r["on_platform"]), "unmapped_note": r["unmapped_note"], "evidence": ev(r)})
        mods = defaultdict(list)
        for s, m in rel.execute("SELECT step_id, module_id FROM step_module ORDER BY step_id, position"):
            mods[s].append(m)
        for r in rel.execute("SELECT s.*, u.family FROM step s JOIN unit_operation u USING (unit_operation) "
                             "ORDER BY platform_id, step_order"):
            by_platform[r["platform_id"]]["steps"].append(
                {"step_id": r["step_id"], "step_order": r["step_order"], "unit_operation": r["unit_operation"],
                 "family": r["family"], "performed_by": r["performed_by"], "modules": mods[r["step_id"]],
                 "uncertain": bool(r["uncertain"]), "unmapped_note": r["unmapped_note"], "evidence": ev(r)})
        for r in rel.execute("SELECT e.*, t.is_material FROM connection e JOIN transfer_mode t USING (transfer_mode) "
                             "ORDER BY platform_id, CAST(substr(edge_id, instr(edge_id, '/E') + 2) AS INTEGER)"):
            by_platform[r["platform_id"]]["connections"].append(
                {"edge_id": r["edge_id"], "from_module": r["from_module"], "to_module": r["to_module"],
                 "transfer_mode": r["transfer_mode"], "is_material": bool(r["is_material"]),
                 "stated": bool(r["stated"]), "uncertain": bool(r["uncertain"]),
                 "unmapped_note": r["unmapped_note"], "evidence": ev(r)})
        docs = []
        for r in rel.execute("SELECT pl.*, p.doi, p.first_public_year FROM platform pl JOIN paper p USING (paper_id) "
                             "ORDER BY platform_id"):
            docs.append({"platform_id": r["platform_id"], "paper_id": r["paper_id"], "doi": r["doi"],
                         "first_public_year": r["first_public_year"], "field_tags": tags.get(r["paper_id"], []),
                         "name": r["name"], "commercial_integrated": bool(r["commercial_integrated"]),
                         "identity_id": r["identity_id"], "evidence": ev(r), **by_platform[r["platform_id"]]})
        return docs
    finally:
        rel.row_factory = None


def correspondence_wide(rel):
    """One row per class, two columns per vocabulary: 'target (match); ...' and the evidence locations."""
    cells = defaultdict(lambda: defaultdict(list))
    for kind, cls, vocab, target, match, source in rel.execute(
            "SELECT * FROM taxonomy_correspondence ORDER BY class_kind, class, vocabulary, target"):
        cells[(kind, cls)][vocab].append((target, match, source))
    header = ["class_kind", "class"] + [c for v in VOCABULARIES for c in (v, f"{v}_source")]
    rows = []
    for (kind, cls), by_vocab in sorted(cells.items()):
        row = [kind, cls]
        for v in VOCABULARIES:
            entries = by_vocab.get(v, [])
            row.append("; ".join("none" if m == "none" else f"{t} ({m})" for t, m, _ in entries))
            row.append(" | ".join(dict.fromkeys(s for _, _, s in entries)))
        rows.append(row)
    return header, rows


def load_evaluate():
    """The shipped evaluate.py, loaded from its file (it imports nothing from the workspace)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("evaluate", HERE / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sqlite_dump_digest(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return hashlib.sha256("\n".join(db.iterdump()).encode("utf-8")).hexdigest()
    finally:
        db.close()


def build_release_db(db, info, root=ROOT, evidence=BENCHMARK_EVIDENCE, versions=None, additions=None):
    """All release tables in memory, from one internal build whose digest must be the one release.json names."""
    digest = internal_digest(db)
    if digest != info["source_build_digest"]:
        raise ExportError(f"internal build digest {digest} is not the release's {info['source_build_digest']}")
    rel = new_release_db()
    defs = load_definitions(db)
    export_core(db, rel, defs, load_redactions(), load_rows(BIB_ADDITIONS) if additions is None else additions)
    export_correspondence(db, rel, load_rows(CORRESPONDENCE_OVERRIDES))
    export_documents(db, rel, root, versions)
    export_benchmark(db, rel, evidence)
    (taxonomy,) = db.execute("SELECT version FROM taxonomy_version").fetchone()
    rel.execute("INSERT INTO release VALUES (?, ?, ?, ?, ?, ?, ?)",
                (info["release_version"], info["released_on"], digest, taxonomy, info["license"],
                 info["zenodo_doi"], rel.execute("SELECT COUNT(*) FROM paper").fetchone()[0]))
    rel.commit()
    return rel


def write_bundle(rel, info, values, out=OUT):
    """Write sdl-workflows-<version>/ under out and return its path; values fill the documents
    (document_values)."""
    import jsonschema
    bundle = Path(out) / f"sdl-workflows-{info['release_version']}"
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)

    target = sqlite3.connect(bundle / "sdl-workflows.sqlite")
    rel.backup(target)
    target.close()
    for table in release_tables(rel):
        write_csv(bundle / "core" / f"{table}.csv", rows_in_order(rel, table))
        write_parquet(bundle / "core" / f"{table}.parquet", rel, table)
    for mode, files in MODE_FILES.items():
        for name, source in files.items():
            write_csv(bundle / "modes" / mode / name, rows_in_order(rel, source))

    graph_schema = json.loads((SCHEMA_DIR / "platform-graph.schema.json").read_text(encoding="utf-8"))
    with (bundle / "modes" / "builder" / "platform_graphs.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for doc in platform_graphs(rel):
            jsonschema.validate(doc, graph_schema)
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    header, rows = correspondence_wide(rel)
    with (bundle / "modes" / "taxonomy" / "correspondence.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)

    bench = bundle / "modes" / "benchmark"
    write_benchmark_files(rel, bench)
    shutil.copy(HERE / "evaluate.py", bench / "evaluate.py")
    task_schema = json.loads((SCHEMA_DIR / "benchmark-task.schema.json").read_text(encoding="utf-8"))
    evaluate = load_evaluate()
    results = {}
    for path in sorted((bench / "tasks").glob("*.json")):
        jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), task_schema)
        task, result, _ = evaluate.evaluate(bench, path.stem)
        if evaluate.mismatches(task, result):
            raise ExportError(f"evaluate.py does not reproduce {path.stem}: {evaluate.mismatches(task, result)}")
        results[path.stem] = result
    (bench / "reference_results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")

    (bundle / "schema").mkdir()
    for name in ("release-schema.sql", "platform-graph.schema.json", "benchmark-task.schema.json"):
        shutil.copy(SCHEMA_DIR / name, bundle / "schema" / name)
    write_documents(bundle, rel, values)
    write_manifest(bundle)
    return bundle


COLUMN_NOTE = re.compile(r"--\s*@column\s+([\w*]+)\.(\w+):\s*(.+)$")


def ddl_comments(schema_text):
    """{(object, column): description} from the schema text: '-- @column object.column: text' lines ('*' for any
    object) first; otherwise the comment at the end of a column's line, continued by the comment-only lines
    indented to the comment column (20 or more spaces) right after it."""
    notes, explicit, obj, last = {}, {}, None, None
    for line in schema_text.splitlines():
        m = COLUMN_NOTE.search(line)
        if m:
            explicit[(m.group(1), m.group(2))] = m.group(3).strip()
            continue
        start = re.match(r"CREATE (?:TABLE|VIEW) (\w+)", line)
        if start:
            obj, last = start.group(1), None
            continue
        code, _, comment = line.partition("--")
        col = re.match(r"\s+(\w+)\s+(?:TEXT|INTEGER|REAL)\b", code)
        if obj and col and col.group(1).upper() not in ("PRIMARY", "UNIQUE", "CHECK"):
            last = (obj, col.group(1))
            if comment.strip():
                notes[last] = comment.strip()
        elif obj and last and not code.strip() and comment.strip() and len(code) >= 20:
            notes[last] = f"{notes.get(last, '')} {comment.strip()}".strip()
        else:
            last = None
    return {**notes, **explicit}


def data_dictionary(rel, schema_text):
    """Rows (object, kind, column, type, description) for every column of every table and view of the release.
    A view column without its own note takes the description of the one table column of the same name."""
    notes = ddl_comments(schema_text)
    objects = rel.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY type, name")
    objects = objects.fetchall()
    tables = {n for n, t in objects if t == "table"}
    columns = {n: [(c[1], c[2]) for c in rel.execute(f"PRAGMA table_info({n})")] for n, _ in objects}
    by_name = defaultdict(set)
    for t in tables:
        for col, typ in columns[t]:
            if (t, col) in notes or ("*", col) in notes:
                by_name[col].add((typ, notes.get((t, col)) or notes[("*", col)]))
    rows, missing = [], []
    for name, kind in objects:
        for col, typ in columns[name]:
            text = notes.get((name, col)) or notes.get(("*", col))
            if text is None and kind == "view" and len(by_name[col]) == 1:
                typ, text = next(iter(by_name[col]))
            if not text:
                missing.append(f"{name}.{col}")
            rows.append((name, kind, col, typ or "", text))
    if missing:
        raise ExportError(f"columns without a description in release-schema.sql: {missing}")
    return rows


# Documents -------------------------------------------------------------------------------------------------
# README, DATA_CARD and the other documents are templates in release/templates/; every number in them is filled
# from the release tables or a recorded file at build time, never typed into the text.
TEMPLATES = HERE / "templates"
DOCUMENTS = {"README.md": "README.md", "DATA_CARD.md": "DATA_CARD.md", "CHANGELOG.md": "CHANGELOG.md",
             "CITATION.cff": "CITATION.cff", "LICENSE-DATA": "LICENSE-DATA", "LICENSE-CODE": "LICENSE-CODE",
             "simulation-README.md": "modes/simulation/README.md"}
DOCUMENTS["protocol-README.md"] = "protocol/README.md"
# Files the coding followed, shipped unchanged (their hashes must be the ones the build recorded), and the English
# translation of the frozen Korean coding guideline (whose hash must be the one its freeze recorded).
PROTOCOL_PROMPT = ROOT / "extraction" / "prompt-v1.md"
PROTOCOL_TAXONOMY = ROOT / "protocol" / "taxonomy-v1.json"
GUIDELINE_ORIGINAL = ROOT / "protocol" / "coding-guideline.md"
GUIDELINE_FREEZE = ROOT / "protocol" / "evidence_protocol_freeze.json"
GUIDELINE_TRANSLATION = HERE / "protocol" / "coding-guideline.md"
CANDIDATE_SOURCES = ROOT / "collection" / "candidates.csv"
QUALITY_EVIDENCE = ROOT / "runs" / "sdl-db-01" / "evidence" / "evi-exp-h3-20261022-001150.json"
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
ZENODO_DOI = re.compile(r"10\.5281/zenodo\.[0-9]+")


def render(text, values):
    missing = sorted({m for m in PLACEHOLDER.findall(text) if m not in values})
    if missing:
        raise ExportError(f"template values missing: {missing}")
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)


def document_values(rel, db, info, candidates=CANDIDATE_SOURCES, quality=QUALITY_EVIDENCE, additions=None):
    """The values the document templates use."""
    def one(sql, args=()):
        return rel.execute(sql, args).fetchone()[0]

    v = {"version": info["release_version"], "released_on": info["released_on"],
         "source_build_digest": one("SELECT source_build_digest FROM release"),
         "taxonomy_version": one("SELECT taxonomy_version FROM release"),
         "year_min": one("SELECT MIN(first_public_year) FROM paper"),
         "year_max": one("SELECT MAX(first_public_year) FROM paper")}
    for name, sql in {
            "n_papers": "SELECT COUNT(*) FROM paper", "n_platforms": "SELECT COUNT(*) FROM platform",
            "n_modules": "SELECT COUNT(*) FROM module", "n_steps": "SELECT COUNT(*) FROM step",
            "n_connections": "SELECT COUNT(*) FROM connection", "n_candidates": "SELECT COUNT(*) FROM candidate",
            "n_material_connections": "SELECT COUNT(*) FROM connection JOIN transfer_mode USING (transfer_mode) "
                                      "WHERE is_material = 1",
            "n_title": "SELECT COUNT(DISTINCT cand_id) FROM screening WHERE stage = 'title'",
            "n_abstract": "SELECT COUNT(DISTINCT cand_id) FROM screening WHERE stage = 'abstract'",
            "n_fulltext": "SELECT COUNT(DISTINCT cand_id) FROM screening WHERE stage = 'fulltext'",
            "n_eligible": "SELECT COUNT(*) FROM trends_screening_latest WHERE stage = 'fulltext' "
                          "AND decision = 'eligible'",
            "n_ineligible": "SELECT COUNT(*) FROM trends_screening_latest WHERE stage = 'fulltext' "
                            "AND decision = 'ineligible'",
            "n_unobtainable": "SELECT COUNT(*) FROM trends_screening_latest WHERE stage = 'fulltext' "
                              "AND decision = 'unobtainable'",
            "n_decisions": "SELECT COUNT(*) FROM screening",
            "n_decisions_model": "SELECT COUNT(*) FROM screening WHERE decided_by = 'model'",
            "n_decisions_model_named": "SELECT COUNT(*) FROM screening WHERE model_id IS NOT NULL",
            "n_decisions_researcher": "SELECT COUNT(*) FROM screening WHERE decided_by = 'researcher'",
            "n_version_links": "SELECT COUNT(*) FROM paper_version_link",
            "n_si_docs": "SELECT COUNT(*) FROM paper_document WHERE doc <> 'main'",
            "n_platforms_shared": "SELECT COUNT(*) FROM platform WHERE identity_id IN "
                                  "(SELECT identity_id FROM platform GROUP BY 1 HAVING COUNT(*) > 1)",
            "n_identities_shared": "SELECT COUNT(*) FROM (SELECT identity_id FROM platform GROUP BY 1 "
                                   "HAVING COUNT(*) > 1)",
            "n_steps_uncertain": "SELECT COUNT(*) FROM step WHERE uncertain = 1",
            "n_connections_uncertain": "SELECT COUNT(*) FROM connection WHERE uncertain = 1",
            "n_unmapped_steps": "SELECT COUNT(*) FROM step WHERE unit_operation = 'unmapped'",
            "n_unmapped_modules": "SELECT COUNT(*) FROM module WHERE module_type = 'unmapped'",
            "n_unmapped_connections": "SELECT COUNT(*) FROM connection WHERE transfer_mode = 'unmapped'",
            "n_main_journal": "SELECT COUNT(*) FROM paper_document WHERE version = 'journal'",
            "n_main_accepted": "SELECT COUNT(*) FROM paper_document WHERE version = 'accepted_manuscript'",
            "n_main_preprint": "SELECT COUNT(*) FROM paper_document WHERE version = 'preprint'",
            "n_main_repository": "SELECT COUNT(*) FROM paper_document WHERE version = 'repository_copy'",
            "n_train_papers": "SELECT COUNT(*) FROM benchmark_split WHERE split = 'train'",
            "n_test_papers": "SELECT COUNT(*) FROM benchmark_split WHERE split = 'test'",
            "n_excluded_papers": "SELECT COUNT(*) FROM benchmark_split WHERE split = 'excluded'"}.items():
        v[name] = one(sql)
    if v["n_eligible"] + v["n_ineligible"] != v["n_fulltext"]:
        raise ExportError("full-text decisions other than eligible and ineligible; DATA_CARD.md does not cover them")
    v["n_preprint_with_journal_doi"] = sum(
        not (doi or "").lower().startswith(PREPRINT_DOI) for (doi,) in rel.execute(
            "SELECT p.doi FROM paper_document d JOIN paper p USING (paper_id) WHERE d.version = 'preprint'"))

    sources = {r["cand_id"]: {s[0] for s in r["source_ids"].split(";") if s} for r in load_rows(candidates)}
    if set(sources) != {c for (c,) in rel.execute("SELECT cand_id FROM candidate")}:
        raise ExportError(f"{candidates.name} and the candidate table hold different candidates")
    v["n_cand_seed_only"] = sum(s == {"S"} for s in sources.values())
    v["n_cand_keyword_only"] = sum(s == {"K"} for s in sources.values())
    v["n_cand_both"] = sum(s == {"S", "K"} for s in sources.values())
    v["n_cand_bib_added"] = len(load_rows(BIB_ADDITIONS) if additions is None else additions)
    v["n_cand_no_title"] = one("SELECT COUNT(*) FROM candidate WHERE title IS NULL OR title = ''")
    v["n_cand_no_year"] = one("SELECT COUNT(*) FROM candidate WHERE year IS NULL")

    rec = json.loads(json.loads(quality.read_text(encoding="utf-8"))["result"]["finding"])
    era = dict(db.execute("SELECT e.era, COUNT(*) FROM gold_membership g JOIN v_era e USING (paper_id) "
                          "WHERE g.gold_set = 'test' GROUP BY 1").fetchall())
    if sum(era.values()) != rec["n_papers"]:
        raise ExportError(f"{quality.name}: {rec['n_papers']} reference papers, the build has {sum(era.values())}")
    v.update(n_reference_papers=rec["n_papers"], n_reference_recent=era.get("test", 0),
             n_reference_older=era.get("train", 0))
    for field in ("unit_operation", "module_type", "transfer_mode"):
        v[f"f1_{field}"] = f"{rec[f'{field}_strict_micro_f1']:.3f}"
        v[f"f1_{field}_low"] = f"{rec[f'{field}_ci95_lower']:.3f}"

    for prefix, target in (("module", "module_type"), ("transfer", "transfer_mode")):
        t = rel.execute("SELECT n_test_items, n_test_papers, baseline_top1, reference_model_top1, diff_ci95_low, "
                        "diff_ci95_high FROM benchmark_task WHERE target = ?", (target,)).fetchone()
        v.update({f"{prefix}_n_items": t[0], f"{prefix}_n_papers": t[1], f"{prefix}_baseline": f"{t[2]:.4f}",
                  f"{prefix}_reference": f"{t[3]:.4f}", f"{prefix}_diff": f"{t[3] - t[2]:+.4f}",
                  f"{prefix}_low": f"{t[4]:+.4f}", f"{prefix}_high": f"{t[5]:+.4f}"})

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    recorded = {s for (s,) in db.execute("SELECT DISTINCT c.prompt_sha256 FROM coding c "
                                         "JOIN db_record_coding USING (coding_id)")}
    if recorded != {sha(PROTOCOL_PROMPT)}:
        raise ExportError(f"{PROTOCOL_PROMPT.name} is not the instruction file recorded with the codings")
    if sha(PROTOCOL_TAXONOMY) != db.execute("SELECT source_sha256 FROM taxonomy_version").fetchone()[0]:
        raise ExportError(f"{PROTOCOL_TAXONOMY.name} is not the taxonomy file recorded with the build")
    if sha(GUIDELINE_ORIGINAL) not in GUIDELINE_FREEZE.read_text(encoding="utf-8"):
        raise ExportError(f"{GUIDELINE_ORIGINAL.name} is not the guideline recorded at its freeze")
    v.update(prompt_sha256=sha(PROTOCOL_PROMPT), taxonomy_sha256=sha(PROTOCOL_TAXONOMY),
             guideline_sha256=sha(GUIDELINE_ORIGINAL))

    authors = info.get("authors") or []
    if not authors:
        raise ExportError("release.json lists no authors (needed for CITATION.cff and LICENSE-CODE)")
    v["authors_cff"] = "\n".join(
        "\n".join([f"  - family-names: \"{a['family-names']}\"", f"    given-names: \"{a['given-names']}\""]
                  + [f"    {k}: \"{a[k]}\"" for k in ("affiliation", "email", "orcid") if a.get(k)]) for a in authors)
    v["copyright_holders"] = ", ".join(f"{a['given-names']} {a['family-names']}" for a in authors)
    v["copyright_year"] = info["released_on"][:4]
    doi = info.get("zenodo_doi")
    if doi is not None and not ZENODO_DOI.fullmatch(doi):
        raise ExportError(f"release.json zenodo_doi is not a Zenodo DOI: {doi!r}")
    v["citation_doi"] = f'doi: "{doi}"\n' if doi else ""
    v["doi_sentence"] = f" The DOI of this version is {doi} (https://doi.org/{doi})." if doi else ""
    return v


def object_files(rel):
    """{table or view: files of the bundle that hold its rows}."""
    files = defaultdict(list)
    for table in release_tables(rel):
        files[table] += [f"core/{table}.csv", f"core/{table}.parquet"]
    for mode, mapping in MODE_FILES.items():
        for name, source in mapping.items():
            files[source].append(f"modes/{mode}/{name}")
    files["benchmark_split"].append("modes/benchmark/split.csv")
    files["benchmark_item"] += ["modes/benchmark/items_module_type.csv", "modes/benchmark/items_transfer_mode.csv"]
    files["benchmark_task"].append("modes/benchmark/tasks/*.json")
    files["taxonomy_correspondence"].append("modes/taxonomy/correspondence.csv (one line per class)")
    return files


def write_documents(bundle, rel, values):
    """data_dictionary.csv and the rendered documents."""
    files = object_files(rel)
    with (bundle / "data_dictionary.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["object", "kind", "column", "type", "description", "files"])
        for obj, kind, col, typ, text in data_dictionary(rel, RELEASE_SCHEMA.read_text(encoding="utf-8")):
            w.writerow([obj, kind, col, typ, text, "; ".join(files.get(obj, ["sdl-workflows.sqlite only"]))])
    for template, target in DOCUMENTS.items():
        path = bundle / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render((TEMPLATES / template).read_text(encoding="utf-8"), values), encoding="utf-8")
    for source in (PROTOCOL_PROMPT, PROTOCOL_TAXONOMY, GUIDELINE_TRANSLATION):
        shutil.copy(source, bundle / "protocol" / source.name)


def write_manifest(bundle):
    """MANIFEST.sha256: sha256 and path of every other file, sorted by path."""
    files = sorted(p for p in bundle.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(bundle).as_posix()}" for p in files]
    (bundle / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    info = json.loads(RELEASE_INFO.read_text(encoding="utf-8"))
    db = open_internal()
    rel = build_release_db(db, info)
    bundle = write_bundle(rel, info, document_values(rel, db, info))
    n = len((bundle / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines())
    print(f"{bundle.relative_to(ROOT)}: {n} files; SQLite dump sha256 {sqlite_dump_digest(bundle / 'sdl-workflows.sqlite')}")


if __name__ == "__main__":
    main()
