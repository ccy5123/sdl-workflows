"""A small internal build for tests: the frozen internal schema (protocol/db-schema.sql) with two papers' worth of
hand-made rows. Every expected value in the tests is worked out from the rows below.

Papers
  Lee2020 (C0001, 2020, train)  one platform, 4 modules, 5 steps, 4 connections; extractor_b disagrees on S2, so
                                S2 carries an 'uncertain' flag. Platform is a singleton.
  Kim2025 (C0002, 2025, test)   one platform, 3 modules, 3 steps, 2 connections; states reuse of Lee2020's
                                platform (identity rule a). sdl-db-01 development paper, so it is excluded from the
                                benchmark evaluation.
Candidates C0001-C0003; C0003 is excluded at the title stage as a review (E_review).
"""
import json
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTERNAL_SCHEMA = ROOT / "protocol" / "db-schema.sql"
TAXONOMY = ROOT / "protocol" / "taxonomy-v1.json"
PROMPT = "extraction/prompt-v1.md"
# The frozen correspondence table and the original coding guideline are written in Korean and kept in the research
# workspace only; the tests that read them skip elsewhere (e.g. in the public code repository).
FROZEN_KOREAN = (ROOT / "protocol" / "taxonomy-correspondence.md", ROOT / "protocol" / "coding-guideline.md")
needs_frozen_documents = unittest.skipUnless(
    all(p.exists() for p in FROZEN_KOREAN),
    "needs the frozen Korean protocol documents of the research workspace (not in the public repository)")


def build_fixture():
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(INTERNAL_SCHEMA.read_text(encoding="utf-8"))
    ins = lambda table, row: db.execute(f"INSERT INTO {table} VALUES ({','.join('?' * len(row))})", row)

    tax = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    ins("taxonomy_version", ("v1", "2026-10-21", "0" * 64))
    for fam, ops in tax["unit_operation"].items():
        ins("uo_family", (fam,))
        for op in ops:
            ins("unit_operation", (op, fam))
    ins("uo_family", ("unmapped",))
    ins("unit_operation", ("unmapped", "unmapped"))
    for m in tax["module_type"] + ["unmapped"]:
        ins("module_type", (m,))
    for t in tax["transfer_mode"] + ["unmapped"]:
        ins("transfer_mode", (t, 0 if t == "data_transfer" else 1))
    for f in tax["field_tag"] + ["unmapped"]:
        ins("field_tag", (f,))

    ins("candidate", ("C0001", "10.1000/lee2020", None, "Lee", 2020, "A robot that dispenses", "Chem &amp; Eng"))
    ins("candidate", ("C0002", "10.1000/kim2025", None, "Kim", 2025, "A flow platform", "Lab Chip"))
    ins("candidate", ("C0003", "10.1000/rev2024", None, "Park", 2024, "A review of robots", "Rev J"))
    for cand, stage, dec, reason, who in [
            ("C0001", "title", "likely", None, "session-subagent"),
            ("C0001", "abstract", "fulltext", None, "session-subagent"),
            ("C0001", "fulltext", "eligible", None, "researcher"),
            ("C0002", "title", "likely", None, "session-subagent"),
            ("C0002", "abstract", "fulltext", None, "session-subagent"),
            ("C0002", "fulltext", "eligible", None, "claude-opus-5-5"),
            ("C0003", "title", "exclude", "E_review", "session-subagent")]:
        ins("screening", (cand, stage, 1, dec, reason, who, "collection/candidates_screened.csv"))
    ins("paper", ("Lee2020", "C0001", "10.1000/lee2020", None, 2020, "candidate_year"))
    ins("paper", ("Kim2025", "C0002", "10.1000/kim2025", None, 2025, "candidate_year"))
    ins("gold_membership", ("Kim2025", "dev", 0, 0))

    for pid in ("Lee2020", "Kim2025"):
        for role in ("extractor_a", "extractor_b"):
            src = f"extraction/db/opus_{role[-1]}/{pid}.json"
            ins("source_file", (src, "1" * 64, "coding_json"))
            ins("coding", (f"{pid}|{role}|p1", pid, role, f"opus-{role}", "claude-opus-5-5", PROMPT, "2" * 64,
                           "v1", src, "coder notes with a \"quoted passage from the paper\"", "main", 2, 2))

    def platform(cid, pid, name, modules, steps, edges):
        ins("platform", (cid, f"{pid}/P1", name, 0, "two campaigns", "main", 2, "Fig. 1"))
        for k, (mtype, mname, on, note) in enumerate(modules, 1):
            ins("module", (cid, f"{pid}/P1/M{k}", f"{pid}/P1", mtype, mname, on, note, "main", 3, "Fig. 2"))
        for k, (op, by, mods) in enumerate(steps, 1):
            ins("step", (cid, f"{pid}/P1/S{k}", f"{pid}/P1", k, op, by, None, "SI1", 4, "Table S1"))
            for pos, m in enumerate(mods, 1):
                ins("step_module", (cid, f"{pid}/P1/S{k}", f"{pid}/P1/M{m}", pos))
        for k, (a, b, mode, stated) in enumerate(edges, 1):
            ins("connection", (cid, f"{pid}/P1/E{k}", f"{pid}/P1", f"{pid}/P1/M{a}", f"{pid}/P1/M{b}", mode,
                               stated, None, "main", 3, "§2 ¶1"))

    lee_modules = [("liquid_handler", "pipetting robot", 1, None), ("batch_reactor", "heating block", 1, None),
                   ("instrument_optical", "plate reader 4'-model", 0, None), ("software", "BO script", 1, None)]
    lee_edges = [(1, 2, "robot_arm_gantry", 1), (2, 3, "human_transfer", 0), (3, 4, "data_transfer", 1),
                 (4, 1, "data_transfer", 1)]
    kim_modules = [("fluidics", "syringe pumps", 1, None), ("flow_reactor", "coil reactor", 1, None),
                   ("software", "optimiser", 1, None)]
    kim_steps = [("dispense_liquid", "robot", [1]), ("react_flow", "robot", [2]), ("plan_next_experiment", "software", [3])]
    kim_edges = [(1, 2, "fixed_tubing", 1), (3, 1, "data_transfer", 1)]
    for role, s2 in (("extractor_a", "react_thermal"), ("extractor_b", "mix")):
        lee_steps = [("dispense_liquid", "robot", [1]), (s2, "robot", [2]), ("measure_optical", "human", [3]),
                     ("analyze_data", "software", [4]), ("plan_next_experiment", "software", [4])]
        platform(f"Lee2020|{role}|p1", "Lee2020", "Robot One", lee_modules, lee_steps, lee_edges)
        platform(f"Kim2025|{role}|p1", "Kim2025", "Flow Two", kim_modules, kim_steps, kim_edges)
    ins("coding_field_tag", ("Lee2020|extractor_a|p1", "chemistry_synthesis", 1))
    ins("coding_field_tag", ("Lee2020|extractor_a|p1", "catalysis", 2))
    ins("coding_field_tag", ("Kim2025|extractor_a|p1", "chemistry_synthesis", 1))
    ins("item_flag", ("Lee2020|extractor_a|p1", "Lee2020/P1/S2", "step", "uncertain", "Lee2020|extractor_b|p1",
                      "pairing=spec-v3-r1fam; unpaired-or-label-differs"))

    ins("platform_identity", ("I001", "Robot One", "A0000000001"))
    ins("platform_identity_member", ("I001", "Lee2020|extractor_a|p1", "Lee2020/P1", "singleton", "build-rule", None))
    ins("platform_identity_member", ("I001", "Kim2025|extractor_a|p1", "Kim2025/P1", "a_stated_reuse",
                                     "claude-opus-5-5",
                                     'Kim2025 states reuse of Lee2020: main.txt, Introduction: "we reuse the robot"'))
    ins("db_build", (1, "draft-1", "2026-10-25T22:05:26+09:00", "3" * 64, "v1"))
    db.commit()
    return db
