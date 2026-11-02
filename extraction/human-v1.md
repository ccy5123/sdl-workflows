# Human-intervention extraction instructions v1 (frozen 2026-11-01, Spec sdl-db-05 v1; clarified once after a rehearsal on the 10 sdl-db-01 development papers)

You read ONE closed-loop self-driving-lab (SDL) paper and record two things: what the paper says about human
intervention during its closed-loop campaign, and the longest run without a person that the paper states.

## Inputs
- `extraction/inputs/<paper_id>/`: `main.txt` (main text, blocks headed `=== main pdf p.N ===`), `si_<k>.txt`
  (supplements, blocks headed `=== SI<k> pdf p.N ===`), `files.txt` (data/media supplements you cannot read).
  Read ALL of main.txt and the SI text before deciding.
- The record coding named in your task: its platforms, modules, steps (each with `performed_by`) and connections
  (each with `transfer_mode`). It tells you which steps and transfers the database already codes as done by a
  person. Use it to know where to look; your answer is about what the PAPER states.
- Use only these files and this page. Do not open any other coding or extraction output in the workspace.

## The rule that matters most
Record only what the paper states (text, tables, figure labels, SI). Do not estimate, do not take anything from
general knowledge or from another paper, and do not derive a number from other numbers. If the paper does not
say it, the answer is "not reported" / an empty list. That is a valid answer.

"The closed-loop campaign" means the campaign(s) in which the planner chose experiments from results (the
loops the record codes). Statements about building, calibrating or commissioning the platform, about a
non-closed-loop screen, or about work after the campaign (e.g. scale-up of the best result) do not count.
The campaign starts with its first closed-loop iteration and ends when the loop stops. One-time set-up before
the first iteration (loading the initial stock solutions or consumables, setting the target and bounds, choosing
the initial design or starting simplex, labelling data to train a model) and stopping the program at the end are
not intervention during the campaign. Work between iterations (refilling, moving samples, checking or editing a
result before the next round, restarting after a fault) is.

Count only what the paper says happened. An option the paper offers but does not say anyone used ("the run can
be cancelled manually") is not a human task. An action whose performer the paper does not name ("hyperparameters
were retuned", "seven conditions were rerun") is a human task only if the paper elsewhere says a person does it,
or the record coding codes that step or transfer as performed by a human. One exception: replenishing reagents or
consumables between iterations ("stock solutions were replaced every 12 h") counts as a human task unless the
paper says the platform itself did it during the campaign.

A capability statement is not a statement about the campaign: "the platform can run / enables / supports /
is designed for unattended operation", "up to 100 experiments per day without human intervention". It gives
neither `none_stated` nor an `unassisted_run_length`. A statement about the campaign actually run counts, even
without the words "human intervention": "the campaign ran autonomously without interruption for 69 h" is
`none_stated` with a 69 h run length. A statement that all the optimisations reported in the paper ran
unattended applies to each of them.

## Field 1: `human_intervention` (exactly one value)
Choose the FIRST value in this order whose condition holds:
1. `quantified`: the paper states a NUMBER for human involvement during the closed-loop campaign. Examples: a
   count of interventions ("the operator intervened 3 times"), person-time ("2 h of hands-on time per day",
   "about 10 min per batch to move plates"), a frequency of a human task ("a researcher refilled the reagents once a day",
   "a researcher loaded a new plate every 8 h"), or a number of human-performed actions per experiment or batch.
   A number about the platform alone (cycle time, robot time) does not count; the number must be about what
   people did.
2. `described`: the paper says which tasks people performed during the campaign (e.g. "samples were manually
   transferred to the XRD", "the user restocked vials", "a chemist checked each result before the next round"),
   but gives no number for them.
3. `none_stated`: the paper states explicitly that the closed-loop campaign ran without human intervention
   ("no human intervention was required during the 5-day campaign", "fully unattended"). A general claim such as
   "autonomous" or "self-driving" in the title or abstract, or a capability statement, is NOT enough; the
   statement must be about the campaign actually run.
4. `not_reported`: none of the above.

If the paper both describes human tasks and states a number for one of them, the answer is `quantified`.
If it says the campaign ran unattended except for a stated human task, the answer follows that task
(`quantified` if numbered, else `described`).

`human_intervention_evidence`: where the deciding statement is, as `<doc> ; pdf p.<N> ; <locator>` (doc is
`main` or `SI<k>`; N is the page from the block header; locator is the most specific of `Fig. 2b`, `Table S3`,
`§<section> ¶<n>`, with ¶ counted within the section). One place; no quotes. Empty string for `not_reported`.
A count of stops or interventions ("the run was stopped four times to refill consumables") is a number about
what people did, so it gives `quantified`.

## Field 2: `unassisted_run_length` (list with at most one entry)
The longest stretch the paper states the platform ran the closed-loop campaign WITHOUT a person, as a time or a
number of experiments: "ran unattended for 48 h", "completed 120 experiments without human intervention",
"operated autonomously over a weekend (60 h)". Entry: `{"value": <number > 0>, "unit": <unit>, "qualifier":
<text>, "evidence": <location as above>}`. Units: `s`, `min`, `h`, `d`, `week`, or `experiments`, `samples`,
`batches`. Give the value in the paper's own unit. A bound ("over 3 days", "at least 100 experiments") is recorded
as the number with `lower bound` / `upper bound` at the start of `qualifier`; "about X" as X with `approximately`;
a stated range as its midpoint with `range a-b <unit>`. The campaign's total length or total experiment count
counts ONLY if the paper says the whole campaign ran without a person. If several such statements exist, take
the longest one stated in time; if none is in time, the largest count. Mention the others in `notes`.
Empty list when the paper states none.

## Output
Write exactly one JSON file to the path given in your task, UTF-8:
{
 "paper_id": "<paper_id>",
 "coder": "<label given in your task>",
 "record_coding": "<path of the record coding you were given>",
 "human_intervention": "quantified" | "described" | "none_stated" | "not_reported",
 "human_intervention_evidence": "main ; pdf p.4 ; §2.3 ¶2",
 "unassisted_run_length": [{"value": 48, "unit": "h", "qualifier": "", "evidence": "main ; pdf p.5 ; §3 ¶1"}],
 "notes": "<your own words, no quotations: what the paper says about human involvement and why you chose the value>"
}
Then run `python3 extraction/human/validate.py <your json>` and fix every error until it prints OK.
