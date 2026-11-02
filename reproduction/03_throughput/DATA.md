# Inputs of the throughput analyses

All inputs are read in place; none is copied into this folder. Paths are relative to the workspace root.

| Input | Read by | Size | Paper text |
|---|---|---|---|
| `db/sdl-db.sqlite` (SQLite DB build) | `throughput.py --db` | 8,531,968 bytes | No full text and no passages from the papers. Holds bibliographic metadata (DOI, first author, year, title), the coded platforms, modules, steps, connections and extracted timing values. Its free-text columns hold the extractors' own notes, module names as the papers name them, and location pointers (document, page, figure or section), not quotations. |
| `extraction/process/opus/<paper_id>.json`, 30 files used (folder holds 238; only papers that also have a reference extraction are read) | `timing_agreement.py --extraction` | 80,017 bytes (30 files used) | No full text. Extracted timing values with units, a short qualifier, a location pointer per value, and the extractor's own notes. |
| `extraction/process/fable/<paper_id>.json`, 30 files (the test papers) | `timing_agreement.py --reference` | 99,633 bytes | As above (independent extraction). |
| `extraction/test/opus_a/<paper_id>.json`, 30 files (record codings named by each extraction file) | `timing_agreement.py --root` | 239,994 bytes | No full text. Platforms, modules, steps and connections with location pointers and the coder's own notes. |

The DB build is identified by its content digest, the sha256 of its SQL dump without the `db_build` row
(`throughput.build_digest`). The manuscript values were computed on the build with digest
`57b39af53554a4b7dbccbdfebfc3b254f88f6af050a378b3cb1f9435deeaa08a`; the current `db/sdl-db.sqlite` has this digest
(file sha256 `b98da79e63ec3e8c1261a106ace09f74521c4ce4781c58b1f5650cdc775df702`). `throughput.py` writes the digest
it read into its outputs and warns when it differs.

sha256 of the sorted `"<path> <sha256>\n"` listing of each extraction file set: Opus files used
`3b9aca9200e373c94a95f27318f8977553dbcffe70b4d8625d1e667aec6c2113`, Fable
`17ebae5adca3bc62ef03c887d4952913c4b8f87c14a495c773000d3fedb3c351`, record codings
`d66b7974090751a56bb0d7449067a4ce1a1d0d4d5847999c714b16efd07b13c6`.

## Running

Python 3.12.3; `throughput.py` and its tests need simpy 4.1.2, the rest uses the standard library only.

```
python3 reproduction/03_throughput/timing_agreement.py --extraction extraction/process/opus \
    --reference extraction/process/fable --root . --out reproduction/03_throughput/out/timing_agreement
python reproduction/03_throughput/throughput.py --db db/sdl-db.sqlite --out reproduction/03_throughput/out/throughput
cd reproduction/03_throughput && python -m unittest test_simulator.py test_throughput.py
```

| Script | Output | Values |
|---|---|---|
| `timing_agreement.py` (uses `agreement_scoring.py`) | `out/timing_agreement/results.json` | agreement of reported throughput and step duration with the independent extraction, same throughput kind, other quantities, cross-paper negative control |
| `throughput.py` (uses `simulator.py`, `agreement_scoring.py`) | `out/throughput/evaluation_sets.json` | evaluation sets, case lists, pool sizes |
| | `out/throughput/results.json` | `summary` (reproduction with own durations, prediction with pooled durations, automation gain), `negative_control_shuffled_durations`, `breakdowns` (by kind, case, field, own-duration coverage; serial-sum and bottleneck-rate estimates; flagged and failed papers), `per_paper` |

`throughput.py` takes about 2.5 minutes.
