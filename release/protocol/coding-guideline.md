<!-- English translation of the frozen coding guideline v1 (original in Korean). See README.md in this folder. -->

# Coding guideline for the sdl-db-01 gold set (v1, frozen)

- Written 2026-10-20 (v0); frozen as v1 on 2026-10-21 after revisions v0.1–v0.3. Not changed during test coding
- Basis: Spec `sdl-db-01`, version 3 (spec_digest `d31ab42d…a3d471`)
- Form: `protocol/coding-template.xlsx` (one file per paper); LLM coders write JSON (`extraction/prompt-v1.md`)

This guideline sets how to read one published closed-loop SDL paper and transfer it into tables of
**platform -> module -> step -> connection**. Under Spec version 3 the gold set is coded with this guideline by the
reference LLM coder Fable 5.1. The extractor (Opus 5.5) follows the same guideline.

- H1 checks whether two independent codings under the same instructions agree.
- H3 compares the extraction with the reference coding. The two models are of the same family, so agreement may
  overestimate accuracy. To check this, the researcher codes 3 test papers personally (diagnostic, not used for the
  decision).

---

## 1. Rules that cannot change, and what may be refined

**Rules frozen in the Spec**: marked [frozen] in this guideline. Changing them needs amend-spec.

- The coding units and hierarchical ids (section 3)
- Every item carries an evidence location (section 5)
- The pairing rule (section 6)
- No class is added during test coding. An item that does not fit is coded unmapped with a free-text note
- An item placed in an "other / miscellaneous" kind of class counts as unmapped, so no such class is created
- The six discriminating cases must be in the test set (section 8)
- Re-coding is done on 10 test papers, as an independent run that does not see the original coding (section 9,
  Spec version 3)

**Refined while coding the 10 development papers**: marked [v0].

- The class lists of section 7 (unit operations, module types, transfer modes)
- Detailed judgment rules such as how finely to split steps and when to split platforms

After the 10 development papers, the class lists and judgment rules are frozen as **taxonomy version 1**. The hash of
this guideline is recorded, and then the 30 test papers are coded.

---

## 2. Order of work

1. **Receive the split lists.** The list of 40 papers (10 development, 30 test) and the list of 10 re-coding papers
   are drawn with recorded seeds and kept as Evidence. Coding starts after that.
2. **Code the 10 development papers.** Classes that are missing are added or changed at this stage. Changes are
   written in `protocol/taxonomy-changelog.md` with date and reason.
3. **Freeze taxonomy version 1.** Fix the class lists and this guideline and record their hashes. The class
   correspondence table to Leong et al. 2022 is made at the same time.
4. **Code the 30 test papers.** Classes are not changed. Record the coding date of each paper.
5. **Keep extraction apart from the reference coding.** The reference coder and the extractor do not see each other's
   output. The extraction prompt is refined on the 10 development papers only.
6. **Re-code 10 papers.** A new session codes from scratch under the same instructions; method in section 9.
7. **Human check of 3 papers.** The researcher codes 3 test papers, drawn with a recorded seed, personally, without
   seeing the LLM output for those papers.

---

## 3. Coding units and ids [frozen]

| Unit | Id format | Example | Meaning |
|---|---|---|---|
| Paper | `paper_id` | `Bai2023` | sci-adk citation key; the key of `references.bib` as it is |
| Platform | `paper_id/P<n>` | `Bai2023/P1` | A paper may have several |
| Module | `paper_id/P<n>/M<k>` | `Bai2023/P1/M3` | One piece of equipment or one work place |
| Step | `paper_id/P<n>/S<k>` | `Bai2023/P1/S5` | One unit operation, with the ids of the modules it uses |
| Connection | `paper_id/P<n>/E<k>` | `Bai2023/P1/E2` | One transfer between modules, with source and target module and transfer mode |

- Numbers start at 1. Step numbers `S<k>` follow the **workflow order**; pairing rule 2 uses this order.
- Module numbers `M<k>` and connection numbers `E<k>` follow the order of first mention in the paper.
- The integration mode of a paper is not coded; it is computed from the connection labels. For example, flow if every
  connection is fixed tubing, mixed if they are mixed.

---

## 4. What to record (the fields of each sheet of the form)

### 4.1 papers (one row per paper)
| Field | Content |
|---|---|
| paper_id | Citation key |
| doi | DOI of the paper |
| set | dev / test / recode |
| coder_date | Date of coding (YYYY-MM-DD) |
| field_tag | Field tag (7.4). Not used for any decision |
| sw_autonomy | Software autonomy category of Tom et al. 2024. 1 = one experiment from a data-driven design, 2 = closed-loop iteration in which results choose the next experiment, 3 = closed-loop iteration over an algorithm-generated search space |
| hw_autonomy | Hardware autonomy category of Tom et al. 2024. 1 = a device doing one kind of task, 2 = a workflow joining several tasks, 3 = a fully automated laboratory running varied experiments without human intervention |
| hardware_location | Where the hardware is described: main / SI / both |
| notes | Points where the judgment was unclear |

Levels 1–5 are computed from the two categories (Tom et al. 2024, Fig. 1); they are not recorded directly.

### 4.2 platforms
| Field | Content |
|---|---|
| platform_id | `paper_id/P<n>` |
| name | The name the paper uses (empty if none) |
| commercial_integrated | yes for a commercial integrated platform (section 8, case 3) |
| campaigns | Names or targets of the campaigns run on this platform (free text) |
| evidence | Evidence location (section 5) |

### 4.3 modules
| Field | Content |
|---|---|
| module_id | `paper_id/P<n>/M<k>` |
| module_type | Chosen from the list in 7.2; `unmapped` if none fits |
| name_in_paper | As written in the paper (e.g. "Opentrons OT-2", "hotplate") |
| on_platform | no for equipment outside the platform (section 8, case 6) |
| evidence | Evidence location |
| unmapped_note | When unmapped, what did not fit |

### 4.4 steps
| Field | Content |
|---|---|
| step_id | `paper_id/P<n>/S<k>` (workflow order) |
| unit_operation | Chosen from the list in 7.1; `unmapped` if none fits |
| module_ids | Ids of the modules that performed the step; several separated by `;` |
| performed_by | robot / human / software |
| evidence | Evidence location |
| unmapped_note | Explanation when unmapped |

### 4.5 connections
| Field | Content |
|---|---|
| edge_id | `paper_id/P<n>/E<k>` |
| from_module, to_module | Module ids |
| transfer_mode | Chosen from the list in 7.3; `unmapped` if none fits |
| stated | stated if the paper states the transfer mode, inferred if it was inferred from context |
| evidence | Evidence location |
| unmapped_note | Explanation when unmapped |

---

## 5. How to write evidence locations [frozen]

Pairing rule 1 is "same evidence location, same pair". Evidence locations are therefore written **down to the smallest
unit**, always in the same format.

Format: `main|SI ; p.<page> ; <locator>`

- The locator is the most specific of: `Fig. 2b`, `Table S3`, `§2.1 ¶3` (section 2.1, third paragraph), `Scheme 1`
- Examples: `main ; p.4 ; Fig. 1b` / `SI ; p.12 ; Table S4` / `main ; p.2 ; §2 ¶2`
- The page is the **PDF page number**, written with `pdf p.` as in `main ; pdf p.4 ; Fig. 1b`. Printed page numbers
  differ between versions and are not used [v0.1]. Several SIs are told apart as `SI1`, `SI2`. For an SI without page
  marks (docx and the like), use the page numbers given in the SI's table of contents and say so in the notes.
- When an item is described in several places, record only **the one place that describes it most directly**.

Sentences of the paper are not copied (copyright); only the location is recorded.

---

## 6. Pairing rule [frozen]: why order and evidence location matter

Re-coding (H1) and LLM scoring (H3) pair the steps and connections of two codings in this order.

1. Items with the same evidence location (same paragraph, figure or table) are a pair.
2. Items with different evidence locations are a pair only if they are in the same position of the workflow order
   within the same platform and in the same unit-operation family.
3. Items without a pair count as misses or extras.

Detail (Spec version 3): when one evidence location holds several items, first pair items of the same platform and the
same family in order, then pair the rest in order. The family is the unit-operation family for steps and the pair of
source and target module types for connections.

What to keep in mind while coding:
- When the same content is described in several places, choose by the same criterion every time. The default is
  **the place that first describes the hardware and workflow systematically** (usually a figure or table of the
  methods section).
- The step order follows the actual execution order, not the order of description in the paper.

---

## 7. Taxonomy [v1 frozen, `protocol/taxonomy-v1.json`]

No new vocabulary is invented. Terms follow XDL (Mehr et al. 2020), WeChemSynOntology (Schilling et al. 2026) and the
MAP workflow framework of Leong et al. 2022. Below is the starting list. **There is no "other" class.** An item that
does not fit is coded `unmapped` with a reason.

### 7.1 Unit operations (family -> class)

The family is the "unit-operation family" of pairing rule 2. The class correspondence to XDL, WeChemSynOntology and
Leong et al. 2022 is in `protocol/taxonomy-correspondence.md`.

| Family | Class | Includes |
|---|---|---|
| plan | `plan_next_experiment` | An algorithm selects the conditions of the next experiment |
| | `generate_instructions` | The selected conditions or design are converted into machine instructions (G-code, robot script). Only when the paper describes this as a separate step [v0.1] |
| prepare (dispensing, preparation) | `dispense_liquid` | Liquid dispensing, reagent addition |
| | `dispense_solid` | Weighing and adding a solid |
| | `prepare_substrate` | Substrate cleaning, drying, pretreatment |
| | `clean_equipment` | Rinsing flow paths, nozzles or vessels with solvent between experiments [v0.1] |
| mix | `mix` | Stirring, shaking, mixing |
| | `sonicate` | Ultrasonic dispersion |
| react (reaction, heat treatment) | `react_thermal` | Leaving the reaction at a set temperature (room temperature included) [v0.3] |
| | `react_flow` | Reaction inside a flow reactor |
| | `react_photo_electro` | Light irradiation, electrochemical synthesis, UV curing |
| | `anneal` | Heat treatment of a film or solid |
| | `cool_quench` | Cooling, stopping a reaction |
| | `preheat` | Bringing a flow or vessel to temperature before the reaction (preheater) [v0.1] |
| separate (separation, purification) | `filter` | Filtration |
| | `centrifuge` | Centrifugation |
| | `wash_extract` | Washing, extraction, phase separation |
| | `evaporate_dry` | Evaporation, drying |
| | `purify` | Chromatographic purification and the like |
| form (forming, fabrication) | `deposit_coat` | Spin, drop or blade coating, printing |
| | `assemble_device` | Coin-cell assembly, device fabrication |
| measure | `measure_optical` | Spectroscopy such as UV-vis, PL, IR, Raman |
| | `measure_structural` | XRD, XPS, NMR and the like |
| | `measure_separation_ms` | Analysis such as HPLC, GC, MS |
| | `measure_imaging` | Microscope or camera images |
| | `measure_electrochemical` | Electrochemical measurement, conductivity |
| | `measure_physical` | Physical properties such as mass, thickness, viscosity, pH |
| analyze | `analyze_data` | Computing the target value from measurements, updating a model |
| handle (sample management) | `handle_sample` | Opening and closing caps, labelling, storage |
| | `sample_aliquot` | Taking part of a sample for analysis, in-line injection valve [v0.1] |

**Criteria for splitting steps [v0]**
- One step = one unit operation done by one module (or a person).
- When the same module does the same operation consecutively, it is one step. Example: reagents A, B, C dispensed one
  after another -> one `dispense_liquid`.
- A repeated experiment is coded for **one cycle** only. Even if it ran 13 times, the workflow is recorded once.
- Process conditions (temperature, time, amounts) are not recorded.

### 7.2 Module types

| Class | Examples |
|---|---|
| `liquid_handler` | Pipetting robot, dispensing head |
| `solid_dispenser` | Powder dispenser, automated balance |
| `fluidics` | Syringe and peristaltic pumps, valves (flow system) |
| `batch_reactor` | Vial or well-block reactor; a stirrer or heating block on which vials stay during the reaction (may include heating and stirring) [v0.3] |
| `flow_reactor` | Tube or chip flow reactor |
| `thermal_unit` | Hotplate, oven, furnace, chiller |
| `mixer` | A device that only mixes, such as a shaker, vortex mixer or ultrasonicator [v0.3] |
| `separation_unit` | Centrifuge, filtration device, evaporator |
| `coating_printing_unit` | Spin coater, blade coater, printer |
| `assembly_unit` | Assembly device such as a coin-cell crimper |
| `instrument_optical` | Spectrometer (UV-vis, PL, IR, Raman) |
| `instrument_structural` | XRD, XPS, NMR |
| `instrument_separation_ms` | HPLC, GC, MS |
| `instrument_imaging` | Microscope, camera |
| `instrument_electrochemical` | Potentiometer, impedance analyser |
| `instrument_physical` | Balance, thickness gauge, pH meter |
| `storage` | Rack, hotel, refrigerated storage |
| `sample_handling_station` | Capping and decapping device, plate sealer, waiting deck [v0.1] |
| `commercial_integrated` | Commercial integrated platform whose internal configuration is not disclosed (e.g. Chemspeed) |
| `software` | Program for experiment planning or data analysis |
| `human` | A work place where a person works by hand |

**Robot arms, gantries and mobile robots are not recorded as modules [v0].** They are recorded as the transfer mode of
a connection (7.3). But if a robot arm itself carries out an operation (for example, dispensing with a pipette on the
arm), it is also recorded as the module that does that operation.

### 7.3 Transfer modes (connections)

| Class | Meaning |
|---|---|
| `fixed_tubing` | Flow through a fixed tubing connection |
| `robot_arm_gantry` | Fixed robot arm, XYZ gantry, rail |
| `mobile_robot` | Mobile robot |
| `human_transfer` | A person carries it |
| `data_transfer` | Data, not a sample, is passed on (instrument -> software -> planning) |

### 7.5 What becomes an item [v0.1, settled in the development rehearsal]

Steps
- Record only steps executed in every cycle of the loop. Preparation done once before a campaign (stock solutions,
  catalyst packing, mobile-phase preparation, calibration) is not recorded as a step but noted in the papers notes.
- When the same software does analysis and planning, record two steps, `analyze_data` and `plan_next_experiment`, on
  that one module.

Modules
- The pumps, valves and tubes of one fluid supply system are grouped as one module (`fluidics`). The tubes inside it
  are not recorded as connections.

Connections: record only these three kinds.
1. Material moving between two different modules (transfer mode chosen from 7.3)
2. When a measurement result is used for a judgment (analysis, planning), one `data_transfer` from that measurement
   module to the software module that receives the result
3. One `data_transfer` from the planning software to the module that executes the first step of the next cycle

Not recorded: connections inside one module, wires and power between a measurement cell and its instrument, waste
lines, database storage.

**Rules added in v0.2 (settled in rehearsal v1)**

Steps
- **Cleaning is a step only when it is in the sequence of every cycle.** If cleaning appears within the execution
  order of one experiment (cycle), whether in the main text, the SI or a status log, record it as a `clean_equipment`
  step. Cleaning done once at the start or end of a campaign, or mentioned only as maintenance, goes into the notes.
- **When dispensing and mixing alternate.** Dispensing done consecutively by the same module with no other operation
  in between is one step, however many reagents. If another operation (mixing, heating, moving) comes in between, the
  dispensing after it is a new step. If the paper does not state the order, do not split.

Modules
- **The cell or vessel in which a measurement takes place is part of the measurement instrument module.** A cell into
  which the sample is poured and measured with electrodes or an optical path (e.g. an electrochemical cell, a cuvette)
  is not recorded as a separate module but included in that instrument module (`instrument_*`). Stirring or holding a
  temperature in that cell right before the measurement is also recorded as a step of that module. If the cell is also
  used as a reaction vessel without measuring (moved to another instrument after the reaction for measurement), record
  it as a reactor.
- **An autosampler attached to an analytical instrument is part of that instrument module.** An HPLC or GC autosampler
  (sample tray + injection valve) is included in the `instrument_separation_ms` module, and the injection is recorded
  as that module's `sample_aliquot` step. An independent pipetting robot that also handles samples for other
  instruments is a `liquid_handler`.

Connections
- **Material moved by a robot is recorded once per source–target module pair.** When the same robot arm moves between
  several modules, each move is one connection. If moves of the same source–target pair repeat within one cycle,
  record one.

**Rules added in v0.3 (settled in rehearsal v2)**

Steps
- **Reaction time is `react_thermal` even at room temperature.** The time for which the reaction is left to proceed
  after all reagents are added (with stirring included) is recorded as `react_thermal`. `mix` is used only for short
  mixing between additions or right before a measurement.
- **A step that takes part of a sample for analysis is `sample_aliquot` even with dilution.** This includes mixing the
  taken sample with solvent and sending it to the analyser.
- **Software steps go at the end of the cycle.** The cycle starts with the first physical step and ends with
  `analyze_data` -> `plan_next_experiment` -> `generate_instructions`, in this order.

Modules
- **A unit the paper names as a group is one module only when its parts are joined into one flow path or one
  assembly.** For example, if the preheating coil, micromixer and reactor inside a "reaction module" form one flow path
  joined by tubing, record one module and the operations inside it as steps of that module. Even if named as a group,
  separately operating devices to which a robot or person carries samples (e.g. a pump dispenser, a robot-arm pipette,
  a stirrer) are split by device. If the paper does not group them, one physically separate device is one module.
  [refined in v1]
- **A device on which the reaction vessel stays during the reaction is a `batch_reactor`.** If the reaction proceeds on
  a stirrer or heating block holding vials, record `batch_reactor`. `mixer` is for devices that only mix and do not
  hold the sample during the reaction time (shaker, vortex mixer, ultrasonicator).
- **The equipment maker's control software is part of that equipment module.** Maker control programs of pumps,
  reactors or analysers are not recorded as a separate `software` module or a `generate_instructions` step. The
  `software` module is for programs the researchers used for planning and analysis.

Connections
- **When consecutive steps of the same sample happen on different modules, record a material connection between
  them.** If the paper does not describe the move, set `stated` = inferred. The transfer mode is the one that equipment
  uses (robot arm, tubing, ...).
- **The `data_transfer` sending the planning result goes to the module that executes the first step of the next
  cycle.** Even through an intermediate control computer or maker software, the target is that executing module.

### 7.4 Field tags (not used for decisions)
`chemistry_synthesis`, `materials_inorganic`, `materials_thin_film`, `materials_polymer_soft`, `nanomaterials`,
`battery_electrochem`, `catalysis`, `biology_biochem`, `analytical_chemistry` (optimisation of analytical methods such
as HPLC or flow-injection analysis). Two or more are joined with `;`.

---

## 8. Difficult cases (six discriminating cases) [frozen: must be in the test set]

| # | Case | How to code |
|---|---|---|
| 1 | Hardware described only in the SI | Read the SI to the end. Write evidence locations as `SI ; …` and set the paper's `hardware_location` to SI |
| 2 | Several platforms or campaigns in one paper | A different module composition is a different platform (P1, P2). Campaigns that change only the target on the same equipment are one platform, listed in `campaigns` [v0] |
| 3 | Commercial integrated platform with undisclosed internals | Record one module (`commercial_integrated`). Record internal modules separately only when the paper discloses them. **Do not fill in the internal configuration by guessing** |
| 4 | Human involvement only implied ("transferred manually") | Record a `human_transfer` connection with `stated` = inferred. If a person carried out an operation, set that step's `performed_by` to human |
| 5 | Fixed flow connections mixed with a robot arm | Record each connection separately. Do not lump them into a paper-level label |
| 6 | Closed loop with some steps done off the platform (e.g. the vacuum annealing of Bai 2024) | Record the outside equipment as a module too, with `on_platform` = no. The connections to and from it are `human_transfer`, `stated` = inferred, unless the paper says otherwise |

---

## 9. Re-coding procedure (H1) [frozen, Spec version 3]

1. The 10 papers to re-code were drawn from the 30 test papers with a recorded seed (split Evidence).
2. After the hash of the original (first) coding is recorded, a new-session subagent codes from scratch under the same
   instructions (second coding). No 14-day gap is kept.
3. The second coder receives only the paper inputs and the instructions; it is not told where the first coding, notes
   or extraction output are.
4. The second coding is saved in a different folder from the first.

---

## 10. Do not

- Add or change classes during test coding (code unmapped instead)
- Create classes such as "other", "misc"
- Correct the gold coding after looking at LLM extraction output
- Fill in internal configurations or transfer modes the paper does not give by guessing (if inferred,
  `stated` = inferred)
- Copy sentences of the paper into the tables (record only locations)

---

## 11. Settled when taxonomy version 1 was frozen

1. **When the paper gives no transfer mode.** Infer the most plausible mode and set `stated` = inferred. If even that
   is not possible, code `unmapped` with a note. No class such as "not described" is created.
2. **Planning and analysis steps count as steps.** `analyze_data` and `plan_next_experiment` are steps (7.5).
3. **Criterion for splitting platforms and campaigns.** A different module composition is a different platform.
   Campaigns that change only the target on the same equipment are listed in one platform's `campaigns` (section 8,
   case 2).
4. **Robot arms are not modules.** A robot arm is a transfer mode. If the arm itself carries out an operation, record
   it as the module doing that operation (7.2).
5. **Correspondence table.** The class correspondence to XDL, WeChemSynOntology and Leong et al. 2022, with a
   reference column for OntoLab and SAREF (Bai et al. 2024), is kept in `protocol/taxonomy-correspondence.md`.
