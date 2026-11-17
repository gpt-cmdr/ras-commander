# Research task template

Copy this into the study's TASK.md and replace the fields with the actual study design. This template does not authorize runs.

## Question and scope

Research question; hypothesis and predicted observable effect; research lens; exclusions; deliverable; definition of done; authorized operations and resource/run/time limits.

## Evidence and planning

HEC document/version/section/URL and the decision it informs; relevant library docs and notebook cells; observations and provenance; unresolved methodological choices. Separate demonstrated capabilities from proposed experiments.

## Baseline and design

Source model and immutable identity; working copies and output roots; HEC-RAS/library/backend versions; geometry/terrain/flow/plan identities; forcing and boundary conditions; initial conditions; CRS/datum/units/time basis; baseline run; varied parameters and ranges; fixed controls; random seed where relevant; scenario matrix; comparison metrics, thresholds and their justification; event IDs and frozen exploratory/calibration/held-out confirmation assignments made before tuning; role changes and lost independence; confounders and uncertainty.

## Human direction and adversarial review

Scientist's intended decision; authorized agency and modification scope; compute envelope; checkpoint triggers; competing explanations; falsification criteria; independent design reviewer and findings reviewer; objection ledger with evidence, discriminating tests and dispositions; unresolved scientist decisions. Record the strongest case against the preferred interpretation.

## Method-improvement experiments

Profile evidence and bottleneck; existing method/oracle; proposed Python/Rust change and package boundary; parity tolerances and failure checks; end-to-end benchmark design; compatibility/resource limits; reviewable diff; independent review; adoption or rejection rationale. Do not equate runtime improvement with physical validity.

## Worker packets

Worker ID and responsibility; bounded question; exclusive files; allowed reads/writes/compute; dependencies; maximum runs/concurrency/runtime; expected result-file path; required checks; stop conditions. Coordinator retains TASK/STATE ownership.

## Experiment receipt

Experiment ID and status (planned/running/completed/failed/interrupted); hypothesis revision; worker; start/end; reproducible command/config identity; input checksums; implementation commit and uncommitted diff identity; compiler flags and built Rust artifact hash where applicable; changed parameters; consumed-input checks; output/log paths and identities; completion and stability/mass-balance diagnostics; metrics and plots; failures; observations; interpretation; uncertainty; reviewer decision. Never promote a partial run to completed.

## Checkpoint and handoff

STATE.md: current accepted baseline, latest accepted experiment, active workers and reconciliation instructions, outstanding issues, exact next command/action, resource use and remaining authorized budget. PROGRESS.md: dated decisions and links to receipts, including rejected findings. Final report: answered questions, evidence, failed tests, limitations, reproducibility instructions, open work and stopped-worker accounting.
