# Inputs of human_involvement.py

Run in this folder, after `../01_coding_agreement/coding_agreement.py` (which writes the confusion table):
`python3 human_involvement.py` (Python 3.12, standard library only; about 30 s). Tests:
`python3 -m unittest test_human_involvement -v`. Results go to `out/`. Paths default to the project workspace two
levels up and can be changed with `--db`, `--workspace`, `--confusion`, `--taxonomy` and `--out` (tests:
environment variables `SDL_SCHEMA`, `SDL_TAXONOMY`, `SDL_DB`).

| Input (workspace path) | Size (bytes) | Paper text? |
|---|---|---|
| `db/sdl-db.sqlite` (opened read-only) | 8,531,968 | No full text or quotation fields. Holds bibliographic metadata (`candidate`: DOI, first author, title, venue of 2,172 candidates) and free text written by the coders (`coding.notes`, `platform.campaigns`, `module.name_in_paper`, `platform_identity_member.evidence`, `process_extraction.notes`, `*.qualifier`, `*.unmapped_note`). In these fields 10-word runs identical to the paper text occur in a few rows each (for example 9 of 516 `coding.notes`, 38 of 268 `process_extraction.notes`). In addition, 47 `platform_identity_member.evidence` rows contain quoted phrases of about 11 words, 9 of which appear word for word in the paper; check these before shipping. The script reads none of these free-text columns: only ids, labels, `performed_by`, `on_platform`, field tags, period, uncertain flags, platform-identity links and `coding.source_path` / `source_file.sha256`. |
| `extraction/test/reference/*.json` and `extraction/test/opus_a/*.json` (60 files, reached through `coding.source_path` for the 30 test papers; each checked against the sha256 stored in the build) | 517,558 | No quotation fields; coder free text as described in `../01_coding_agreement/DATA.md`. Only ids, labels, module ids and evidence locators are used. |
| `../01_coding_agreement/out/extraction_confusion.csv` (written by `coding_agreement.py`; byte-identical to the table the original analysis used, sha256 `2176fd71...b34f`) | 5,678 | No. |
| `protocol/taxonomy-v1.json` | 2,305 | No. |
| `protocol/db-schema.sql` (tests only) | 15,590 | No. |

The build was rebuilt on 1 November 2026 (process tables added). Its content digest differs from the build the
original analysis ran on, but every output value reproduces exactly from the current file
(sha256 `99ed1c62eb27da5da2bbedd3adbd45ddf00f6fcc8084f932efe0cf6e910e82ea`).

## Outputs

| File | Content |
|---|---|
| `results.json` | Counts, platform groups, per-unit-operation field counts (primary fields with weighted n >= 5 at or above half / below half), counts of steps meeting each condition, period breakdown, relabelling (per-unit-operation share quantiles, share of steps whose module type changed, deleted items, miss rates), uncertain items excluded, paired comparison with the independent coding on the test papers |
| `shares.csv` | Weighted n, weighted count depending on people, share and bootstrap interval per unit operation and group, for the main table and each further table (column `analysis`) |
| `field_counts.csv` | Per unit operation, the number of primary fields at or above half and below half |
