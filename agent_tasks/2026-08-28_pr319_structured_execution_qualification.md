# PR 319 Structured Execution Evidence Qualification

## Objective

Build and execute an auditable qualification framework for draft PR #319,
`codex/structured-execution-evidence-integration`, against real HEC-RAS projects
and installed HEC-RAS versions. The framework must establish that
version-aware result selection, pre-compute cleanup, post-compute cleanup, and
structured execution evidence behave predictably without mutating any source
project.

This work updates the draft PR branch only. It does not target or merge to
`main`.

## Approval and hard gate

On 2026-08-28, the maintainer explicitly approved:

- writing the qualification task documents to disk;
- using subagents for independent fixture, harness, and adversarial review;
- building the qualification harness;
- running real HEC-RAS calculations against disposable staged project copies;
- continuing through analysis and draft-PR updates.

The approval applies only to the projects, plans, executables, and disposable
destinations enumerated in an execution packet. Original project folders are
immutable. Any materially different project, executable, destination, public
API change, release action, or destructive operation requires a new review of
scope and authority.

## Repository state

- Draft PR: <https://github.com/gpt-cmdr/ras-commander/pull/319>
- Head branch: `codex/structured-execution-evidence-integration`
- Base branch: `codex/structured-execution-evidence-test-base`
- Qualification-start head: `8b9eec5d`
- Qualification report root:
  `H:\CLB-Repos\ras-commander\working\pr319_execution_qualification_2026-08-28`
- Disposable engine workspace root:
  `C:\Users\billk_clb\AppData\Local\ras-commander\pr319_execution_qualification_2026-08-28`
- Qualification Python:
  `C:\Users\billk_clb\AppData\Local\ras-commander\pr319_execution_qualification_2026-08-28\.venv\Scripts\python.exe`
- Qualification Python launcher SHA-256:
  `340c0026b66e5a0bc487c8b6a4d7ef8c8319d139c6b5acd5639de76e53308070`

## Prior evidence and why it is not sufficient

The 2026-08-24 multi-version campaign produced 58 lanes across three project
types and 20 installed versions. It remains valuable captured-real evidence,
but it predates the opposing-result cleanup now in PR #319. Successful modern
1D computations commonly left both a plan HDF and a legacy `.O##` file, making
those staged outputs especially useful mixed-format regression inputs but not
proof that the new compute normalization works.

The old campaign also ran lanes in one long-lived Python process and treated
JSON/CSV as peer canonical outputs. The new framework uses one worker process
per lane and makes typed PyArrow/Parquet tables the canonical machine-readable
record.

## Runtime constraint and resolution

The repository contract prefers a repo-local `.venv`, but this checkout is on
an SMB/mapped-drive path from which Windows refuses to execute the generated
Python launcher (`Access is denied`). An attempted H-drive `.venv` is therefore
not a usable qualification interpreter and is not used by any lane.

The isolated interpreter instead lives under the approved local disposable
execution root shown above. It is built with `uv`, installs this exact worktree
editable with the repository's `full` feature set, and explicitly includes
pytest. Preflight confirmed Python 3.13.9, PyArrow 25.0.1, psutil 7.2.2, and an
editable `ras_commander` import from this exact H-drive worktree. Receipts must
record the interpreter path, launcher hash, Python version, PyArrow version,
psutil version, package import path, and git commit.

## Required fixture origins

Every artifact row must declare exactly one origin:

- `captured_real`: preserved output from an earlier real calculation;
- `generated_edge_case`: a deliberately constructed deterministic artifact
  state used to exercise a boundary condition;
- `staged_execution_output`: output produced by a current approved lane;
- `archived_failed_execution`: preserved evidence from a real attempted lane
  that failed or was blocked.

Generated edge cases must never be represented as observed HEC-RAS output.

## Source projects

| Project key | Plan | Plan title | Type | Immutable source project | Project-file SHA-256 |
|---|---:|---|---|---|---|
| `steady_1d` | `01` | Existing Conditions Run | Steady 1D | `C:\Users\billk_clb\Documents\HEC Data\HEC-RAS\Example Projects\1D Steady Flow Hydraulics\Chapter 4 Example Data\EX1.prj` | `c5c99ea7ff1a3636a72247b72030387c78cc73c6ea7dbd2721e476c936b0dade` |
| `unsteady_1d` | `06` | Unsteady Broad Crest S=10ft/mi | Unsteady 1D | `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\sources\Example 20 - HagerLatWeir_e01_multiversion_source\HagerLatWeir.prj` | `b83b0e03fe98056891887fb12cabf6d58d1ab9687c803eea3e0827a7a59bcda2` |
| `unsteady_2d` | `18` | 2D to 2D Run | Unsteady 2D | `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\sources\BaldEagleCrkMulti2D_e01_multiversion_source\BaldEagleDamBrk.prj` | `a112974c1216382971d60926aaf5f1d0324a4b3da0fe0309bd58e8d13f61a082` |

Before and after every campaign, the harness must hash the complete source
project bundle, not merely the `.prj` file. Any source hash change is a hard
failure and stops further engine execution.

## Qualification layers

1. **Deterministic contract and property tests**
   Exercise the complete artifact-state matrix, timestamp ties and tolerances,
   plan version parsing, engine/version disagreement, cleanup allowlists,
   failure atomicity, and serialization without launching HEC-RAS.
2. **Captured-real artifact replay**
   Inspect archived clean, mixed, failed, and incomplete outputs read-only.
3. **Representative local-engine pilot**
   Run the exact five-lane packet in
   `2026-08-28_pr319_pilot_execution_packet.md`.
4. **Cross-version transitions**
   Reuse a disposable staged copy through modern-to-legacy and
   legacy-to-modern transitions and verify the opposing result family is
   absent after each confirmed run.
5. **Expanded installed-version matrix**
   Run the 58 compatible project/version lanes once the pilot is sound.
6. **Transport and interruption qualification**
   Exercise local, network-source-to-local-stage, termination, timeout,
   failed-compute, and partial-artifact cases without weakening cleanup or
   evidence semantics.

## Core invariants

- **R1 — Source immutability:** no approved operation changes a source bundle.
- **R2 — Exact plan scope:** cleanup can remove only the selected plan's
  `.p##.hdf`, `.O##`, and documented message sidecars.
- **R3 — Engine ownership:** the selected executable or Controller determines
  the result family produced by a computation; plan declaration alone never
  authorizes opposing-family cleanup.
- **R4 — Fail closed:** unresolved or contradictory engine identity prevents
  permanent cleanup and prevents computation.
- **R5 — Pre-run normalization:** a modern run removes the selected plan's
  legacy result and stale message sidecars; a legacy run removes the selected
  plan's HDF and stale message sidecars.
- **R6 — Post-run normalization:** after confirmed completion, an opposing
  result recreated by HEC-RAS is removed while current message evidence is
  retained.
- **R7 — Failure preservation:** a failed or interrupted calculation is not
  reported as completed. Its observations remain available for diagnosis and
  are labeled as failed execution evidence.
- **R8 — Read-only inspection:** inspection never deletes, rewrites, or merges
  result artifacts.
- **R9 — Declared-version selection:** with both families present, inspection
  uses the declared plan family only when the opposing artifact is not newer;
  apparently newer opposing evidence raises `ResultArtifactAmbiguityError`.
- **R10 — Timestamp humility:** modification time is treated as a conservative
  ambiguity signal, not proof of calculation chronology. Exact ties and
  filesystem-resolution tolerances are explicit test cases.
- **R11 — Process isolation:** each engine lane runs in a fresh Python worker;
  no COM, JVM, PyArrow, pandas, or ras-commander global state crosses lanes.
- **R12 — Typed audit trail:** lane, artifact, observation, and event tables are
  written through PyArrow with declared schemas and validated on readback.

## Canonical outputs

The report root must contain:

- `manifest.parquet`: immutable lane intent, source identity, engine identity,
  destination, and expected outcome;
- `lanes.parquet`: one terminal row per lane;
- `artifacts.parquet`: before/prepared/after/finalized artifact observations;
- `observations.parquet`: structured execution-evidence fields and conflicts;
- `events.parquet`: ordered worker and supervisor events;
- `summary.md`: human review summary generated from the Parquet data;
- `logs/<lane_id>/`: stdout, stderr, and ras-commander logs;
- `workers/<lane_id>/`: small recovery envelope written atomically by the
  isolated worker if Parquet publication is not possible.

JSON may be used only as an atomic per-worker recovery envelope. It is not a
peer canonical result format. CSV is not a qualification output.

## Lane lifecycle

1. Supervisor verifies repository commit, source bundle, executable hash, and
   absence of active HEC-RAS processes through ras-commander APIs.
2. Supervisor creates a unique local disposable destination.
3. Worker stages the complete project through ras-commander and verifies the
   source is unchanged.
4. Worker initializes the project with the packet's explicit version and
   executable/controller.
5. Worker inventories the selected plan's artifact state.
6. Worker invokes only `RasCmdr`, `RasControl`, or another focused
   ras-commander execution API. Direct `Ras.exe` subprocess calls are forbidden.
7. Worker records preparation, execution, finalization, and read-only evidence
   observations.
8. Worker closes owned processes and writes its recovery envelope atomically.
9. Supervisor verifies no process survives, validates the staged artifacts,
   ingests the envelope into typed PyArrow tables, and reads the Parquet tables
   back before accepting the lane.
10. Supervisor rehashes the source bundle.

## Stop conditions

Stop dispatching new engine lanes immediately if any of the following occurs:

- a source bundle hash changes;
- a lane addresses an unlisted project, plan, executable, or destination;
- a cleanup candidate escapes the staged project root or selected plan;
- the selected executable/controller cannot be resolved exactly;
- an owned HEC-RAS process survives cleanup;
- a worker times out without confirmed process-tree termination;
- the harness cannot persist and read back the lane audit record;
- two lanes would share a writable project directory;
- evidence reports completion from an artifact that predates the lane start;
- a result contradicts an invariant in a way that could expose later source
  data or processes to mutation.

A numerical or application failure confined to a disposable lane is recorded
and may allow the campaign to continue after the supervisor proves containment.

### Current host hold

The 2026-08-28 read-only preflight through `RasControl.list_processes()` found
an unrelated untracked HEC-RAS process, PID 320624, associated with
`UPGU3.prj`. Qualification must not terminate or adopt that process. No real-
engine lane may start while it remains active because process ownership and
engine attribution would be ambiguous. Deterministic, staging, and offline
inspection work may continue because it does not dispatch HEC-RAS or COM.

## Required reviews and work products

- Fixture inventory:
  `agent_tasks/2026-08-28_pr319_qualification_fixture_inventory.md`
- Exact captured-output replay packet:
  `agent_tasks/2026-08-28_pr319_captured_replay_packet.md`
- Harness design:
  `agent_tasks/2026-08-28_pr319_qualification_harness_design.md`
- Adversarial matrix:
  `agent_tasks/2026-08-28_pr319_qualification_adversarial_plan.md`
- Exact pilot packet:
  `agent_tasks/2026-08-28_pr319_pilot_execution_packet.md`

The three independent review documents must be reconciled into this task before
engine execution. Findings that challenge the packet or invariants take
priority over schedule.

## Independent-review reconciliation

The 2026-08-28 reviews are complete. They changed the execution order and
raised two hard pre-engine blockers.

### Fixture inventory findings

- The 58 canonical prior lanes contain 34 completed, 15 blocked, and 9 failed
  records.
- The 34 completed lanes comprise 4 clean legacy-only outputs, 10 clean
  HDF-only 2D outputs, and 20 mixed modern 1D outputs.
- In every mixed modern 1D lane, `.O##` is 1.065 to 1.929 seconds newer than the
  HDF. These are high-value captured-real ambiguity inputs and cannot be used
  as clean post-normalization baselines.
- All 20 installed executable paths and SHA-256 values still match the prior
  manifest.
- The Hager and Bald Eagle sources need stronger long-term extraction receipts,
  although their exact current fingerprints are known and adequate for this
  immutable qualification run.

### Harness-design findings

- The qualification harness will be tracked under
  `scripts/qualification/execution_evidence/` and tested under
  `tests/qualification/`.
- Immutable per-attempt receipts are the recovery source of truth. Only the
  supervisor writes aggregate PyArrow/Parquet tables.
- Real-engine lanes are serialized and isolated in fresh Python processes.
- `RasCmdr.compute_plan()` does not currently expose a public hard timeout.
  The supervisor must therefore time-bound the worker and use only
  plan-scoped `RasCmdr.cancel_plan()` for cancellation; raw process-name kills
  are prohibited.

### Adversarial findings and current hard stop

The adversarial matrix defines 16 safety invariants and 93 cases. Two P0 risks
must be closed with deterministic tests before the first HEC-RAS lane:

1. `RasControl.run_plan()` may reach final opposing-family cleanup after a
   calculation attempt when Controller completion polling or process ownership
   is uncertain. Final cleanup requires positive solver quiescence.
2. The modern solver-state query compares a literal `.tmp.hdf` command-line
   spelling. Equivalent mapped-drive, UNC, 8.3-name, symlink/junction, relative,
   or wildcard-containing paths can produce a false `stopped` result. A query
   must prove equivalence or return `unknown`; it must never infer stopped from
   a spelling mismatch.

No real-engine lane may run while either P0 item is open.

The direct-modern source risk is closed at the deterministic gate:

- the modern solver-state query now uses tokenized `psutil` command lines,
  process working directories, normalized literal paths, and
  `os.path.samefile()` identity checks. Access, parsing, enumeration, cwd, or
  identity uncertainty returns `None`; only a fully inspected nonmatch returns
  `False`.

The first `RasControl.run_plan()` patch correctly requires a valid blocking
return or `Compute_Complete() == True` before cleanup and preserves opposing
artifacts on compute/poll exceptions. Cross-review then found and fixed two
remaining P0 paths: finalization when Controller close reported an owned
process survived, and the absence of an internal `max_runtime` deadline when
the external watchdog was unavailable. Finalization now requires both solver
quiescence and a positively safe Controller/session close; the nonblocking loop
uses a monotonic deadline checked before and after every completion query.

API-consistency review found and fixed one final strict-mode edge: a strict
`QuitRas()` failure during the preliminary current-results check could be
downgraded to a normal currency-query error and proceed to computation. The
strict-mode exception now propagates before detailed-logging mutation or a
compute session starts; default non-strict currency-query fallback remains
compatible and covered.

The isolated full-feature qualification interpreter passes 147 combined
RasControl/direct-compute/cleanup/evidence tests after an initial lean-
environment run correctly classified seven missing-extra failures
(`geopandas` and `setuptools`) as environment setup, not branch defects. The
RasControl P0 gate is closed deterministically. The real-engine stop remains in
force until harness adversarial hardening and captured-artifact replay are
complete.

### Revised rollout

1. Finish the pre-engine harness foundation and all deterministic P0 cases.
2. Stage the three pristine `captured_real` model sources, overlay and inspect
   the exact `staged_execution_output` allowlists for the 13 archived anchors:
   four legacy-only, six mixed modern 1D, and three HDF-only 2D.
3. Run the exact five-lane smoke packet only after the P0 stop is lifted.
4. Expand that fresh packet to the full 13 representative lanes: steady and
   unsteady 1D at 4.0 and 4.1, plus all three plan types at 6.1, 6.6, and 7.0.
5. Repeat the 13 representative lanes from independent fresh stages.
6. Extend to the remaining successful 6.x/6.7 engines, then investigate 5.x and
   6.0 exact-controller failures as a separately reviewed lane group.
7. Rebuild the 58-lane installed-version matrix only after the representative
   gates pass.

## Completion criteria

- deterministic and captured-real suites pass in isolated processes;
- the five-lane pilot has complete, read-back-verified Parquet evidence;
- both result-family transitions satisfy pre- and post-run normalization;
- the compatible 58-lane matrix is either complete or each non-complete lane
  has a reproducible, contained, version-specific explanation;
- representative successful staged projects open with a single expected
  result family and credible structured evidence;
- source bundles remain byte-identical;
- docs, focused tests, and the repository suite are rerun proportionately;
- findings, residual risks, and confidence are documented in the draft PR;
- no merge to `main` occurs as part of this qualification task.

## Progress log

- 2026-08-28: maintainer approved the framework, real disposable-copy runs,
  durable task documents, subagent reviews, and continued execution.
- 2026-08-28: goal created; fixture-inventory, harness-design, and adversarial
  review agents started.
- 2026-08-28: source project and representative executable hashes revalidated
  read-only against the prior manifest.
- 2026-08-28: independent fixture inventory completed: all prior modern 1D
  successes are mixed-format and therefore replay inputs, not cleanup passes.
- 2026-08-28: process-isolated PyArrow harness design completed and the tracked
  pre-engine implementation assigned.
- 2026-08-28: adversarial review found two P0 quiescence/process-identity risks;
  real HEC-RAS execution paused and independent fixes assigned.
- 2026-08-28: focused pre-engine baseline passed: 65 tests in
  `test_execution_evidence.py` and `test_execution_artifact_cleanup.py`.
- 2026-08-28: first-pass P0 fixes added. Independent root reruns passed 53
  RasControl-focused tests and 67 direct-compute/cleanup tests. No HEC-RAS
  process was launched.
- 2026-08-28: independent cross-review reopened the RasControl gate for owned
  process survival during close and a missing internal poll deadline; follow-up
  fix and tests assigned before any real-engine work.
- 2026-08-28: repo-local virtual environment proved non-executable on the SMB
  checkout. Created and pinned an isolated uv environment under the approved
  local execution root with compute, PyArrow/GeoParquet, and pytest support.
- 2026-08-28: the isolated lean environment produced 101 passes and 7 missing-
  dependency failures. Installed the repository's full feature set and reran
  the same combined suite: 108 passed.
- 2026-08-28: pre-engine qualification foundation completed and independently
  rerun in the isolated interpreter: 62 passed. It includes exact Arrow
  schemas, atomic receipts, stable snapshots, locks, R01-R12 evaluation,
  deterministic Parquet aggregation, reports, and manifest preflight.
- 2026-08-28: final API-consistency review found a strict-close exception that
  could be swallowed during the currency check; fix and regression assigned.
- 2026-08-28: strict-close currency path fixed; default non-strict behavior
  retained. Isolated integrated deterministic suite passed 147 tests.
- 2026-08-28: adversarial harness review found receipt/path/lock/aggregate
  hardening gaps. No raw HEC-RAS launch path exists, but the no-engine gate stays
  closed until those gaps and strict manifest allowlists are covered.
- 2026-08-28: read-only host process preflight found unrelated untracked
  HEC-RAS PID 320624 (`UPGU3.prj`); live qualification dispatch placed on hold
  without touching that process.
- 2026-08-28: adversarial foundation hardening closed reparse-root,
  no-overwrite publication, stable-hash, lock-ownership, aggregate-coherence,
  schema-metadata, command-smuggling, and provenance-validation gaps. The
  remaining portable Windows quarantine compare/unlink race is documented and
  fails closed for ordinary replacement races.
- 2026-08-28: the captured-output replay packet pinned 13 archived lanes and
  30 exact result/message files. Current policy predicts ten successful
  inspections and three exact
  `program_version_unresolved_multiple_formats` failures; every copied engine
  artifact remains labeled `staged_execution_output`.
- 2026-08-28: the no-engine worker now stages only pristine source projects
  through `stage_project()`, overlays exact hash/size/mtime-pinned replay files,
  runs inspection in fresh Python processes, and records action-scoped
  invariants and typed receipts. Replay and source roots must be disjoint.
- 2026-08-28: independent deterministic reruns passed 147 affected
  RasControl/RasCmdr/evidence tests and 145 qualification-framework tests.
  Qualification-record hard-link publication was also proved on the approved
  H-drive audit root. No HEC-RAS or COM process was launched by these tests.
