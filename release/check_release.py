"""Check a finished sdl-workflows bundle against the release conditions (drafts/dataset/schema-design.md section 5).

  1. no foreign-key violation, no value outside the taxonomy, no 'unmapped' item without a note
  2. no quotation of 12 or more characters in the free-text columns
  3. the bundle's evaluate.py reproduces the recorded benchmark values, which are those of the recorded evaluation
  4. row counts equal the internal build's (papers, steps, connections, platforms, modules) and every core CSV
     holds as many rows as its SQLite table
  5. the bundle names the source build digest of release.json, and the internal build has that digest
  6. no HTML entity left in the bibliographic columns
and, before them, that MANIFEST.sha256 lists every file with its hash.

Reads the bundle and, for conditions 3-5, the internal build and the recorded evaluation; writes nothing.
Run from the workspace root:  python3 release/check_release.py [BUNDLE_DIR]
Exit status 0 when every check passes.
"""
import csv
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import export_release as ex  # noqa: E402

ENTITY = re.compile(r"&(?:[A-Za-z]+|#[0-9]+|#x[0-9A-Fa-f]+);")
CORE_COUNTS = {"paper": "SELECT COUNT(*) FROM paper",
               "platform": "SELECT COUNT(*) FROM platform p JOIN db_record_coding USING (coding_id)",
               "module": "SELECT COUNT(*) FROM module m JOIN db_record_coding USING (coding_id)",
               "step": "SELECT COUNT(*) FROM v_step",
               "connection": "SELECT COUNT(*) FROM v_connection"}
CLASS_COLUMNS = (("step", "unit_operation", "unit_operation"), ("module", "module_type", "module_type"),
                 ("connection", "transfer_mode", "transfer_mode"))


def open_bundle_db(bundle):
    return sqlite3.connect(f"file:{bundle / 'sdl-workflows.sqlite'}?mode=ro", uri=True)


def check_manifest(bundle):
    listed = {}
    for line in (bundle / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, path = line.split("  ", 1)
        listed[path] = digest
    on_disk = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()} - {"MANIFEST.sha256"}
    bad = sorted(p for p in listed if p not in on_disk
                 or hashlib.sha256((bundle / p).read_bytes()).hexdigest() != listed[p])
    unlisted = sorted(on_disk - listed.keys())
    return not bad and not unlisted, f"{len(listed)} files; changed or missing {bad[:5]}; unlisted {unlisted[:5]}"


def check_integrity(rel):
    fk = rel.execute("PRAGMA foreign_key_check").fetchall()
    outside = []
    for table, col, ref in CLASS_COLUMNS:
        outside += rel.execute(f"SELECT '{table}', {col} FROM {table} WHERE {col} NOT IN "
                               f"(SELECT {ref} FROM {ref})").fetchall()
    outside += rel.execute("SELECT 'benchmark_item', label FROM benchmark_item WHERE label NOT IN "
                           "(SELECT module_type FROM module_type UNION SELECT transfer_mode FROM transfer_mode)").fetchall()
    unnoted = []
    for table, col, _ in CLASS_COLUMNS:
        unnoted += rel.execute(f"SELECT '{table}' FROM {table} WHERE {col} = 'unmapped' "
                               "AND length(coalesce(unmapped_note, '')) = 0").fetchall()
    ok = not fk and not outside and not unnoted
    return ok, f"foreign-key violations {len(fk)}, values outside the taxonomy {len(outside)}, unmapped without note {len(unnoted)}"


def check_quotations(rel):
    found = []
    for table, (key, cols) in ex.FREE_TEXT.items():
        for col in cols:
            for k, text in rel.execute(f"SELECT {key}, {col} FROM {table} WHERE {col} IS NOT NULL"):
                found += [(table, k, col) for _ in ex.quotations(text)]
    return not found, f"quotations {len(found)} {found[:3]}"


def check_benchmark(bundle, evidence):
    bench = bundle / "modes" / "benchmark"
    run = subprocess.run([sys.executable, "-I", str(bench / "evaluate.py"), str(bench)], capture_output=True,
                         text=True, timeout=600)
    rec = json.loads(json.loads(evidence.read_text(encoding="utf-8"))["result"]["finding"])
    differ = []
    for field, task_id in (("a", "chrono2023-module_type"), ("b", "chrono2023-transfer_mode")):
        task = json.loads((bench / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))
        pairs = {"baseline_top1": rec[f"{field}_baseline"], "reference_model_top1": rec[f"{field}_tool"],
                 "diff_ci95_low": rec[f"{field}_diff_ci95"][0], "diff_ci95_high": rec[f"{field}_diff_ci95"][1],
                 "n_test_items": rec[f"{field}_items"]}
        differ += [(task_id, k) for k, v in pairs.items() if round(task[k], 4) != round(v, 4)]
    ok = run.returncode == 0 and not differ
    return ok, f"evaluate.py exit {run.returncode}; task values differing from the record {differ}"


def check_counts(bundle, rel, internal):
    differ = []
    if internal is not None:
        for table, sql in CORE_COUNTS.items():
            a, b = rel.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], internal.execute(sql).fetchone()[0]
            if a != b:
                differ.append((table, a, b))
    for table in ex.release_tables(rel):
        with (bundle / "core" / f"{table}.csv").open(encoding="utf-8", newline="") as f:
            n_csv = sum(1 for _ in csv.reader(f)) - 1
        n_db = rel.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if n_csv != n_db:
            differ.append((f"core/{table}.csv", n_csv, n_db))
    counts = {t: rel.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("paper", "step", "connection")}
    return not differ, f"{counts}; differing {differ}"


def check_digest(rel, expected, internal):
    named = rel.execute("SELECT source_build_digest FROM release").fetchone()[0]
    actual = ex.internal_digest(internal) if internal is not None else None
    ok = named == expected and (actual is None or actual == expected)
    return ok, f"bundle names {named[:16]}..., release.json {expected[:16]}..., internal build " + \
        (f"{actual[:16]}..." if actual else "not read")


def check_entities(bundle, rel):
    hits = [c for c, *values in rel.execute("SELECT cand_id, title, venue, first_author FROM candidate")
            if any(ENTITY.search(v or "") for v in values)]
    with (bundle / "core" / "candidate.csv").open(encoding="utf-8", newline="") as f:
        hits += [r["cand_id"] for r in csv.DictReader(f)
                 if any(ENTITY.search(r[k]) for k in ("title", "venue", "first_author"))]
    return not hits, f"entities in {len(hits)} rows {hits[:3]}"


def check(bundle, internal=None, evidence=ex.BENCHMARK_EVIDENCE, expected_digest=None):
    """[(check, passed, detail)] for one bundle."""
    bundle = Path(bundle)
    rel = open_bundle_db(bundle)
    try:
        return [("manifest", *check_manifest(bundle)),
                ("1 integrity", *check_integrity(rel)),
                ("2 quotations", *check_quotations(rel)),
                ("3 benchmark", *check_benchmark(bundle, evidence)),
                ("4 row counts", *check_counts(bundle, rel, internal)),
                ("5 source build", *check_digest(rel, expected_digest, internal)),
                ("6 HTML entities", *check_entities(bundle, rel))]
    finally:
        rel.close()


def main(argv=None):
    info = json.loads(ex.RELEASE_INFO.read_text(encoding="utf-8"))
    args = sys.argv[1:] if argv is None else argv
    bundle = Path(args[0]) if args else ex.OUT / f"sdl-workflows-{info['release_version']}"
    # Outside the research workspace there is no internal build: conditions 4 and 5 then check the bundle alone
    # (CSV rows against SQLite tables; the digest the bundle names against release.json).
    internal = ex.open_internal() if ex.INTERNAL_DB.exists() else None
    if internal is None:
        print("note: internal build not present; row counts and digest are checked against the bundle only")
    results = check(bundle, internal, ex.BENCHMARK_EVIDENCE, info["source_build_digest"])
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    manifest = hashlib.sha256((bundle / "MANIFEST.sha256").read_bytes()).hexdigest()
    print(f"MANIFEST.sha256 sha256 {manifest}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
