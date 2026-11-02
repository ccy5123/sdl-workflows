# Timing data for simulation

The process numbers the papers state, keyed to the coded items, as needed to simulate a platform's operation. The
release holds the stated numbers only; it contains no simulator.

| File | Rows | What it holds |
|---|---|---|
| `step_timing.csv` | {{n_step_timing}} | Per step: `duration` ({{n_durations}} rows) and `duration_batch_size`, the number of samples one device handles together in that run ({{n_duration_batch_sizes}} rows). |
| `process_values.csv` | {{n_process_values}} | Per platform ({{n_platform_values}} rows): batch size, parallel batches, planning time, operating hours and days, throughput, experiments per sample (when the throughput counts samples), cost, throughput of a less automated and of the automated configuration, transfer agents (robot arms or gantries, mobile robots or people). Per module ({{n_module_values}}): number of identical devices. Per connection ({{n_connection_values}}): transfer time. |

The files are copies of the tables `step_timing` and `process_value` (`core/`, `sdl-workflows.sqlite`). Join them to
`modes/builder/steps.csv`, `platforms.csv` and `connections.csv` by `step_id`, `platform_id` and `edge_id`;
`process_values.csv` names its item in `target_kind` and `target_id`. `data_dictionary.csv` defines every column.

Reading the values:

- A number the paper does not state has no row. The extracting model was not allowed to estimate a value, take one
  from another paper or derive one from flow rates, volumes or counts (`protocol/process-v1.md`).
- Values are in the unit the paper uses. A value stated as a range is its midpoint (`range_midpoint` = 1, with
  `range_low` and `range_high`); `bound` marks a stated bound and `approximate` an approximate value.
- A time the paper gives for several consecutive steps sits on the first of them, and `covers_steps` lists all of
  them ({{n_joint_durations}} rows); the other steps then have no `duration` row.
- A step without `duration_batch_size` has no stated number of samples per run; its duration applies to the batch.
- A platform has at most one `throughput`: a rate measured in a campaign (`throughput_kind` = measured) where the
  paper reports one, else a nominal capacity or cycle time. A measured rate computed from a stated number of
  experiments and elapsed time gives both (`n_experiments`, `elapsed_time`).
- `parallel_units`, `units` and `transfer_agent_count` are recorded only when the paper states more than one; no
  row means one or not stated.
