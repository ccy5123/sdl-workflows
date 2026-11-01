# Coding instructions

The files the coding of this release followed.

| File | What it is |
|---|---|
| `prompt-v1.md` | The instructions given to the language model (Claude Opus 5.5) that coded every paper, unchanged. Its SHA-256, `{{prompt_sha256}}`, is the one recorded with every coding in the release. |
| `taxonomy-v1.json` | The class lists of taxonomy v1, unchanged (SHA-256 `{{taxonomy_sha256}}`). The same classes, with definitions, are in `modes/taxonomy/classes.csv`. |
| `coding-guideline.md` | An English translation of coding guideline v1, which `prompt-v1.md` names as its authority. The guideline was written and frozen in Korean (SHA-256 of the original: `{{guideline_sha256}}`); the original is not included. The translation was made for this release and is not the text the model read. |

The files are records of the authors' study and keep its working references:

- Paths such as `extraction/inputs/<paper_id>/`, `protocol/` and `extraction/rehearsal/validate.py` are folders and
  scripts of the authors' workspace, not of this release.
- "Spec sdl-db-01" is the pre-registered plan of the study that tested the coding. Its hypotheses H1 (reproducibility
  of the reference coding), H2 (taxonomy coverage) and H3 (agreement of the extraction with the reference coding) are
  reported in `DATA_CARD.md`.
- The reference coder (Claude Fable 5.1) coded 30 test papers for that study; the extractor (Claude Opus 5.5)
  produced the codings in this release.
- The guideline describes a human check of 3 test papers. It was removed from the study plan before it was carried
  out (amendment of 26 October 2026); no human coding exists.
