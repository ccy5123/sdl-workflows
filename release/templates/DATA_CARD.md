# Data card: sdl-workflows {{version}}

## What the data record

Which modules published closed-loop self-driving laboratories use, in what order one experimental cycle runs its
steps on them, and how material moves between the modules. The unit is the platform: {{n_papers}} papers describe
{{n_platforms}} platforms. One cycle of the loop is coded once, however many cycles a campaign ran. Process
conditions (temperatures, volumes) are not coded. The times, batch sizes, throughput and cost a paper states are
attached to its coded items as timing data, and what it states about human intervention during the campaign is
recorded per paper (sections below).

A closed loop here means that an algorithm chose the next experiment from earlier results and automated hardware
carried it out, at least once on the physical system reported in the paper.

## How the papers were found

The {{n_candidates}} candidates came from two routes, both run on 20 October 2026: the reference lists of three
reviews (Tom et al., Chem. Rev. 2024, doi:10.1021/acs.chemrev.4c00055; Hwang et al., Digital Discovery 2026,
doi:10.1039/d6dd00024j; Lee et al., Mater. Horiz. 2026, doi:10.1039/d5mh01984b), and keyword searches of Crossref
and arXiv. Searches of Semantic Scholar and OpenAlex were attempted and failed on that date.
{{n_cand_seed_only}} candidates came only from the reference lists, {{n_cand_keyword_only}} only from the searches
and {{n_cand_both}} from both. Where a reference list gave no title, venue or year but a DOI was available, the
missing fields were taken from the DOI record ({{n_cand_bib_added}} candidates); {{n_cand_no_title}} candidates
still have no title and {{n_cand_no_year}} no year.

Candidates were screened on titles ({{n_title}}), then abstracts ({{n_abstract}}), then full texts
({{n_fulltext}}). A paper was eligible when all of these held:

1. It is an original research paper.
2. An algorithm chose the next experiment from the results of earlier ones, and at least one such iteration was
   run on the physical system in the paper.
3. The experiments in the loop were executed by automated hardware; isolated manual steps were allowed.
4. Something was made or processed in the loop, not only measured.
5. The hardware configuration is described in the main text or the supplementary information.

{{n_eligible}} papers were eligible and {{n_ineligible}} ineligible (one reason code each, defined in
`modes/trends/screening_reasons.csv`). Of the {{n_decisions}}
screening decisions, {{n_decisions_model}} were made by a language model working from the written criteria (the
model is named in `screening.model_id` for the {{n_decisions_model_named}} decisions whose record names it) and
{{n_decisions_researcher}} by the researcher. When several versions of a study were found (preprint, journal or
other-language version), one was kept; `paper_version_link` lists the {{n_version_links}} pairs.

## How the papers were coded

Each paper was coded once by a language model (Claude Opus 5.5) from its main text and the supplements available as
PDF or docx ({{n_si_docs}} supplements in total), following written coding instructions and taxonomy v1. The
instructions and the taxonomy were settled on 10 development papers and not changed afterwards; every coding in this
release used those versions. The taxonomy has no catch-all class: an item that fits no class is coded
`unmapped` with a note. The classes and their definitions are in `modes/taxonomy/classes.csv`; the instructions, the
taxonomy file and an English translation of the coding guideline are in `protocol/`.

- **Platform:** name, whether it is a commercial integrated system with undisclosed internals, and a summary of its
  campaigns.
- **Module:** class, the name the paper uses, and whether it belongs to the platform or is outside equipment used
  by the loop. Robot arms, gantries and mobile robots are coded as the transfer mode of a connection, not as
  modules, unless they carry out a step themselves.
- **Step:** unit-operation class, whether a robot, a person or software performs it, the modules that perform it,
  and its position in the cycle.
- **Connection:** source and target module, transfer mode, and whether the paper states the transfer or it was
  inferred from context (for example, consecutive steps of one sample on different modules).
- **Paper:** where the hardware is described, the software and hardware autonomy categories of Tom et al. (2024),
  and field tags. For field tags the coder chose from the list of tag names; the definitions in `classes.csv` state
  the scope of each name.

Every item carries the document, page and figure, table or section that describes it; `core/paper_document.csv`
gives the hash and version of each file that was read.

Platforms used in more than one paper share an `identity_id`. Two papers' platforms are the same when one paper
states that it reuses the other's platform (`identity_rule` = `a_stated_reuse`, judged by Claude Opus 5.5 from the
papers' text), or when the platform names match and the corresponding-author groups match by OpenAlex author id
(`b_name_and_group`, applied by a script).
{{n_platforms_shared}} platforms in {{n_identities_shared}} groups appear in more than one paper.

A second coding of every paper by the same model with the same instructions was compared with the released coding
item by item. Items without a counterpart of the same class in the second coding have `uncertain` = 1:
{{n_steps_uncertain}} of {{n_steps}} steps and {{n_connections_uncertain}} of {{n_connections}} connections. The
second coding is not released.

## How far the labels can be trusted

For {{n_reference_papers}} papers ({{n_reference_recent}} first public in 2024 or later, {{n_reference_older}}
earlier), a different model, Claude Fable 5.1, coded the papers under the same instructions as a reference. Against
it, the released coding reached a field-wise strict micro-F1 (an item counts when it pairs with a reference item and
has the same class) of {{f1_unit_operation}} for the unit operation of steps, {{f1_module_type}} for module type
and {{f1_transfer_mode}} for transfer mode. The lower bounds of the paper-level cluster bootstrap 95% intervals were
{{f1_unit_operation_low}}, {{f1_module_type_low}} and {{f1_transfer_mode_low}}. This is agreement between two models,
not accuracy against human coding; the release contains no human coding.

In the release, {{n_unmapped_steps}} steps, {{n_unmapped_modules}} modules and {{n_unmapped_connections}}
connections are `unmapped`.

## Timing data

`step_timing` and `process_value` hold the process numbers the papers state: {{n_durations}} step durations and
{{n_duration_batch_sizes}} numbers of samples one device handles in one run of a step; for platforms,
{{n_batch_size}} batch sizes, {{n_throughput}} throughputs ({{n_throughput_measured}} measured in a campaign,
{{n_throughput_nominal}} nominal), {{n_cost}} costs and the other quantities defined in `data_dictionary.csv`;
{{n_module_values}} module and {{n_connection_values}} connection values. {{n_papers_timing}} of the {{n_papers}}
papers have at least one value. Each value is keyed to a step, platform, module or connection of the release and
carries the document, page and figure, table or section that states it.

Claude Opus 5.5 extracted the values under written instructions (`protocol/process-v1.md`), one extraction per
paper, from the paper's text and its released coding. The instructions allow only numbers the paper states: the
model was not allowed to estimate a value, take one from general knowledge or another paper, or derive a time from
flow rates, volumes or counts. Three pieces of arithmetic were allowed: the midpoint of a stated range
(`range_midpoint`, with `range_low` and `range_high`), a measured throughput as a stated number of experiments
divided by a stated elapsed time of the same campaign (`n_experiments`, `elapsed_time`), and an expression the paper
prints for that one quantity. Values are in the paper's unit. A value the paper does not state has no row. Two
cases need care: a time the paper gives for several consecutive steps sits on the first of them
({{n_joint_durations}} rows), with `covers_steps` naming all of them, and the other steps have no duration row. `parallel_units`, `units` and
`transfer_agent_count` are recorded only when the paper states more than one, so their absence also covers one. A
platform has at most one throughput: a measured one where the paper reports one, else a nominal one.

The instructions ask for a qualifier with each value. Its categorical parts are columns: bound, approximate, range,
throughput kind, rate per working day, the steps a joint duration covers, whether operating hours are those of the
equipment or of people, the kind of transfer agents (robot arms or gantries, mobile robots or people), and the steps and connections a person performs in a less automated configuration. The rest of the
qualifier, including what a cost covers, is the model's free text and is not included.

For the same {{n_timing_reference_papers}} papers as above, Claude Fable 5.1 extracted the timing data under the same
instructions as a reference. An item (a platform's throughput, a step's duration) agreed when both extractions gave a
value and the values, normalised to experiments per day and to minutes per batch, differed by at most 10%. The share
of agreeing items was {{timing_tp_agree}} for throughput ({{timing_tp_items}} platforms) and {{timing_dur_agree}}
for step duration ({{timing_dur_items}} steps; paper-level cluster bootstrap 95% interval {{timing_dur_low}} to
{{timing_dur_high}}). This is agreement between two models, not accuracy. The reference extraction is not released.

## Human-intervention reporting

`human_intervention` records, for every paper, what it states about human intervention during its closed-loop
campaign, read by Claude Opus 5.5 under written instructions (`protocol/human-v1.md`), one extraction per paper.
{{n_human_quantified}} papers state a number for it (a count of interventions, person-time, or the frequency of a
human task), {{n_human_described}} name tasks people performed without a number, {{n_human_none_stated}} state that
the campaign ran without human intervention, and {{n_human_not_reported}} state none of these. One-time set-up before
the first iteration is not intervention; a capability statement or the word "autonomous" alone does not give
`none_stated`. {{n_run_length}} papers state a stretch of the campaign that ran without a person; `run_length_value`
holds the longest, with bounds, approximate values and ranges marked as in the timing data. The category and the
run length carry the location of the statement each rests on. No second extraction exists to compare with.

## Benchmark (`chrono2023`)

Two tasks predict a class from the coded context: the type of a step's primary module (the first module listed
for the step), from its unit operation,
the unit operations of the neighbouring steps and the field tag; and the transfer mode of a material connection,
from the unit operations of the two steps it joins and their families (groups of related unit operations,
column `family` of `modes/taxonomy/classes.csv`). Models train on the {{n_train_papers}} papers
first public in 2023 or earlier and are tested on the {{n_test_papers}} papers first public in 2024 or later; the
{{n_excluded_papers}} papers from 2024 on among the 10 development papers of the coding instructions are left out.

| Task | Test items (papers) | Baseline top-1 | Reference model top-1 | Difference, 95% interval |
|---|---|---|---|---|
| Primary module type | {{module_n_items}} ({{module_n_papers}}) | {{module_baseline}} | {{module_reference}} | {{module_diff}} [{{module_low}}, {{module_high}}] |
| Transfer mode | {{transfer_n_items}} ({{transfer_n_papers}}) | {{transfer_baseline}} | {{transfer_reference}} | {{transfer_diff}} [{{transfer_low}}, {{transfer_high}}] |

The baseline predicts the most frequent class of the unit operation (of the family pair for transfer mode); the
reference model and the scoring are defined in `modes/benchmark/tasks/*.json`. The intervals come from a
paper-level paired cluster bootstrap. `modes/benchmark/evaluate.py` reproduces the table from the release files and
scores new predictions the same way. The labels are the model codings described above, so accuracy on this
benchmark measures agreement with them.

## Limitations

- The search ran once, on one date, in two indexes. The {{n_papers}} papers are the eligible candidates that this
  search found, not every closed-loop SDL paper published; counts by year reflect the search as well as the field.
- Page numbers refer to the file versions in `core/paper_document.csv`. {{n_main_preprint}} main texts are
  preprints, and {{n_preprint_with_journal_doi}} of them belong to papers with a journal version whose pages differ.

## Not included

Paper text and abstracts, process conditions other than the stated times, batch sizes, throughput and cost, the
coders' general notes on each paper, the extracting model's notes and free-text qualifiers, the second coding
(represented only by `uncertain`), and the reference extraction of the timing data.

## Versions and corrections

See `README.md`. Coding corrections are released as PATCH versions and listed in `CHANGELOG.md`.
