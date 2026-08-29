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

The exact representative lanes, engine identities, live-run invariants, and
audited additive process/cancellation/provenance API prerequisite are recorded
in `agent_tasks/2026-08-29_pr319_live_execution_packet.md`. The additive API is
implemented and tested only on this draft branch; its exact public names and
compatibility posture remain a highlighted merge-review decision.

## Repository state

- Draft PR: <https://github.com/gpt-cmdr/ras-commander/pull/319>
- Head branch: `codex/structured-execution-evidence-integration`
- Base branch: `codex/structured-execution-evidence-test-base-v2`
- Latest-main base commit: `d7784fcc7714ca75632eef5338612fece28609aa`
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

### Host-process gate

The 2026-08-28 read-only preflight through `RasControl.list_processes()` found
an unrelated untracked HEC-RAS process, PID 320624, associated with
`UPGU3.prj`. Qualification did not terminate or adopt that process. A later
strict `RasControl.inspect_processes()` scan on 2026-08-29 was complete with no
query errors and no HEC-RAS process; the historical PID is not a current host
hold. Every live attempt must still acquire the host lock and repeat the strict
complete-empty inventory proof immediately before dispatch. A new unrelated or
unverifiable process closes the gate without being signalled.

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
  plan-scoped `RasCmdr.cancel_plan_exact()` for structured cancellation proof;
  raw process-name kills are prohibited. The Boolean `cancel_plan()` remains a
  compatibility wrapper and is not sufficient supervisor evidence.

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
- 2026-08-28: captured replay Run 001 (commit `c87b5a60`) preserved a
  fail-closed Windows path-length finding. The two short steady lanes passed,
  three steady ambiguity lanes failed exactly as expected, and eight longer
  Hager/2D lanes produced supervisor-synthesized `worker_crashed` receipts
  because the harness embedded the final artifact name in a temporary name at
  the legacy 260-character boundary. Its aggregate remained verifiable.
- 2026-08-28: commit `cc6ef362` replaced only the disposable replay temporary
  basename with a short same-directory name. Exact final HEC-RAS names,
  byte/size/mtime pins, stable hashes, and atomic no-overwrite hard-link
  publication remain unchanged. The added boundary regression and 146-test
  qualification suite passed.
- 2026-08-28: captured replay Run 002 (commit `cc6ef362`) proved replay
  publication and inspection reached all longer projects, then preserved a
  second systematic failure: all eight unsteady lanes exposed the harness's
  incorrect requirement that modeled simulation-window datetimes carry a
  timezone. The aggregate again verified and the run remains retained as
  negative evidence.
- 2026-08-28: commit `a510996e` added the logical `local_datetime` observation
  type using canonical timezone-naive ISO text for modeled HEC-RAS wall-clock
  windows. True audit and filesystem instants remain aware Arrow UTC
  timestamps; no physical Parquet column changed.
- 2026-08-28: independent report audit found that Run 001's report mixed
  evaluated invariant-row counts with attempt gates. Commit `9828e8c1` now
  reports recorded check rows separately and labels zero-row crash gates
  `not_evaluated`, without inventing failed invariant records or altering
  aggregate semantics. The combined qualification suite passed 151 tests.
- 2026-08-28: captured replay Run 003 is pinned to full commit
  `9828e8c198f376945ff3940288ce3b9996952c11` and normalized manifest SHA-256
  `b0d41a53da2613d144e5d78a095ed208b8c98e60c7d5c0f34d840152abb7c937`.
  All 13 fresh workers completed with the exact oracle: ten `passed`, three
  `expected_failure`, 36/36 invariant evaluations passed, and every attempt's
  required-invariant gate passed. PyArrow verification rebuilt 13 lane, 36
  invariant, 170 observation, 2,162 artifact, and 78 event rows. All 30 pinned
  replay files (84,925,655 bytes) preserved source bytes and mtimes; 16 modeled
  window observations round-tripped as `local_datetime`; no HEC-RAS/COM was
  invoked.
- 2026-08-28: post-replay RasControl process preflight still finds the unrelated
  untracked HEC-RAS PID 320624 (`UPGU3.prj`). The `dev_human-in-loop` live-engine
  gate therefore remains closed; no process was adopted, terminated, or used.
- 2026-08-29: the representative live-execution packet pinned 13 L0/L1 lanes,
  five exact engine routes, disposable roots, mixed-family/cross-declaration
  phases, required invariants, timeout behavior, and the distinction between
  newly generated live datasets and read-only captured replay evidence.
- 2026-08-29: API consistency audit found that the legacy process DataFrame and
  Boolean cancellation cannot prove complete host inventory, exact plan
  ownership, PID reuse safety, survivor absence, or cancellation quiescence.
  It specified an additive structured process/cancellation contract and common
  modern/Controller execution provenance details while preserving existing
  compatibility behavior. Implementation and deterministic tests are in
  progress on the draft branch.
- 2026-08-29: the first no-engine live supervisor/worker integration exposed
  and corrected contract drift, unsafe Python-child termination when solver
  quiescence was unknown, terminal-receipt publication from mutable logs, and
  resume skipping of failed attempts. Current supervisor tests leave uncertain
  children untouched, retain the host lock, publish no terminal receipt, and
  resume only exact verified successful outcomes from new attempts as needed.
- 2026-08-29: the first real-host `inspect_processes()` query exposed and fixed
  a deterministic Windows PID 0 classification bug. The focused process suite
  passed 21 tests, and the repeated strict query was complete with no query
  errors. It identified the unrelated untracked UPGU3 launcher PID 320624 and
  solver PID 312248; both remain untouched and keep live dispatch closed.
- 2026-08-29: the integrated no-engine process/provenance/live-harness gate
  passed 366 tests. Ruff passed on every changed file (with the package
  initializer's pre-existing E402 exemption) and compileall passed. No HEC-RAS
  or COM execution occurred.
- 2026-08-29: independent adversarial review kept L0/L1 at no-go and found five
  additional proof gaps: incomplete steady/legacy solver taxonomy, Controller
  finalization without a strict post-close solver scan, Controller provenance
  without actual Ras.exe path/hash, interrupt/recovery races around an
  authorized Python worker, and parent terminal verification that accepted
  derived booleans without the underlying TCU/execution/process records.
  Remediation and deterministic regression tests were assigned before any
  live dispatch. Read-only installed-file inspection confirmed exact legacy
  `Steady.exe`, `Unsteady.exe`, and `Sediment.exe` binaries and modern
  `RasSteady.exe`/related solver binaries; it did not execute them.
- 2026-08-29: the no-go findings were remediated without live execution. The
  strict host taxonomy now covers the installed legacy and modern launcher,
  hydraulic, geometry-preprocess, sediment, and water-quality executables while
  retaining exact plan matching only for signatures that can be proved. The
  Controller path records the actual PID/create-time-bound `Ras.exe` path and
  SHA-256, performs complete empty global preflight, and requires complete
  empty exact-plan and global post-close inventories before finalization.
  Watchdog actions revalidate PID, creation time, and name before signalling;
  nonfinite or identity-incomplete session locks are quarantined.
- 2026-08-29: the live supervisor now requires a durable
  intent/hello/authorization handshake before a child may stage or execute,
  retains its host lock across uncertain interrupts, and independently verifies
  that the materialized `execution_result.json`, `evidence.json`, and
  `events.jsonl` exactly agree with their receipt claims as well as their stable
  hashes. Manual recovery requires the original worker identity to be absent
  and a complete empty global inventory; it never signals processes.
- 2026-08-29: an API consistency pass added finite positive timeout validation
  to `cancel_plan_exact()` and retained the existing Boolean `cancel_plan()` as
  a compatibility wrapper. The final affected no-engine integration gate passed
  436 tests. A separate marker-safe audit passed 62 tests and deselected 38
  native/real-engine tests. This audit found two previously unmarked tests that
  launched HEC-RAS; their pytest parents are now explicitly marked. The two
  resulting RAS processes were not signalled and exited naturally.
- 2026-08-29: upstream `main` advanced from `cd56e7cc` to `d7784fcc` through
  PRs 318 and 320. The live manifest and dispatch remain held until the reviewed
  changes are committed, the latest main tip is merged, and all deterministic
  gates are rerun at the resulting clean commit.
- 2026-08-29: making fixture source fingerprints mandatory exposed a latent
  qualification-fixture defect: the manifest's canonical `snapshot_tree`
  digest had been compared with `stage_project()`'s independent, length-framed
  tree digest. Identical source bytes therefore failed the worker gate. The
  corrected R11 contract verifies the manifest pin against qualification
  source snapshots and separately requires the public staging
  before/after/copied fingerprints to match. The retained failed receipt and
  per-file hashes proved this was a digest-domain mismatch, not source drift.
- 2026-08-29: the two digest domains are now persisted as explicit versioned
  contracts. Qualification manifests, requests, lane rows, and artifact rows
  identify `ras_commander.qualification_snapshot.canonical_json.v1`; public
  staging results and `.ras-commander/stage.json` identify
  `ras_commander.stage_project.framed_tree.v1`. Offline and live supervisors
  verify the manifest's qualification pin before publishing a request, and
  workers reverify that same pin before calling `stage_project()`. R11 records
  and checks both namespaces while comparing values only within a namespace.
- 2026-08-29: after that correction, the explicit no-engine integration gate
  passed 501 tests. Ruff passed for all production, harness, and focused test
  files; compileall and `git diff --check` passed. No HEC-RAS or COM execution
  occurred. Live dispatch remains closed pending latest-main reconciliation,
  a clean committed HEAD, final independent review, and an under-lock
  complete-empty strict host inventory.
- 2026-08-29: the final API audit found and closed a cancellation constructor
  contradiction: terminate/kill errors followed by natural process exit now
  return indeterminate quiescence instead of attempting to claim confirmed
  quiescence alongside query errors. Cancellation receipts include start/finish
  times, incomplete inventories require explicit query errors, and the legacy
  Boolean wrapper retains its prior numeric timeout coercion while returning
  true only for a matched, positively quiescent result.
- 2026-08-29: `ComputeParallelResult` now carries defaulted, JSON-safe
  `execution_details_by_plan`, and both parallel/test-mode execution preserve
  direct `ComputeResult` evidence for success, failure, and explicit source
  skips without changing mapping, Boolean, or two-positional construction
  compatibility.
- 2026-08-29: fingerprint namespaces are now explicit end to end:
  `ras_commander.qualification_snapshot.canonical_json.v1` for manifest and
  qualification snapshots, and `ras_commander.stage_project.framed_tree.v1`
  for public staging. The manifest pin is checked before staging; the public
  staging chain is checked independently. The parent supervisor additionally
  validates the exact worker stage receipt against the persisted
  `.ras-commander/stage.json`, including namespace, chain, copy totals, and
  artifact inventory. Omission, wrong-namespace, chain, digest, total, and
  persisted-record tampering all fail deterministically.
- 2026-08-29: the post-remediation explicit no-engine integration gate passed
  514 tests; the expanded parent-stage proof shard passed 74 tests. Ruff passed
  across all changed production/harness/focused-test files, compileall passed,
  and `git diff --check` reported only the repository's existing line-ending
  notices. Independent adversarial review found the prior stage-proof P1
  closed and no remaining HEC-RAS authorization or process-control bypass.
- 2026-08-29: the final API-consistency re-audit approved the additive public
  API with no remaining blocker. The last constructor invariant now rejects an
  incomplete cancellation scan without explanatory query errors, and all
  process/cancellation float timestamps are documented as Unix epoch seconds.
  The final integrated no-engine baseline passed 518 tests in 151.22 seconds;
  its focused process shard passed 83 tests and Ruff passed. No HEC-RAS, COM,
  or process-signalling action occurred.
- 2026-08-29: live-packet review found that folder-wide result-family detection
  would treat an unrelated plan or initial-condition artifact such as
  `Model.IC.O06` as a plan-18 legacy result. Live source, pre-execution, final,
  timestamp, and failure evidence now count only the selected plan's exact
  `<stem>.p##.hdf` and `<stem>.O##` paths. Cross-plan regression tests plus the
  live supervisor/offline/manifest shards passed 182 tests; Ruff and
  `git diff --check` passed. The live manifest example now uses the exact eight
  invariants supported by live v1.
- 2026-08-29: the reviewed work was checkpointed in five coherent commits and
  merged with latest `main` (`d7784fcc`). The sole textual conflict retained
  main's newer quoted-command, legal-dialog, TCU, and owned-process supervision
  while preserving existing final HDF/legacy results and accepting a final-HDF
  preprocessing fallback only when it is nonempty and new or changed. A new
  negative regression rejects an unchanged pre-existing HDF. The reconciliation
  shard passed 59 tests, the full affected no-engine gate passed 521 tests in
  143.78 seconds, and Ruff/compileall/diff checks passed. No HEC-RAS, COM, or
  process-signalling action occurred.
- 2026-08-29: final adversarial review held live dispatch and found four P1
  gaps outside the approved direct Windows L0 happy path: an unresolved
  unsteady computation identity could relax to shared `cwd + bNN`; WSL lacked
  exact Linux-side timeout quiescence; batch promotion did not prove the
  destination was globally idle; and mixed-family sidecars could be attributed
  to the selected result. Follow-up review also exposed promotion recovery
  paths that could discard worker output or temporarily pair an old primary
  result with a new sidecar.
- 2026-08-29: those findings are closed deterministically. Exact cancellation
  now becomes incomplete and sends no signal without project-specific `.cNN`
  identity. Mixed-family filesystem sidecars are diagnostic-only and all known
  candidates are inventoried. WSL requires an atomic token-bound per-plan
  lease, PID/start-tick/PGID evidence, and exact recovery before finalization.
  Batch promotion holds a cooperative destination lock, requires a complete
  empty global RAS inventory, retains failed worker/test stages, and publishes
  each plan through a hash-verified transaction with grouped-primary rollback.
  Unproved rollback exposes no recognized result/sidecar set and retains its
  backups for recovery.
- 2026-08-29: the settled post-remediation gate passed 626 tests in 148.98
  seconds; Ruff, compileall, and `git diff --check` passed. Final API review
  approved the changes with no blocker/high finding. Final adversarial review
  reported no remaining P0/P1 design finding after 226 focused process,
  evidence, WSL, and promotion tests plus 121 live harness tests. No HEC-RAS,
  COM, or process-signalling action occurred. The earlier unexecuted manifest
  pinned to `5feae3d8` is superseded and must not be dispatched.
- 2026-08-29: the first approved L0 dispatch attempt used manifest campaign
  `99860d39-cb16-430c-beaf-14ce9123ddd1`, pinned to clean commit `31c19acd`,
  and selected only lane `steady_1d__6_6__l0`. It failed closed while trying
  to publish `request.json`: resolving the mapped H: archive path to UNC made
  the attempt directory 237 characters and the old destination-derived atomic
  temporary name 264 characters. No request or worker authorization was
  published; no project was staged; no HEC-RAS, COM, or process-signalling
  action occurred. A strict post-failure inventory was complete and empty, the
  host-lock directory was empty, the source remained unchanged, and the empty
  failed attempt directory is retained as prelaunch evidence. This manifest is
  superseded and must not be resumed.
- 2026-08-29: receipt publication now uses a short fixed temporary prefix in
  the same destination directory, preserving the existing atomic hard-link and
  replacement semantics without repeating long destination basenames. A real
  filesystem boundary regression exercises both modes with the longest live
  handshake record: its final digest is 259 characters while every atomic
  temporary is 247 characters. The focused receipt suite passed 17 tests, the
  complete qualification suite passed 269 tests, and Ruff and diff checks
  passed. The replacement live manifest will use one UUID level beneath each
  approved archive/execution root; no additional campaign directory or
  `archive-run` component will consume the Windows path budget.
- 2026-08-29: replacement campaign
  `97baec75-82c7-4b7e-b9cd-efb7235b5810`, pinned to clean commit `2063b7de`,
  selected only `steady_1d__6_6__l0`. It generated no simulation dataset. The
  worker published launch intent, launcher binding, and hello records, then
  failed closed before authorization, staging, COM, or HEC-RAS because the
  pinned Windows virtual-environment `python.exe` was the Python Launcher
  wrapper while the hello came from its sole base-interpreter child. Attempt
  `a56c3508-e29a-477c-8ed4-774fd36608d1` is retained as request-only evidence.
  A strict inventory was complete and empty, the source content and metadata
  fingerprints remained exact, and explicit lock recovery
  `a4f2441c-578c-4dd4-b663-49aab75b3cf1` proved the exact worker and global
  HEC-RAS inventory absent before atomically retiring the unchanged lock. It
  sent no process signal. This campaign is superseded and must not be resumed.
- 2026-08-29: the Windows-launcher remediation now persists digest-bound launch
  intent, exact launcher PID/create-time/command, worker hello, and final
  authorization. It accepts only a direct supervisor child or the launcher's
  sole one-hop child, revalidates the complete topology before authorization,
  and makes atomic authorization publication the final grant. Timeout handling
  signals the same revalidated worker process object, never the wrapper, and
  refuses workers or cancellation helpers with descendants. Cancellation uses
  an independent intent/binding/hello/authorization lease, and recovery proves
  both the helper/worker and any delegated launcher absent from exact persisted
  evidence. Focused tests passed 146 cases; the complete qualification suite
  passed 284 cases; Ruff, compileall, and `git diff --check` passed. An
  independent adversarial re-audit reported GO with no residual P0/P1/P2
  finding. No HEC-RAS, COM, or real-process signal occurred during remediation
  or validation.
