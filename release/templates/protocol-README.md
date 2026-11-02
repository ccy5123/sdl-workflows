# Coding and extraction instructions

The files the coding and the two extractions of this release followed.

| File | What it is |
|---|---|
| `prompt-v1.md` | The instructions given to the language model (Claude Opus 5.5) that coded every paper, unchanged. Its SHA-256, `{{prompt_sha256}}`, is the one recorded with every coding in the release. |
| `taxonomy-v1.json` | The class lists of taxonomy v1, unchanged (SHA-256 `{{taxonomy_sha256}}`). The same classes, with definitions, are in `modes/taxonomy/classes.csv`. |
| `coding-guideline.md` | An English translation of coding guideline v1, which `prompt-v1.md` names as its authority. The guideline was written in Korean and fixed before coding began (SHA-256 of the original: `{{guideline_sha256}}`); the original is not included. The translation was made for this release and is not the text the model read. |
| `process-v1.md` | The instructions for the timing data (`step_timing`, `process_value`), unchanged. Its SHA-256, `{{process_sha256}}`, is the one recorded with every timing extraction in the release. |
| `human-v1.md` | The instructions for the human-intervention reporting (`human_intervention`), unchanged. Its SHA-256, `{{human_sha256}}`, is the one recorded before the extraction began; the instructions were not changed afterwards. |

The files are records of the authors' study and keep its working references:

- Paths such as `extraction/inputs/<paper_id>/`, `extraction/db/opus_a/<paper_id>.json`, `protocol/`,
  `extraction/rehearsal/validate.py`, `extraction/process/validate.py` and `extraction/human/validate.py` are folders
  and scripts of the authors' workspace, not of this release. Where the two extraction instructions refer to a
  paper's existing coding, they mean the coding released in `core/`.
- "Spec sdl-db-01" is the pre-registered plan of the study that tested the coding. Its hypotheses H1 (reproducibility
  of the reference coding), H2 (taxonomy coverage) and H3 (agreement of the extraction with the reference coding) are
  reported in `DATA_CARD.md`. "Spec sdl-db-03" and "Spec sdl-db-05" are the plans of the studies that used the
  timing data and the human-intervention reporting.
- The reference coder (Claude Fable 5.1) coded 30 test papers for that study; the extractor (Claude Opus 5.5)
  produced the codings in this release. `process-v1.md` was also given to Claude Fable 5.1 for the same 30 papers;
  that reference extraction is not released (`DATA_CARD.md` reports the agreement).
- The `notes` field and the free text of `qualifier` that the two extraction instructions ask for are not in the
  release; the categorical parts of `qualifier` are columns of the tables.
- The guideline describes a human check of 3 test papers. It was removed from the study plan before it was carried
  out (the study plan was changed on 26 October 2026); no human coding exists.
