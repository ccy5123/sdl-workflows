# Further analyses of configuration prediction and throughput

These scripts import the code in `../02_configuration_prediction/` and `../03_throughput/` without changing it. They
read the same database build (content digest `57b39af5...a08a`, structure digest `ea4ab949...14fe`). Every interval
is a 95% percentile bootstrap over papers, with B = 2000 and seed 1, following the resampling rules of the script each
analysis extends. The scripts compute values only; they apply no thresholds.

Python 3.12.3. Run from this folder. Pass `-B` so that no `__pycache__` is written into the imported folders.

| Script | Command | Outputs |
|---|---|---|
| `config_class_distribution.py` | `python3 -B config_class_distribution.py --db ../../db/sdl-db.sqlite --out out` | `out/config_class_distribution.json`: per label (transfer mode, module type), item and paper counts, the majority label, the accuracy of the model, the baseline and the majority-class rule, and the paired differences between them, each with its interval. `out/config_class_counts.csv`: the number and share of items for each label value, on the fitting side (papers up to 2023) and on the evaluated side (papers from 2024). |
| `throughput_comparisons.py` | `~/.venvs/sdl-db-03/bin/python -B throughput_comparisons.py --results ../03_throughput/out/throughput/results.json --out out` | `out/throughput_comparisons.json`. Reproduction test (35 papers): shares within a factor of 1.5 for the simulation, the serial-sum estimate and the bottleneck-rate estimate; paired differences between them; measured minus nominal reported throughput, with stratified and unstratified bootstraps; median fold errors. Prediction test (128 papers): shares within 1.5x for the field-median baseline, the simulation and the two simple estimates; the paired difference simulation minus baseline; median fold errors. No new simulation is run; the script reads the recorded per-paper values. |
| `human_hours_sensitivity.py` | `~/.venvs/sdl-db-03/bin/python -B human_hours_sensitivity.py --db ../../db/sdl-db.sqlite --recorded ../03_throughput/out/throughput/results.json --out out` | `out/human_hours_sensitivity.json`: both throughput tests rerun with the base human calendar (Mon–Fri 09:00–17:00), with continuous availability (24 h, 7 d) and with seven days at 09:00–17:00; the base rerun checked paper by paper against the recorded values; the number of papers with human work; each variant's share, mean difference and paired difference against the base. `out/human_hours_per_paper.csv`: the simulated throughput of each paper under each variant. This run takes about 3 minutes. |

The human-hours variants replace the default calendar only for platforms that state neither human operating hours nor
human operating days. If a platform states one of the two, `throughput.calendars` fills in the other with 8 h or 5 d, and
that calendar is kept in every variant. None of the evaluated platforms states either value. The calendar applies only
to human steps and human transfers.
