# Inputs of coding_agreement.py

Run in this folder: `python3 coding_agreement.py` (Python 3.12, standard library only). Results go to `out/`; the
run takes about one second. Paths default to the project workspace two levels up and can be changed with
`--codings`, `--gold-split`, `--gold-keys`, `--taxonomy` and `--out`.

| Input (workspace path) | Files | Size (bytes) | Paper text? |
|---|---|---|---|
| `extraction/test/reference/*.json` (independent coding, 30 test papers) | 30 | 277,564 | No quotation fields. Free-text fields written by the coder (`paper.notes`, `platforms[].name`, `platforms[].campaigns`, `modules[].name_in_paper`, `*.unmapped_note`) and short evidence locators (document; page; section heading). A few of these strings repeat 8 to 13 consecutive words of the paper (mostly instrument or platform names). |
| `extraction/test/recode/*.json` (second independent coding, 10 papers) | 10 | 93,826 | As above. |
| `extraction/test/opus_a/*.json` (language-model records) | 30 | 239,994 | As above. |
| `extraction/test/opus_b/*.json` (second language-model extraction) | 30 | 240,593 | As above. |
| `collection/gold_split.csv` | 1 | 8,545 | No paper text; bibliographic metadata (DOI, first author, year, title) of the 40 coded papers. The script reads only `cand_id`, `set`, `recode`, `field_tag` and the six difficult-case columns. |
| `collection/gold_keys.csv` | 1 | 2,491 | No. |
| `protocol/taxonomy-v1.json` | 1 | 2,305 | No. |

The 8-to-13-word overlaps were found by comparing every free-text field of the coding files with the text
inputs the coders read (runs of 8 or more identical words). The scoring reads only ids, labels, module ids and
evidence locators; the free-text fields are not used, except `unmapped_note`, which is copied into
`out/taxonomy_unmapped_items.csv`. A copy of the coding files with the free-text fields blanked would give the
same numbers.

`out/inputs_sha256.csv` lists the sha256 of every input file read.

## Outputs

| File | Content |
|---|---|
| `recode_summary.json`, `recode_per_paper.csv` | 10 papers coded twice: counts, step- and connection-identification F1, kappa, percent agreement, Gwet's AC1, bootstrap intervals |
| `taxonomy_coverage_summary.json`, `taxonomy_coverage_per_field_tag.csv`, `taxonomy_unmapped_items.csv` | Mapped shares of steps, modules, connections (overall, per field tag) and the unmapped items |
| `extraction_summary.json`, `extraction_per_case.csv`, `extraction_per_field_tag.csv`, `extraction_per_paper.csv`, `extraction_confusion.csv` | Records vs independent coding: strict micro-F1 with intervals, identification F1, agreement and kappa on paired items, per difficult case and field tag, agreement of the two extractions, uncertain flags |
| `negative_control_summary.json`, `negative_control_derangement.csv` | Each extraction scored against another paper's independent coding |

`extraction_confusion.csv` is an input of `../04_human_involvement/human_involvement.py`.
