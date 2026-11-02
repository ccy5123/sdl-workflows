# Changelog

## 1.1.0 ({{released_on}})

Adds the timing data and the human-intervention reporting of all {{n_papers}} papers, and removes one paper that
1.0.0 held twice: 1.0.0 has 238 papers and 280 platforms, 1.1.0 has 237 and 279.

Snapp2023 (candidate C1176, arXiv 10.48550/arxiv.2308.02315) is the preprint of Snapp2024 (C1499, Nat. Commun.
10.1038/s41467-024-48534-4): the same authors and the same study. 1.1.0 keeps Snapp2024 and removes Snapp2023 with
its platform, modules, steps and connections. Its full-text decision in `screening` is now ineligible,
`E_duplicate_version`, decided by the researcher, and `paper_version_link` holds the pair C1176-C1499. As for every
paper with a linked version, `first_public_year` is the earliest year of the versions, so Snapp2024 is now dated
2023 and is a training paper of the benchmark `chrono2023` instead of a test paper. The test set has 98 papers
instead of 99 (module type: 1189 items instead of 1199; transfer mode: 424 instead of 426), and the reference values
in `benchmark_task` come from the authors' evaluation repeated on the corrected database. The row of Gongora2020 in
`platform` names Snapp2024 instead of Snapp2023 as the paper that states the reuse of its platform.

Apart from these rows, every table of 1.0.0 holds the same rows as in 1.0.0, except the one row of `release`, which
names this version and the database it was exported from, and the DOIs of the seven papers named below. The reason
given for the benchmark's excluded papers now reads "one of the 10 development papers of the coding instructions"
instead of "used to develop the extraction instructions", and the Gottstein2026 rows of `taxonomy_correspondence`
write their PDF pages as `p.N` like the other sources instead of `pdf p.N`.

Seven papers recorded in 1.0.0 under a preprint DOI have since been published (Christensen2021, Emery2024,
Ginsburg2023, Sheng2023, Tamasi2022, Vescovi2023, Zhang2023). Their `paper.doi` now gives the DOI of the journal or
proceedings version; the preprint DOI stays in `candidate.doi`, and their `first_public_year` is unchanged, so none
of them moves between the two periods of the benchmark split. The main text of Christensen2021 that was read is the journal
article, and its `paper_document` row now names the article's DOI instead of the ChemRxiv DOI.

- `step_timing` ({{n_step_timing}} rows): {{n_durations}} stated step durations and {{n_duration_batch_sizes}}
  stated numbers of samples one device handles in one run of a step.
- `process_value` ({{n_process_values}} rows): stated batch sizes, parallel batches, operating hours and days,
  throughput (measured or nominal), cost, throughput of a less automated and of the automated configuration, and
  numbers of transfer agents (robot arms or gantries, mobile robots or people that move samples) of
  platforms; numbers of identical devices a module stands for; transfer times of connections.
- `human_intervention` ({{n_human}} rows, one per paper): how the paper reports human intervention during its
  closed-loop campaign, and the longest stated run without a person.
- The files `modes/simulation/step_timing.csv`, `modes/simulation/process_values.csv` and
  `modes/trends/human_intervention.csv`; `modes/simulation/README.md` describes the timing data.
- `protocol/process-v1.md` and `protocol/human-v1.md`, the instructions the two extractions followed.

Exported from the authors' internal database (SHA-256 of its contents `{{source_build_digest}}`). That
database is the one 1.0.0 was exported from with the timing data added and Snapp2023 removed; the platforms,
modules, steps and connections of the other papers are unchanged.

## 1.0.0 (2026-11-01)

First release: 238 papers, 280 platforms, taxonomy v1, and the benchmark `chrono2023` (papers made public up to 2023 predict the module types and transfer modes of papers made public from 2024 on).
DOI 10.5281/zenodo.23857126. Exported from the authors' internal database (SHA-256 of its contents
`6bc13fac0303d08817c63b1615ef7c0e0c15161982b5853b808cd1226bef320a`).
