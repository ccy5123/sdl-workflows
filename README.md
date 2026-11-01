# sdl-workflows (code)

Code that builds, documents and checks the dataset **sdl-workflows**: hardware workflows of the closed-loop
self-driving laboratories described in 238 published papers.

- Dataset: Zenodo, https://doi.org/10.5281/zenodo.23857126 (version 1.0.0, CC BY 4.0)
- Code: this repository (MIT)

The data themselves are on Zenodo, not here. Download `sdl-workflows-1.0.0.zip` from the record; its `README.md` and
`DATA_CARD.md` describe the contents.

## Layout

| Path | What it is |
|---|---|
| `release/export_release.py` | Builds the bundle from one recorded internal database build: release tables, CSV, Parquet, SQLite, JSON, documents, manifest |
| `release/evaluate.py` | The benchmark evaluation shipped in the bundle (`modes/benchmark/evaluate.py`); Python standard library only |
| `release/check_release.py` | Checks a finished bundle against the release conditions |
| `release/schema/` | SQL schema of the release (the source of the data dictionary) and the two JSON Schemas |
| `release/inputs/` | Hand-written export inputs: version and authors, English definitions, correspondence additions, version judgments of paper files, bibliographic additions from DOI records |
| `release/templates/` | Templates of the bundle's documents; their numbers are filled at build time |
| `release/protocol/` | English translation of the coding guideline shipped in the bundle |
| `release/manifests/` | SHA-256 manifest of the 1.0.0 bundle and the SHA-256 of its zip |
| `release/tests/` | Unit tests (`unittest`), with a small hand-made internal build as fixture |
| `protocol/`, `extraction/prompt-v1.md`, `analysis/sdl-db-02/h1_tool.py`, `runs/sdl-db-02/evidence/` | Files of the authors' research workspace that the code reads: the internal schema, the taxonomy, the coding instructions, the record of the guideline's freeze, the benchmark item builder and the recorded benchmark evaluation |

## Using it with the published bundle

Reproduce the benchmark's reference values from the bundle (inside the unzipped folder):

```bash
python modes/benchmark/evaluate.py modes/benchmark
```

Check a bundle against the release conditions (from the root of this repository):

```bash
python release/check_release.py path/to/sdl-workflows-1.0.0
```

Without the internal build, the row counts and the source digest are checked against the bundle itself. Compare the
bundle's `MANIFEST.sha256` with `release/manifests/sdl-workflows-1.0.0.MANIFEST.sha256`.

## Tests

```bash
python -m unittest discover release/tests -v
```

Needs Python 3.12, `pyarrow` and `jsonschema`. Tests that read the internal build, the coders' input texts or the
two frozen protocol documents written in Korean (the correspondence table and the original coding guideline) are
skipped here, each with its reason; in the authors' workspace all of them run.

## Rebuilding the bundle

`export_release.py` reads files that are not in this repository: the internal SQLite build of the research record
(content digest `6bc13fac…`, named in `release/inputs/release.json`), the text of the papers given to the coders and
the paper files (copyrighted), the candidate list and the recorded evaluations. A rebuild therefore runs only in the
authors' workspace; this repository records the code that produced the published bundle.

## Citation and licence

Cite the dataset by its DOI (see `CITATION.cff` in the bundle). Code: MIT (`LICENSE`).
