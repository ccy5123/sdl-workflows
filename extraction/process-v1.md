# Process-information extraction instructions v1 (frozen 2026-10-26, Spec sdl-db-03 v2; text of dev rehearsal r3, tuned on the 10 dev papers only)

You read ONE closed-loop self-driving-lab (SDL) paper and attach the process numbers it reports (times,
batch sizes, throughput, cost) to the items of its existing database record. The same instructions are given
to the extractor (Opus 5.5) and to the reference extractor (Fable 5.1).

## Inputs
- `extraction/inputs/<paper_id>/`: `main.txt` (main text, blocks headed `=== main pdf p.N ===`), `si_<k>.txt`
  (supplements, blocks headed `=== SI<k> pdf p.N ===`), `files.txt` (data/media supplements you cannot read).
  Read ALL of main.txt and the SI text before extracting.
- The record coding named in your task (`extraction/db/opus_a/<paper_id>.json` or similar): its platforms,
  modules, steps (in execution order) and connections, with their IDs. Read it to know what each ID is.
- Use only these files and this page. Do not open any other coding or extraction output in the workspace.

The record is fixed. Never add, remove, merge or relabel platforms, modules, steps or connections. If a
reported number belongs to something the record does not have, leave it out and say so in `notes`.

## The one rule that matters most
Record only numbers the paper states (text, tables, figure labels, SI). Do not estimate, do not take a value
from general knowledge or from another paper, do not derive a time from flow rates, volumes or counts. Three
pieces of arithmetic are allowed, and only these:
1. a stated range or span ("2–4 h", "residence times of 1 to 10 min") is recorded as its arithmetic midpoint,
   with the range in `qualifier` (`range 2-4 h`);
2. a measured throughput may be computed as N experiments ÷ elapsed time when the paper states both numbers
   for the same campaign (see Throughput); the two numbers go in `qualifier`;
3. an arithmetic expression the paper itself prints for that one quantity ("(60 + 90) × 2 s") is evaluated
   (300 s), with the expression in `qualifier`. Adding up separately listed times of different steps or
   table rows is NOT allowed.
A bound counts as a stated number: "at least 200 s", "less than 5 min", "up to 100 per day", "over 100
experiments" are recorded as 200 s, 5 min, 100, 100, with `lower bound` or `upper bound` at the start of
`qualifier` (in a throughput row: after `measured; ` or `nominal; `). "About/approximately X" is recorded
as X with `approximately`. A batch size of one counts as
stated when the paper says in words that one experiment is proposed and run at a time (e.g. a sequential
simplex, "one reaction per cycle"); "reaction(s)" or a plural without a number does not.
Unit conversion is not needed: give the value in the unit the paper uses, if it is in the allowed list.
A number that is not reported gets no row. An empty list is a valid answer.

When a time or size differs between the paper's campaigns, use the value of the campaign your throughput row
comes from; if there is no throughput row, the campaign with the most closed-loop experiments (first reported
if tied). Mention the other campaigns' values in `notes`.

## What to extract

### Steps (`step_process`)
For each step of the record whose time the paper states:
- `duration`: how long the step occupies its module(s) for one run of that step — the reaction time of a
  reaction step, the residence time of a flow-reactor step, the run time of one measurement, the dispensing
  time, the drying/annealing/incubation time, the computation time of an analysis step. Units: `s`, `min`,
  `h`, `d`.
- `duration_batch_size`: how many samples ONE device handles together in one run of that step, when the paper
  says so (e.g. a 96-well plate incubated together → 96; an HPLC run per sample → 1; a cell that holds one
  solution → 1). Unit `samples`. If the paper does not say, give no row; the time is then taken to apply to
  the whole batch. When a module stands for several identical devices working side by side (five cells, three
  heating blocks), the number of devices is the module's `units`, NOT the duration_batch_size: five cells that
  each hold one sample are `units` 5 with `duration_batch_size` 1.
- A time the paper gives for several consecutive steps together ("synthesis and characterisation take 2 h")
  goes on the FIRST of those steps, with `qualifier` = `covers <step_id>, <step_id>, ...` listing all of them;
  the other steps get no `duration` row, even when the paper also gives a time for one of them (put that time
  in `notes`). The joint time takes precedence over times of single steps inside its span.
- A time that varies with the experiment (the planner chooses it) is recorded as the midpoint of the stated
  range (rule 1). If only the values of single experiments are listed, do not average them; give no row and
  say so in `notes`.
- The computation time to propose the next batch is the `duration` of the record's `plan_next_experiment`
  step; use the platform `planning_time` only if the record has no such step.
- Waiting for a person, or overnight storage, is not a step duration.

### Platform (`process_items`, `target_kind` = `platform`, `target_id` = platform_id)
- `batch_size` (`samples`): how many experiments the planner proposes at once and gets back together.
- `parallel_units` (`count`): how many such batches can be in progress at the same time (e.g. two reactors
  running different batches). Give a row only if the paper says more than one can run at once.
- `planning_time` (`s`/`min`/`h`): computation time to propose one batch.
- `operating_hours_per_day` (`h`) and `operating_days_per_week` (`d`): only if the paper states them;
  `qualifier` = `automated` (the platform) or `human` (the people doing manual steps).
- `throughput`: ONE row per platform at most (see Throughput).
- `experiments_per_count` (unitless): only if the throughput is counted in samples and the paper says how many
  samples make one experiment (e.g. 3 replicates per condition → 0.3333). Give the value to 4 decimals.
- `cost`: a stated cost of the platform or of one experiment; `unit` = currency code (`USD`, `EUR`, `GBP`,
  `JPY`, `KRW`, `CNY`, ...); `qualifier` = what the cost covers, in your own words.
- `throughput_less_automated` and `throughput_automated`: only if the paper reports throughput for both a less
  automated configuration (e.g. manual transfer, manual operation of a step) and the automated one of the
  same workflow. Units as for throughput. `qualifier` of `throughput_less_automated` = the step_ids and
  edge_ids of the record that a person performs in the less automated configuration, comma separated,
  then `; ` and measured/nominal.
- `transfer_agent_count` (`count`): how many robot arms/gantries, mobile robots or people move samples;
  `qualifier` = `robot_arm_gantry`, `mobile_robot` or `human`. Only if the paper says more than one.

### Modules (`target_kind` = `module`)
- `units` (`count`): number of identical devices that module stands for (e.g. "four syringe pumps" coded as
  one fluidics module → only if they work in parallel on different samples; "two identical XRD machines" → 2).
  Only if more than one.

### Connections (`target_kind` = `connection`)
- `transfer_time` (`s`/`min`/`h`): time to move one batch along that connection, if stated.

### Throughput
"Experiment" = one set of conditions evaluated and returned to the planner.
- `measured`: the rate the paper observed in a campaign — "N experiments in T", "ran for 8 days and
  performed 688 experiments", "about 30 experiments per day during the campaign". If the paper states N and T
  separately for the same campaign, value = N ÷ T, unit = `experiments/<unit of T>`, qualifier =
  `measured; N=<N>; T=<T> <unit>`. N and T must both be stated FOR THAT CAMPAIGN as numbers the paper reports
  (e.g. "129 experiments over 69 h"); a capability sentence ("the entire cycle can be completed within a single
  day") combined with a count from the design is NOT a throughput. Count only the experiments of the closed
  loop (include initial design-of-experiments rounds only if the paper's T includes them; say which in
  qualifier).
- `nominal`: a capacity the paper states as a number of experiments per time or a time per experiment/batch —
  cycle time per experiment, "up to 100 samples per day", "one experiment every 45 min". qualifier =
  `nominal`.
- One row per platform: take a measured value if the paper has one, else a nominal one. Among several
  measured campaigns take the one with the most experiments (first reported if tied). Among several nominal
  statements take, in this order: a rate per day or longer ("one round per day", "100 experiments per
  day"); else any other rate ("4 per hour", "100 samples every 4 h"); else a cycle time. Mention the others in
  `notes`.
- Count in the paper's own noun. If the paper says "experiments", the unit is `experiments/...`, even when
  each experiment is run in replicate; use `samples` (with `experiments_per_count`) only when the paper itself
  counts samples, vials or formulations.
- Units: `experiments/<t>`, `samples/<t>`, `batches/<t>`, or a cycle time `<t>/experiment`, `<t>/sample`,
  `<t>/batch`, where `<t>` is `s`, `min`, `h`, `d` or `week`, optionally preceded by a whole number for a
  rate per several time units: "100 samples every 4 h" is value 100, unit `samples/4h` (do not divide).
  Use `samples` when the paper counts samples or
  formulations that are not one-to-one with experiments and say why in `notes`. A rate per working day
  ("per 8-h working day") is `/d`; say so in qualifier. A count in `batches` is converted with the platform
  `batch_size`, so give `batch_size` too.

## Evidence location
`<doc> ; pdf p.<N> ; <locator>` where doc is `main` or `SI<k>`, N is the page from the block header, locator is
the most specific of `Fig. 2b`, `Table S3`, `Scheme 1`, `§<section> ¶<n>`. One place per row; no quotes.

## Output
Write exactly one JSON file to the path given in your task, UTF-8:
{
 "paper_id": "<paper_id>",
 "coder": "<label given in your task>",
 "record_coding": "<path of the record coding you were given>",
 "step_process": [{"step_id": "<pid>/P1/S3", "quantity": "duration", "value": 30, "unit": "min", "qualifier": "", "evidence": "..."}],
 "process_items": [{"target_kind": "platform", "target_id": "<pid>/P1", "quantity": "throughput", "value": 2.5, "unit": "experiments/h", "qualifier": "measured; N=120; T=48 h", "evidence": "..."}],
 "notes": "..."
}
Values are numbers (not strings), > 0. `qualifier` is "" when there is nothing to say. Then run
`python3 extraction/process/validate.py <your json>` and fix every error until it prints OK.
