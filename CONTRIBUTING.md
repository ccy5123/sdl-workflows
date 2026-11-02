# Contributing to sdl-workflows

The data are on Zenodo (https://doi.org/10.5281/zenodo.23857125, all versions); this repository holds the code that builds them.
Contributions to the data come in as GitHub issues. Open a new issue and pick one of three forms:

| Form | Use it for | Released as |
|---|---|---|
| Correction to a coded item | A module, step, connection, platform or paper record that does not match its source paper | PATCH version |
| Missing or new paper | A closed-loop self-driving laboratory paper the dataset does not include | MINOR version |
| Taxonomy or vocabulary mapping | A mapping of a class to another vocabulary, or a change to a class | MINOR version for a mapping; a MAJOR version if a class changes incompatibly |

Problems with the code itself go in an ordinary issue or a pull request.

## How a contribution is handled

- **Corrections.** Each item names the document, page and figure, table or section that describes it. The
  maintainer checks a correction against that page of the file version listed in `core/paper_document.csv`.
- **New papers.** The maintainer screens a suggested paper against the five inclusion criteria in `DATA_CARD.md`.
  Eligible papers are coded with the instructions in `protocol/` that coded the released papers, so that every
  paper is coded the same way.
  Please suggest papers rather than sending codings.
- **Taxonomy.** A mapping that cites its source is checked against that source. A new class or a changed definition
  changes how papers are coded, so it is discussed in the issue and decided by the maintainer.
- **Benchmark.** The benchmark (`chrono2023`: papers made public up to 2023 predict the module types and transfer modes of papers made public from 2024 on) keeps the items, labels, split and reference values published in
  1.0.0. Corrections change the tables of later releases, not the benchmark.
- **Releases.** Accepted contributions are collected into the next release. Its `CHANGELOG.md` lists each change
  with the number of the issue it came from. Issues that are not accepted are closed with the reason.

Do not paste more than a short quote from a paper into an issue; the dataset holds no paper text.

## Licence and credit

By submitting a contribution you agree that it is published under CC BY 4.0, the licence of the dataset. Code sent
by pull request is published under MIT, the licence of this repository.

Accepted contributors are listed in `CONTRIBUTORS.md` and as contributors (role: data curator) on the Zenodo record
of the release that includes their contribution, with name and ORCID when given in the issue.
