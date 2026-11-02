# sdl-workflows (code)

Code that builds, documents and checks the dataset **sdl-workflows**: hardware workflows of the closed-loop
self-driving laboratories described in 238 published papers.

- Dataset: Zenodo, https://doi.org/10.5281/zenodo.23875743 (version 1.1.0, CC BY 4.0); all versions:
  https://doi.org/10.5281/zenodo.23857125
- Code: this repository (MIT)

The data themselves are on Zenodo, not here. Download `sdl-workflows-<version>.zip` from the record; its `README.md` and
`DATA_CARD.md` describe the contents.

## Layout

| Path | What it is |
|---|---|
| `release/export_release.py` | Builds the bundle from the authors' internal SQLite database, which is not public: release tables, CSV, Parquet, SQLite, JSON, documents and the list of file hashes |
| `release/evaluate.py` | The benchmark evaluation shipped in the bundle (`modes/benchmark/evaluate.py`); Python standard library only |
| `release/check_release.py` | Checks a finished bundle against the release conditions |
| `release/schema/` | SQL schema of the release (the source of the data dictionary) and the two JSON Schemas |
| `release/inputs/` | Hand-written export inputs: version and authors, English definitions, correspondence additions, version judgments of paper files, bibliographic additions from DOI records, the reference values of the benchmark tasks |
| `release/templates/` | Templates of the bundle's documents; their numbers are filled at build time |
| `release/protocol/` | English translation of the coding guideline shipped in the bundle |
| `release/manifests/` | SHA-256 manifest of each released bundle and the SHA-256 of its zip |
| `release/tests/` | Unit tests (`unittest`), with a small hand-made stand-in for the internal database as fixture |
| `protocol/`, `extraction/prompt-v1.md`, `extraction/process-v1.md`, `extraction/human-v1.md`, `analysis/sdl-db-02/h1_tool.py` | Files of the authors' research workspace that the code reads: the internal schema, the taxonomy, the coding instructions, the instructions of the timing and human-intervention extractions, the hashes recorded when the coding guideline was fixed, and the code that builds the benchmark items |
| `reproduction/`, `analysis/sdl-db-02/platform_group_bootstrap.py`, `package_src/figures/` | The analyses and figures of the manuscript describing the dataset (next section) |

## Analyses in the manuscript

The scripts below produced every computed number, table and figure of the manuscript "What Can the Records of
Published Self-Driving Laboratories Predict About a New Platform? A Step-Level Database and Explorer" and its
Supporting Information (SI).
`reproduction/` has one folder per analysis with its scripts, their tests, the result files of the reported run
(`out/`) and a `DATA.md` (in `06_further_analyses/`, a `README.md`) that gives the run commands and lists every input
with its size and checksum. The folder `analysis/sdl-db-02/` is named after the authors' internal study number.

Python 3.12.3. `03_throughput/` and the scripts of `06_further_analyses/` that import it need SimPy 4.1.2; the figure
script needs matplotlib, numpy and seaborn; everything else uses the standard library. Seeds and resampling order are
fixed in the scripts, so a rerun on the same inputs gives the reported values exactly.

Data needed, last column: **public** means the dataset on Zenodo (sdl-workflows 1.1.0,
https://doi.org/10.5281/zenodo.23875743), unzipped so that the folder `release/out/sdl-workflows-1.1.0/` exists in
this repository; **here** means result files already in this repository; **internal** means the authors' internal
SQLite database (content digest `57b39af5…a08a`), which has more tables and views than the release, and, where
named, the coders' or extractors' files of each paper. These files are not public because their free-text notes can
repeat short phrases of the papers. Scripts that need them can be read and their tests run here; their `out/` files
are the outputs of the reported run.

| Manuscript | Script | Data needed |
|---|---|---|
| Figure 1, the record of one platform | `package_src/figures/make_figures.py 1` | internal |
| Figure 2, contents of the database | `package_src/figures/make_figures.py 2` | public |
| Table 1, agreement of the records with the independent coding; SI Tables S3 and S4 | `reproduction/01_coding_agreement/coding_agreement.py` (with `pairing.py`) | internal, with the coding files of the 30 test papers |
| Table 2, prediction of module type and transfer mode; SI Table S5 except the platform-group row; the choice of the minimum count *m* (SI) | `reproduction/02_configuration_prediction/prepare.py` (period list, choice of *m*), `evaluate.py` (main evaluation and the split at 2019), `model.py` (the model and the baseline) | internal |
| SI Table S5, row with platform groups resampled | `analysis/sdl-db-02/platform_group_bootstrap.py` | public |
| Figure 3, transfer modes, observed and predicted | `package_src/figures/make_figures.py 3` | here (`06_further_analyses/out/config_class_counts.csv`, `02_configuration_prediction/out/evaluation/predictions.csv`) |
| SI Table S6, transfer-mode distribution; the majority-rule comparison (SI) | `reproduction/06_further_analyses/config_class_distribution.py` | internal |
| Table 3, agreement of the timing data with the independent extraction | `reproduction/03_throughput/timing_agreement.py` (with `agreement_scoring.py`) | internal, with the timing extraction files of the 30 test papers |
| Table 3, simulation rows; SI Tables S7 and S8 | `reproduction/03_throughput/throughput.py` (with `simulator.py`, the discrete-event simulator) | internal |
| Figure 4, simulated and summed-duration throughput against reported throughput | `package_src/figures/make_figures.py 4` | here (`03_throughput/out/throughput/results.json`) |
| Results, paired comparisons of the simulation with the field median and with the two simple estimates | `reproduction/06_further_analyses/throughput_comparisons.py` | here (`03_throughput/out/throughput/results.json`) |
| SI Table S9, working hours of people | `reproduction/06_further_analyses/human_hours_sensitivity.py` | internal |
| Results, dependence on people by unit operation; SI Table S13 | `reproduction/04_human_involvement/human_involvement.py` (with `pairing.py`) | internal, with the coding files of the 30 test papers, and here (`01_coding_agreement/out/extraction_confusion.csv`) |
| Figure 5, reporting of ten simulation inputs | `package_src/figures/make_figures.py 5` | here (`05_reporting/out/results.json`) |
| Results, reporting of simulation inputs; SI Tables S10 to S12 | `reproduction/05_reporting/reporting.py` | internal, with the human-intervention extraction files of the 238 papers |

Not computed by code in this repository: the search and screening counts of the corpus (Methods; SI Section S1 and Figure S1),
SI Table S1 (the list of reference papers) and SI Table S2 (the unit-operation classes, from
`protocol/taxonomy-v1.json`).

`make_figures.py` writes into `package_src/figures/`; from the result files here and the unzipped release it
regenerates Figures 2 to 5 byte for byte (SVG). One output of `coding_agreement.py` is not included:
`taxonomy_unmapped_items.csv`, which copies the coders' notes on items outside the taxonomy.

Tests that need no internal data (from the root of this repository):

```bash
python -m unittest discover -s reproduction/02_configuration_prediction -p "test_*.py"
(cd reproduction/03_throughput && python -m unittest test_simulator.py test_throughput.py)
(cd reproduction/04_human_involvement && python -m unittest test_human_involvement)
(cd reproduction/05_reporting && python test_reporting.py)
```

One test in each of the first and third commands reads the internal database and is skipped without it.

## Using it with the published bundle

Reproduce the benchmark's reference values from the bundle (inside the unzipped folder):

```bash
python modes/benchmark/evaluate.py modes/benchmark
```

Check a bundle against the release conditions (from the root of this repository):

```bash
python release/check_release.py path/to/sdl-workflows-1.1.0
```

Without the internal database, the row counts and the database hash the bundle names are checked against the
bundle itself. Compare the
bundle's `MANIFEST.sha256` with `release/manifests/sdl-workflows-<version>.MANIFEST.sha256`.

## Tests

```bash
python -m unittest discover release/tests -v
```

Needs Python 3.12, `pyarrow` and `jsonschema`. Tests that read the internal database, the coders' input texts or the
two study documents written in Korean (the correspondence table and the original coding guideline) are
skipped here, each with its reason; in the authors' workspace all of them run.

## Rebuilding the bundle

`export_release.py` reads files that are not in this repository: the authors' internal SQLite database
(SHA-256 of its contents `57b39af5…` for 1.1.0 and `6bc13fac…` for 1.0.0; `release/inputs/release.json` names the current
one), the text of the papers given to the coders and the paper files (copyrighted), the human-intervention extraction
files (which hold the extracting model's notes), the candidate list and the authors' records of the benchmark evaluation. A rebuild therefore runs only in the
authors' workspace; this repository records the code that produced the published bundle.

## Contributing

Corrections, missing papers and taxonomy mappings are welcome as GitHub issues; `CONTRIBUTING.md` explains the
three issue forms and how contributions are reviewed and credited.

## Citation and licence

Cite the dataset by its DOI (see `CITATION.cff` in the bundle). Code: MIT (`LICENSE`).
