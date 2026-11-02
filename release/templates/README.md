# sdl-workflows {{version}}

Hardware workflows of the closed-loop self-driving laboratories (SDLs) described in {{n_papers}} published papers.
For each platform, the data list its modules (pieces of equipment, software or human work stations), the steps one experimental cycle runs
on them, and the connections that move material or data between modules. Every item has a class from a fixed
taxonomy and the page of the source paper that describes it. The timing data attach the times, batch sizes,
throughput and cost each paper states to these items, and each paper's reporting of human intervention during its
closed-loop campaign is recorded.

| | Count |
|---|---|
| Papers (first public {{year_min}}–{{year_max}}) | {{n_papers}} |
| Platforms | {{n_platforms}} |
| Modules | {{n_modules}} |
| Steps | {{n_steps}} |
| Connections ({{n_material_connections}} move material) | {{n_connections}} |
| Screened candidates | {{n_candidates}} |
| Stated step durations and samples per run (`step_timing`) | {{n_step_timing}} |
| Stated platform, module and connection values (`process_value`) | {{n_process_values}} |
| Papers with human-intervention reporting coded (`human_intervention`) | {{n_human}} |

How the papers were found and coded, and how far the labels can be trusted, is in `DATA_CARD.md`. Every column
is described in `data_dictionary.csv`.

## Where to start

| If you want to | Use | Files |
|---|---|---|
| Design or compare a platform | `modes/builder/` | `platforms.csv`, `steps.csv`, `connections.csv`, `platform_graphs.jsonl` (one platform per line as a graph) |
| Follow how SDL hardware has changed | `modes/trends/` | `papers.csv` (one row per paper), `candidates.csv`, `screening.csv`, `screening_reasons.csv`, `human_intervention.csv` (one row per paper) |
| Train or test a model that predicts workflow elements | `modes/benchmark/` | `tasks/*.json`, `split.csv`, `items_module_type.csv`, `items_transfer_mode.csv`, `evaluate.py`, `reference_results.json` |
| Map these classes to another vocabulary | `modes/taxonomy/` | `classes.csv` (definitions), `correspondence.csv` |
| Simulate platforms (cycle times, batch sizes) | `modes/simulation/` | `step_timing.csv`, `process_values.csv` (stated values only; `README.md` there says how to read them) |

All tables are in `core/` as CSV and Parquet, and in `sdl-workflows.sqlite` together with the views from which the files
in `modes/` are made (`builder_platform`, `builder_step`, `builder_connection`, `trends_paper`, `taxonomy_class`, ...).
`schema/release-schema.sql` defines them; `schema/platform-graph.schema.json` and
`schema/benchmark-task.schema.json` define the JSON files. `protocol/` holds the instructions the papers were
coded and the timing data and human-intervention reporting extracted with (see `protocol/README.md`).

## Quick start

```bash
sqlite3 sdl-workflows.sqlite "SELECT platform_id, platform_name, n_modules, n_steps, material_transfer_modes FROM builder_platform LIMIT 5"
```

```bash
python modes/benchmark/evaluate.py modes/benchmark
```

The second command fits the baseline and the reference model of the benchmark (`chrono2023`: models trained on
papers made public up to 2023 predict the module types and transfer modes of papers made public from 2024 on; see `DATA_CARD.md`) and checks them against the values reported there
(Python 3 standard library only). To score your own predictions, write a CSV with columns `item_id,prediction`, one
row per test item, and run:

```bash
python modes/benchmark/evaluate.py modes/benchmark --task chrono2023-module_type --predictions my_predictions.csv
```

## Identifiers and source locations

- A paper is identified by a citation key (`paper_id`, e.g. `Aand2024`) that does not change between releases.
  Items below it are `<paper_id>/P<n>` (platform), and `/M<k>`, `/S<k>`, `/E<k>` (module, step, connection).
  `S<k>` is the k-th step of one cycle.
- `ev_doc`, `ev_page` and `ev_locator` give where an item is described: the main text (`main`) or the k-th
  supplement (`SI<k>`), a page, and a figure, table or section. `core/paper_document.csv` gives the SHA-256 of the
  file that was read and its version. The main texts are {{n_main_journal}} journal versions,
  {{n_main_accepted}} accepted manuscripts, {{n_main_preprint}} preprints and {{n_main_repository}} repository copy;
  {{n_preprint_with_journal_doi}} of the preprints belong to papers that also have a journal version, whose page
  numbers differ. Pages of PDF files are PDF pages; docx supplements, which have no PDF pages, are counted by the
  supplement's own page numbers. Timing values and human-intervention statements carry the same three columns
  (`run_ev_doc`, `run_ev_page`, `run_ev_locator` for a stated run without a person).
- No paper text is included: the release holds bibliographic data, coded classes, stated values with their units
  and locations only.

## Sources of the correspondence table

`taxonomy_correspondence.source_ref` names its sources by key.

| Key | Vocabulary | Reference |
|---|---|---|
| Mehr2020 | XDL | Mehr et al., Science 370, 101–108 (2020), doi:10.1126/science.abc2986. Page numbers refer to the accepted manuscript in the University of Glasgow repository |
| Schilling2026, Schilling2026_SI | WeChemSynOntology (WCSO) | Schilling et al., Digital Discovery 5, 2074 (2026), doi:10.1039/d6dd00058d, and its supplementary information |
| Leong2022 | MAP workflow framework | Leong et al., Matter 5, 3124 (2022), doi:10.1016/j.matt.2022.08.017. The locators Proposal, CS1–CS3 and FW1–FW3 are the paper's own section heading and labels of its case studies and future-work examples |
| Bai2024 | OntoLab / SAREF (module types only) | Bai et al., Nature Communications 15, 462 (2024), doi:10.1038/s41467-023-44599-9 |
| Gottstein2026 | Orchestration levels | Gottstein et al., Device 4, 101202 (2026), doi:10.1016/j.device.2026.101202 |

The software and hardware autonomy categories (`paper.sw_autonomy`, `paper.hw_autonomy`) are those of Tom et al.,
Chemical Reviews 124, 9633 (2024), doi:10.1021/acs.chemrev.4c00055.

## Versions

Release numbers are `MAJOR.MINOR.PATCH`: MAJOR changes when the taxonomy or the schema changes incompatibly, MINOR
when papers, tables or folders under `modes/` are added, PATCH when codings are corrected. `CHANGELOG.md` lists the changes.
The benchmark has its own identifier (`chrono2023`); its split and reference values stay as they are when later
releases add papers, and a new split gets a new identifier. Release 1.1.0 corrected the split under the same
identifier: one study had been recorded as two papers, one on each side of the split, so the test set went from 99
to 98 papers (module type: 1199 to 1189 items; transfer mode: 426 to 424). `CHANGELOG.md` gives the details.
Results on the benchmark should name the release with the identifier, for example `chrono2023` in sdl-workflows 1.1.0.

`MANIFEST.sha256` lists the SHA-256 of every file. This release was exported from the authors' internal
database; the SHA-256 of its contents is `{{source_build_digest}}`.

## Citation and licence

See `CITATION.cff`.{{doi_sentence}} Data: CC BY 4.0 (`LICENSE-DATA`). Code (`modes/benchmark/evaluate.py`): MIT (`LICENSE-CODE`).
