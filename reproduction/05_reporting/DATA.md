# Reporting of simulation inputs: inputs and outputs

## Inputs

| Input | Read by | Size | Paper text |
|---|---|---|---|
| SQLite build of the database (`db/sdl-db.sqlite` in the working repository), passed with `--db`; opened read-only | `reporting.py` | 8,531,968 bytes | No full text. It holds bibliographic metadata (DOI, year, candidate titles), the coded platforms, steps, modules and connections, the timing and process values with their qualifiers, page/section locators, and short coder notes in the coder's own words (two notes in `process_extraction` contain a quoted phrase of a few words). The script reads none of the note or title columns. |
| Human-intervention coding, one JSON file per paper (`extraction/human/opus/<paper_id>.json`, 238 files), passed with `--human-dir` | `reporting.py` | 424,786 bytes in total | The files also hold the extractor's free-text notes with page locators, which can include short phrases from the paper. The script reads only two fields: `human_intervention` (category) and `unassisted_run_length` (whether the list is empty). The files are not copied here. |

Tables and views read: `db_record_coding`, `db_process_extraction`, `platform`, `v_step`, `v_connection`, `step_process`, `process_item`, `v_era`, `coding_field_tag`, `platform_identity_member`.

Before reading, the script checks the content digest of the build (sha256 of the SQL dump without the `db_build` row, `57b39af5...a08a`); the current `db/sdl-db.sqlite` is that build.

## Script and outputs

| Command (from this folder) | Output |
|---|---|
| `python3 reporting.py --db DB --human-dir DIR` | `out/indicators.csv` (one row per paper: period, primary field, human-intervention category, 0/1 per item, blank when not eligible), `out/items.csv` (one row per item), `out/results.json` |
| `python3 test_reporting.py -v` | synthetic tests (no real data) |

`results.json` holds, per item: eligible and reporting papers, share and 95% bootstrap interval (`items`); early (up to 2023) and late (from 2024) shares, late-minus-early difference and its period-stratified interval (`by_period`); fields tested, chi-square, permutation p and Holm-adjusted p (`by_field`); platform-weighted shares (`platform_weighted`, 200 platform groups). It also holds the further descriptive items with intervals (`descriptive`), the human-intervention category counts and the distribution of the number of items reported per paper.

Python 3.12.3, standard library only; SQLite 3.45.1.
