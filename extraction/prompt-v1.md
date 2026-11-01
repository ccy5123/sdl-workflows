# Coding / extraction instructions v1 (frozen 2026-10-21, Spec sdl-db-01 v3)

You code ONE closed-loop self-driving-lab (SDL) paper into a structured record.
Follow `protocol/coding-guideline.md` (v1) and the class lists in `protocol/taxonomy-v1.json`. Those two files
are the authority; this page fixes the output format and repeats the scope rules. The same instructions are
given to the reference coder (Fable 5.1) and to the extractor (Opus 5.5).

## Inputs
`extraction/inputs/<paper_id>/`: `main.txt` (main text, blocks headed `=== main pdf p.N ===`),
`si_<k>.txt` (supplements, blocks headed `=== SI<k> pdf p.N ===`), `files.txt` (data/media supplements
you cannot read). Read ALL of main.txt and the SI text before coding. Use only these files. Do not open any
other coding or extraction output in the workspace.

## What to code
- One cycle of the closed-loop workflow per platform. No process conditions.
- Platforms P1..; modules M1.. (order of first mention); steps S1.. (actual execution order);
  connections E1.. (order of first mention).
- A different module composition is a different platform; campaigns on the same equipment are listed in the
  platform's `campaigns`.

Steps
- Only steps executed in every loop cycle. One-time setup before a campaign (stock solutions, catalyst
  packing, mobile-phase preparation, calibration, initial design-of-experiments rounds) is NOT a step;
  mention it in paper.notes.
- The cycle starts with its first physical step. Software steps come at the end, in this order:
  `analyze_data`, `plan_next_experiment`, then `generate_instructions` (only when the paper describes a
  separate conversion of conditions/designs into machine instructions by the researchers' software).
- One step = one unit operation by one module (or a human). Consecutive dispensing by the same module with no
  other operation in between is ONE step, however many reagents. A dispense after a mix, heat or move is a
  new step. If the paper does not state the order, do not split.
- The period in which the reaction is left to proceed after all reagents are added (stirred or not, heated or
  at room temperature) is `react_thermal` (or `react_flow` in a flow reactor). Use `mix` only for short mixing
  between additions or just before a measurement.
- Taking part of a sample for analysis is `sample_aliquot`, also when the portion is diluted on its way to the
  analyser.
- Cleaning (`clean_equipment`) is a step only if the paper places it inside the sequence of each cycle
  (main text, SI or status logs). Cleaning only at campaign start/end or as maintenance goes to notes.
- If one software both analyses and plans, give it two steps: `analyze_data` then `plan_next_experiment`.

Modules
- A unit the paper names as one module (e.g. a "reaction module") is ONE module only if its parts form one
  connected flow path or one physical assembly (e.g. a preheating coil, micromixer and reactor joined by
  tubing); code its operations as steps of that module. If the named unit is a group of separately operated
  devices between which a robot or a person moves the sample (e.g. a pump dispensing system, a pipette on a
  robot arm and a stir plate), split it by device. Otherwise one physically separate device is one module.
- Pumps, valves and tubing of one fluid-delivery system are ONE `fluidics` module.
- A device on which the reaction vessels sit while the reaction proceeds (stir plate or heating block holding
  vials) is a `batch_reactor`. `mixer` is for devices that only mix and do not hold the sample during the
  reaction (shaker, vortex, sonicator).
- A cell or vessel in which the measurement takes place (electrochemical cell, cuvette) is part of that
  measuring instrument module (`instrument_*`); stirring or holding temperature in it just before the
  measurement are steps of that instrument module. Code the vessel as a reactor only if it is used for a
  reaction and the sample is then moved to another instrument.
- An autosampler attached to an HPLC/GC (sample tray + injection valve) is part of the
  `instrument_separation_ms` module; the injection is a `sample_aliquot` step of that module. A stand-alone
  pipetting robot that serves other instruments is a `liquid_handler`.
- Vendor control software of a pump, reactor or analyser is part of that device's module: not a separate
  `software` module and not a `generate_instructions` step. `software` modules are the programs the
  researchers use for analysis and planning.
- Robot arms, gantries and mobile robots are not modules (they are transfer modes) unless the arm itself
  performs a unit operation.
- A commercial integrated platform whose internal modules the paper does not reveal is ONE
  `commercial_integrated` module; never fill in its internals by guesswork.
- Off-platform equipment: module with on_platform = "no"; transfers to/from it are `human_transfer`
  (stated = "inferred") unless the paper says otherwise.

Connections: record ONLY
1. each movement of material between two different modules. Whenever consecutive steps on the same sample
   happen on different modules, record a material connection between them; if the paper does not state the
   move, set stated = "inferred" and use the transfer mode that device uses (robot arm, tubing, ...). With a
   robot, one connection per (from module, to module) pair moved within a cycle; a repeated move between the
   same pair is recorded once. If not even the transfer mode can be inferred, use "unmapped" with a note;
2. one `data_transfer` from each measuring module whose result is used for analysis/planning to the software
   module that receives it;
3. one `data_transfer` from the planning software to the module that executes the first step of the next
   cycle, even if the plan passes through an intermediate control computer or vendor software.
Do NOT record: links inside one module, cables/power between a cell and its instrument, waste lines,
database storage.

A class that does not fit: "unmapped" with unmapped_note. Never invent classes.

## Evidence location
`<doc> ; pdf p.<N> ; <locator>` where doc is `main` or `SI<k>`, N is the page from the block header,
locator is the most specific of `Fig. 2b`, `Table S3`, `Scheme 1`, `§<section> ¶<n>`. For an SI without
page headers use its own table-of-contents page and say so in paper.notes. One place per item; no quotes.
Where the same item is described in several places, use the place that first describes the hardware or
workflow systematically (usually a methods figure or table).

## Output
Write exactly one JSON file to the path given in your task, UTF-8, with this shape:
{
 "paper_id": "<paper_id>",
 "coder": "<label given in your task>",
 "paper": {"field_tag": "...", "sw_autonomy": 1|2|3, "hw_autonomy": 1|2|3, "hardware_location": "main|SI|both", "notes": "..."},
 "platforms": [{"platform_id": "<pid>/P1", "name": "...", "commercial_integrated": "yes|no", "campaigns": "...", "evidence": "..."}],
 "modules": [{"module_id": "<pid>/P1/M1", "module_type": "<class|unmapped>", "name_in_paper": "...", "on_platform": "yes|no", "evidence": "...", "unmapped_note": ""}],
 "steps": [{"step_id": "<pid>/P1/S1", "unit_operation": "<class|unmapped>", "module_ids": ["<pid>/P1/M1"], "performed_by": "robot|human|software", "evidence": "...", "unmapped_note": ""}],
 "connections": [{"edge_id": "<pid>/P1/E1", "from_module": "<pid>/P1/M1", "to_module": "<pid>/P1/M2", "transfer_mode": "<class|unmapped>", "stated": "stated|inferred", "evidence": "...", "unmapped_note": ""}]
}
field_tag, sw_autonomy and hw_autonomy follow `protocol/coding-guideline.md` §4.1 (field tags decide nothing).
Then run `python3 extraction/rehearsal/validate.py <your json>` and fix every error until it prints OK.
