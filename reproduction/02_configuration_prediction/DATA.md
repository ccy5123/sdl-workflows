# Prediction of module type and transfer mode: inputs and outputs

## Input

| Input | Read by | Size | Paper text |
|---|---|---|---|
| SQLite build of the database (`db/sdl-db.sqlite` in the working repository), passed with `--db`; opened read-only | `prepare.py`, `evaluate.py` | 8,531,968 bytes | No full text. It holds bibliographic metadata (DOI, year, candidate titles), the coded platforms, steps, modules and connections (module names as given in the paper), page/section locators, and short coder notes in the coder's own words (two notes in `process_extraction` contain a quoted phrase of a few words). The scripts read none of the note, name or title columns. |

Tables and views read: `v_era`, `v_step`, `v_connection`, `gold_membership` (which papers were used to develop the coding guideline, `dev`, and which form the independently coded test set, `test`), `platform_identity_member` and `db_record_coding` (platform groups), and, for the independently coded labels, `coding`, `step`, `step_module`, `module`, `connection`, `transfer_mode`, `unit_operation`, `coding_field_tag`, `item_flag`.

Before reading, `prepare.open_db` checks a sha256 over the INSERT lines of the SQL dump of every table except `db_build`, `source_file` and the three process tables (`process_extraction`, `step_process`, `process_item`). The outputs here were computed on the 237-paper build (`ea4ab949...14fe`), made after Snapp2023 was removed as another version of Snapp2024; the 238-paper build gave `abd4f57f...a32f`.

## Scripts and outputs

| Command (from this folder) | Output |
|---|---|
| `python3 prepare.py --db DB era` | `out/era_list.csv`: paper, first year made public, period (`train` up to 2023, `test` from 2024), guideline set |
| `python3 prepare.py --db DB select-m` | `out/lopo.csv` (leave-one-paper-out accuracy for m in 1, 2, 3, 5, 10), `out/m_selection.json` (papers, items, connections left out, chosen m) |
| `python3 evaluate.py --db DB main` | `out/evaluation/results.json`, `out/evaluation/predictions.csv`: fit up to 2023, evaluate from 2024 |
| `python3 evaluate.py --db DB temporal-2019` | `out/temporal_2019/results.json`, `out/temporal_2019/predictions.csv`: fit up to 2019, evaluate 2020 to 2023 |
| `SDL_DB=DB python3 -m unittest test_evaluate -v` | synthetic tests (the last one reads the database) |

`evaluate.py` needs `out/m_selection.json`, so run `select-m` first. `results.json` holds, per label (`module_type`, `transfer_mode`): items, papers, model and baseline top-1 accuracy, difference, 95% bootstrap intervals, top-3 accuracy and macro-F1, for the evaluated papers (`labels`), the shuffled-label control (`shuffled_labels`), the evaluated papers plus development papers (`with_development_papers`), the evaluated papers without platforms shared with the fitting side (`shared_platforms_removed`) and the independently coded test papers (`reference_coded`). `predictions.csv` lists paper and item identifiers, labels and predictions; it contains no paper text.

Python 3.12.3, standard library only; SQLite 3.45.1.
