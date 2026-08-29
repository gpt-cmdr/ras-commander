# PR 319 representative live-execution packet

Date: 2026-08-29

Status: approved scope and deterministic design gates complete. The unexecuted
`5feae3d8` preflight manifest, prelaunch-failed `31c19acd` manifest, and
preauthorization-failed `2063b7de` manifest are superseded. Live dispatch is
held until the Windows launcher/worker identity correction is committed, a new
exact manifest pins the resulting clean commit, and the strict under-lock host
inventory is complete and empty.

Branch: `codex/structured-execution-evidence-integration`

Draft PR: <https://github.com/gpt-cmdr/ras-commander/pull/319>

## Purpose and evidence classification

This packet governs real HEC-RAS execution for the representative PR 319
qualification. These lanes **generate new datasets** in disposable execution
folders. They are not read-only replay lanes. Receipts must label newly
generated result artifacts `staged_execution_output`; pristine source-model
files remain `captured_real`. Captured result files used only to prepare a
mixed-family starting condition retain their pinned replay origin until HEC-RAS
replaces or removes them.

The previously accepted `captured_replay/run-003` campaign only read captured
outputs and invoked no HEC-RAS. It is the inspection oracle, not proof of live
cleanup, solver quiescence, or process hygiene.

## Human approval and hard boundary

The maintainer approved disposable-copy execution of the representative
steady 1D, unsteady 1D, and unsteady 2D plans in HEC-RAS 4.0, 4.1, 6.1, 6.6,
and 7.0. Execution must remain inside the archive/execution roots below and
must use only ras-commander APIs. Original project folders are immutable.

Approval does not authorize adopting, cancelling, closing, or killing an
unrelated HEC-RAS process. Before every attempt, the harness must acquire its
host-wide real-engine lock and use the strict `RasControl.inspect_processes()`
inventory. The legacy `list_processes(show_all=True)` view is useful for
operator visibility but cannot open the gate because it omits partial-query
failures. Any unaccounted process or incomplete inventory blocks dispatch.

The first real-host strict read-only query on 2026-08-29 found a scanner defect:
the legitimate non-RAS Windows PID 0 was treated as an invalid process and made
every inventory incomplete. After moving PID validation behind exact RAS-name
classification, the regression suite passed and the same host query returned a
complete inventory with no query errors. It identified two related, untracked
processes outside this task: launcher PID 320624 (`Ras.exe`, `UPGU3.p08`) and
solver PID 312248 (`RasUnsteady.exe`, `UPGU3.c01`). Both were left untouched.
A later strict scan on 2026-08-29 was complete with no query errors and no
HEC-RAS process. That historical occupancy no longer closes the gate, but the
same complete-empty proof must be repeated under the host lock for every live
attempt.

## Roots

- Repository:
  `H:/CLB-Repos/ras-commander/working/structured_execution_evidence_2026-08-24/repo`
- Durable archive root:
  `H:/CLB-Repos/ras-commander/working/pr319_execution_qualification_2026-08-28/live_representative`
- Local execution root:
  `C:/Users/billk_clb/AppData/Local/ras-commander/pr319_execution_qualification_2026-08-28/live_representative`
- Host real-engine lock root:
  `%LOCALAPPDATA%/ras-commander/qualification-locks/`

Each campaign receives a new UUID execution root and a new archive run root.
The UUID is the direct child of each approved root; an additional campaign UUID
or `archive-run` directory must not be inserted. This layout leaves the longest
known UNC archive record (`worker-authorization.sha256` for the longest lane)
at 257 characters, below the tested 259-character boundary. An attempt always
receives a new UUID stage. Failed, timed-out, or interrupted attempts are
retained and never resumed in place.

### Prelaunch path-boundary finding

The first approved single-lane pilot selected `steady_1d__6_6__l0` from
campaign `99860d39-cb16-430c-beaf-14ce9123ddd1`. It generated no simulation
dataset. Before staging or worker launch, atomic `request.json` publication
failed because the mapped archive path expanded to a 237-character UNC attempt
directory and the former destination-derived temporary name reached 264
characters. The retained attempt directory contains no request. A strict
post-failure process inventory was complete and empty, the host-lock directory
was empty, and no HEC-RAS, COM, cancellation, or process signal occurred.

The correction retains same-directory atomic publication but uses a bounded
`.q-` temporary prefix. Regression coverage writes the request and the longest
worker-authorization record in immutable and replacement modes: the longest
final digest is 259 characters and every temporary path is 247. The replacement
campaign must pin the commit containing this correction and use the flattened
root layout above; the failed campaign must never be resumed.

### Windows launcher identity finding

The next approved pilot selected `steady_1d__6_6__l0` from campaign
`97baec75-82c7-4b7e-b9cd-efb7235b5810`, pinned to commit `2063b7de`. It also
generated no simulation dataset. Attempt
`a56c3508-e29a-477c-8ed4-774fd36608d1` published the request, worker launch
intent, exact `Popen` launcher binding, and worker hello, then failed before
authorization, staging, COM, or HEC-RAS. The pinned virtual-environment
`python.exe` was the Windows Python Launcher wrapper; `Popen.pid` identified
that wrapper while the hello correctly identified its sole base-interpreter
child. The previous direct-child-only mock assumption rejected this valid
one-hop topology.

The host remained clean and both source fingerprint namespaces were unchanged.
After the actual Python child exited, explicit recovery
`a4f2441c-578c-4dd4-b663-49aab75b3cf1` revalidated the archived request, exact
worker absence, exact source content and metadata, and two complete empty global
RAS inventories before atomically retiring the unchanged host lock. Recovery
sent no signal. The retained campaign and attempt are diagnostic evidence only
and must never be resumed.

The remediation binds the exact launcher and worker as separate identities. A
worker can be either the direct `Popen` process or, on Windows only, the
launcher's sole one-hop child; both command lines, PID/create times, parentage,
and topology must match. Atomic authorization is the final action after a
second full revalidation. Timeout code signals the same verified worker process
object, never the launcher, and refuses a worker with descendants. The
cancellation helper uses a distinct digest-bound intent, launcher binding,
hello, and authorization lease and cannot inspect or cancel a plan before the
grant. Recovery reconstructs the exact commands from the archived requests and
proves both the actual worker/helper and any delegated launcher absent. Missing,
partial, or tampered evidence retains the lock and fails closed.

The focused handshake, timeout, and recovery suite passed 146 no-engine tests;
the full qualification suite passed 284; Ruff, compileall, and diff checks
passed. Independent adversarial review returned GO with no P0/P1/P2 finding.
These tests neither generated datasets nor invoked HEC-RAS, COM, or real-process
signals. A new manifest must pin the commit containing this remediation before
another pilot.

## Immutable project anchors

| Plan type | Project and plan | Qualification snapshot fingerprint | Stage-project fingerprint | Expected compatibility |
|---|---|---|---|---|
| Steady 1D | `C:/Users/billk_clb/Documents/HEC Data/HEC-RAS/Example Projects/1D Steady Flow Hydraulics/Chapter 4 Example Data/EX1.prj`, plan `01`, `Existing Conditions Run` | `915cc1eb2c0657f907953881122ad795e35eae92c8097209e533943bcadb2925` | `b80648885d625fb7b035de00ad014cb05dd447513c4a8da9dd93e8791dd93530` | 4.0, 4.1, 6.1, 6.6, 7.0 |
| Unsteady 1D | `H:/CLB-Repos/ras-commander/working/structured_execution_evidence_2026-08-24/multiversion_fixtures/sources/Example 20 - HagerLatWeir_e01_multiversion_source/HagerLatWeir.prj`, plan `06`, `Unsteady Broad Crest S=10ft/mi` | `79e13df7d9a167c319d9750fffe28ec026fed43446dfc477a76740d1981d3249` | `36ae1f21de0bdc3583839b3b9e339f07c3b374336c31489db54ce9060a6e7028` | 4.0, 4.1, 6.1, 6.6, 7.0 |
| Unsteady 2D | `H:/CLB-Repos/ras-commander/working/structured_execution_evidence_2026-08-24/multiversion_fixtures/sources/BaldEagleCrkMulti2D_e01_multiversion_source/BaldEagleDamBrk.prj`, plan `18`, `2D to 2D Run` | `e972ac7a99fd21e2375187d01cca684b034d91b6bce99c87354a612d81863400` | `09779010a48e6dfb34da3d4323cf444c6880b0e931a891c92f9f5ec189bebf46` | 6.1, 6.6, 7.0 only |

Before and after every attempt, content and metadata fingerprints of the source
tree must match. Staging must use `RasProject.stage_project()` through the
qualification worker and publish into a destination that did not exist.
Manifest/source pins use the explicit
`ras_commander.qualification_snapshot.canonical_json.v1` namespace. Public
staging receipts use the independent
`ras_commander.stage_project.framed_tree.v1` namespace; those digests must not
be compared across algorithms. Both current values are recorded above so the
manifest pin and the independently published stage receipt can be reviewed
without relabeling either digest. Before terminalizing or reusing a live result,
the parent validates the worker's stage receipt against the persisted
`.ras-commander/stage.json` record and requires the staging
before/after/copied chain to agree.

### Read-only fixture and engine readiness preflight

On 2026-08-29, `inspect_project_assets(..., depth="all_plans")` was run through
the public ras-commander API and filtered to the selected plan plus project-wide
rows. The steady plan returned 7 scoped rows, unsteady 1D returned 10, and 2D
returned 39. All three had zero external linked assets and zero required assets
that were unready or nonportable. The live worker nevertheless re-evaluates the
PyArrow-backed staged inventory and fails before cleanup/compute if a required
or potentially required execution asset is external, has unproved scope, is
outside the disposable stage, or is not ready and portable.

Read-only `RasTcu.status()` checks for 4.0, 4.1.0, 6.1, 6.6, and 7.0 all
returned `accepted=True` for the exact installed directories. The worker must
repeat this exact-engine check before staging. It never calls `RasTcu.accept()`
or opens the GUI; false or unknown acceptance fails closed.

## Exact representative engines

| Requested version | API | Identity | Expected result family |
|---|---|---|---|
| 4.0 | `RasControl.run_plan()` | `RAS400.HECRASController`; canonical Controller version `4.0`; actual `C:/Program Files (x86)/HEC/HEC-RAS/4.0/Ras.exe`; SHA-256 `29f22cd3330ca14e7b92a5e8ca0293cb46a582156ae2bd03bbb1b83f1701300b`; `strict_close=True`; watchdog and `max_runtime` enabled | legacy `.O##` |
| 4.1.0 | `RasControl.run_plan()` | `RAS41.HECRASController`; canonical Controller version `4.1`; actual `C:/Program Files (x86)/HEC/HEC-RAS/4.1.0/Ras.exe`; SHA-256 `b9b1cb9376ccfe63dcca8969c518e095059ea7aba7340b04eabb7a5dd2c9dc17`; `strict_close=True`; watchdog and `max_runtime` enabled | legacy `.O##` |
| 6.1 | `RasCmdr.compute_plan()` | `C:/Program Files (x86)/HEC/HEC-RAS/6.1/Ras.exe`; SHA-256 `58423df21f7115340a9d41f5d93039a786c91f0ffc944f7b23c77846bcc9e330` | plan HDF |
| 6.6 | `RasCmdr.compute_plan()` | `C:/Program Files (x86)/HEC/HEC-RAS/6.6/Ras.exe`; SHA-256 `a34e56a172ba06cde2d546f4d7282801c2b67040969d4ed23b41dfc755772134` | plan HDF |
| 7.0 | `RasCmdr.compute_plan()` | `C:/Program Files (x86)/HEC/HEC-RAS/7.0/Ras.exe`; SHA-256 `9990c10531221469bf51a9a62ae91f36ec01e651bed83aadf632e678130ae797` | plan HDF |

Controller ProgIDs prove the requested COM route. The Controller implementation
also captures the actual running `Ras.exe` image, binds it to PID plus creation
time, and records its path and SHA-256 after identity revalidation. The worker
requires those observed values to equal the manifest pins. Modern executable
files are rehashed during manifest validation and again in the worker before
launch.

## Lane set

The clean representative set has 13 lanes:

- steady 1D in 4.0, 4.1.0, 6.1, 6.6, and 7.0;
- unsteady 1D in 4.0, 4.1.0, 6.1, 6.6, and 7.0; and
- unsteady 2D in 6.1, 6.6, and 7.0.

The current live-harness v1 CLI deliberately enables only L0/L1 lanes whose
starting state is `neither`. L2/L3 mixed-family preparation and L4
cross-declaration execution are documented future phases and are rejected by
the current dispatcher until their setup APIs and independent gates are
implemented and reviewed.

### L0: clean smoke

Create a fresh `neither` stage for every lane. Exact cleanup uses
`RasCmdr.remove_plan_execution_artifacts()`; no harness code unlinks HEC-RAS
artifacts directly. Execute once only after the preflight gate is clear.

### L1: clean repeatability

Repeat all 13 `neither` lanes from new stages and compare semantic evidence,
not output hashes. HDF and message files may contain run-specific metadata.

### L2/L3: mixed-family normalization

For every compatible lane, prepare both HDF and legacy outputs from the
hash/size/mtime-pinned captured replay library:

- `both_expected_newer`: the engine-owned family has the later `mtime_ns`;
- `both_opposing_newer`: the opposing family has the later `mtime_ns`.

The worker must record the complete pre-run population and allowed deletion
set. Running a modern engine must remove legacy `.O##` artifacts before launch
and leave one HDF family after quiescence. Running a legacy Controller must
remove the plan HDF before launch and leave one legacy family. Repeat both
states from fresh stages.

### L4: cross-declaration

Where the plan is compatible, run an engine whose output family differs from
the plan's starting `Program Version` declaration. Any declaration edit is
made only on the disposable copy through a reviewed ras-commander API and is
recorded as generated test setup. Engine identity—not the declaration—owns
execution cleanup. This phase is held until the clean and mixed-family gates
pass.

## Required live evidence

Normal execution lanes require passing R01, R02, R03, R04, R06, R10, R11, and
R12. R05, R07, R08, and R09 are evaluated only in their explicit failure,
skip, uncertainty, or transport campaigns; they are not mislabeled as passing
when not exercised.

Every successful attempt must prove:

1. the source tree was immutable;
2. the exact pinned engine/Controller route was used;
3. only allowlisted plan result/message artifacts were removed;
4. execution returned and solver/Controller quiescence was confirmed;
5. final inspection selected the engine-owned result family without mixing
   evidence channels;
6. exactly one final result family exists;
7. evidence is immutable, JSON-safe, schema-valid, and stably hashed;
8. no attempt-owned process remains; and
9. the worker wrote a digest-bound terminal receipt whose exit code agrees
   with its terminal category.

Mechanical completion and message counts are recorded. They are not a claim
of hydraulic acceptability.

## Timeout and failure behavior

- Controller lanes pass the lane timeout to `RasControl.run_plan()` as
  `max_runtime`, enable the watchdog, and require `strict_close=True`.
- Modern lanes are supervised by the parent deadline. On timeout, a separate
  digest-bound Python helper initializes only the staged project and calls
  `RasCmdr.cancel_plan_exact(plan_number)`. The helper must return structured
  matched, stopped, survivor, query-error, and tri-state-quiescence evidence.
  Raw `taskkill`, `Stop-Process`, direct
  `Ras.exe`, or process-name killing are forbidden.
- The parent may terminate its Python child only after exact cancellation is
  confirmed or after ras-commander proves no exact plan process exists.
- Uncertain process ownership retains the host lock, preserves all conflicting
  artifacts, quarantines the attempt, and fails closed.

A retained real-engine lock is never removed merely because its owner PID is
absent. The explicit `recover --ack-recover-real-engine-lock` action must bind
the archived request to the current run, prove the original PID/create-time
owner is gone, reprove the exact source fingerprint and a complete empty
global HEC-RAS inventory, and atomically archive the unchanged lock identity.
If any proof is unavailable, the lock and evidence remain in quarantine.

## Dispatch gate

Before L0 begins, all of the following must be true at the same clean Git HEAD:

- deterministic qualification and affected-library tests pass;
- live worker/supervisor tests prove no HEC/COM side effects;
- the ras-commander API exposes a strict, structured process inventory that
  includes both launchers and solvers, records PID plus process creation time,
  and reports incomplete inspection rather than silently omitting a process;
- plan-scoped cancellation returns structured ownership, stop, survivor, and
  query-error evidence. The existing backward-compatible Boolean cancellation
  behavior is not sufficient evidence for supervisor release decisions;
- modern and Controller compute results record the exact requested/resolved
  engine route and the terminal quiescence, close, and result-finalization
  gates used by the worker. A worker must not infer those facts from success
  alone;
- the live manifest validates and pins the current commit, interpreter,
  sources, engines, archive root, and execution root;
- archive and execution roots are empty/new and disjoint from sources;
- `RasControl.inspect_processes()` is complete and returns no unaccounted
  HEC-RAS process before and again inside the acquired host lock; and
- the durable manifest and this packet are reviewed before `--ack-real-ras` is
  supplied.

These are additive API prerequisites. Existing `list_processes()` DataFrame,
`cancel_plan()` Boolean, and truth/tuple-compatible compute results remain
available for callers, but the live qualification harness must use the strict
structured siblings or fields. Any unsupported capability, partial process
query, missing engine provenance, or indeterminate quiescence is a dispatch
failure, not a reason to fall back to raw operating-system process control.

### Audited additive API contract

The API consistency audit recommends the following smallest compatible public
surface. These names are provisional until the implementation review, but the
semantics are mandatory for live dispatch:

- immutable JSON-safe records `RasProcessRecord`, `RasProcessQueryError`,
  `RasProcessInventory`, `PlanProcessInventory`, and
  `PlanCancellationResult`, all with explicit `to_dict()` methods and no
  truth-value coercion;
- `RasControl.inspect_processes()` for a strict host inventory of exact-name
  launchers and compute/preprocess engines, including process creation time and
  explicit query errors. The allowlist includes legacy `adh.exe`, `adh_hot.exe`,
  `pre_adh.exe`, `GeomPreprocessor.exe`, `Steady.exe`, `Unsteady.exe`,
  `Sediment.exe`, `SIAM.exe`, and `wqnet.exe`; modern `RasGeomPreprocess.exe`,
  `RasSteady.exe`, `RasUnsteady.exe`, `RasUnsteadySediment.exe`,
  `RasQuasiSediment.exe`, `RasQuasiRVSM.exe`, `RasWaterQuality.exe`,
  `KineticsInterface.exe`, `Kinetics_WPF_Interface.exe`, and `Ras.exe`; and the
  supported `RasProcess.exe` geometry driver. Viewers and generic helpers are
  excluded;
- `RasCmdr.inspect_plan_processes()` for exact token/path matching against the
  initialized project, plan, and plan temporary HDF;
- `RasCmdr.cancel_plan_exact()` returning matched, stopped, survivor,
  query-error, and tri-state quiescence evidence; and
- additive `ComputeResult.execution_details`, plus terminal Controller details
  populated only after close and result finalization.

Process identity is `(pid, create_time)`. Path matching is token-based and
normalizes Windows aliases, UNC/extended prefixes, and working-directory
relative tokens; basename or substring matches are forbidden. Partial process
enumeration makes an inventory incomplete. `cancel_plan()` remains a Boolean
compatibility wrapper and returns true only when at least one exact match was
found and post-cancellation quiescence is positively confirmed.

The first strict host query also showed that solver command lines are
version-specific: the active HEC-RAS 6.3.1 `RasUnsteady.exe` used the exact
project working directory plus the complete plan marker `b08`, not a plan
temporary-HDF argument. Plan matching therefore accepts either an exact tmp-HDF
path token or the jointly exact project-directory/`bNN` signature. The marker
alone, a working directory alone, a basename, or a prefix remains insufficient.
The real-host read-only matcher identified both the UPGU3 launcher and solver
for plan 08 with this contract.

Common execution details include the execution API, engine kind, selected
result format, whether calculation was attempted, solver quiescence,
result-artifact finalization, and engine-provenance confirmation. Modern runs
also record the resolved executable path and SHA-256 plus launcher PID and
creation time. Controller runs retain requested/resolved Controller identity
and ProgID and add Controller PID/creation time, safe close, and owned-process
exit confirmation, plus the actual verified `Ras.exe` path and SHA-256. Both
routes require complete plan-scoped and global post-run process inventories
before finalization.

The supervisor uses a durable launch handshake rather than inferring ownership
from a child PID alone: it writes a request/lock/nonce-bound launch intent,
persists the exact `Popen` launcher PID/create-time and command, verifies the
worker hello and the direct-or-sole-one-hop topology, repeats the full
revalidation, and only then publishes authorization as the final grant that
permits staging or HEC-RAS execution. The cancellation helper uses its own
equivalent lease before it may inspect or cancel the selected plan. An interrupt
before authorization has no RAS side effects. An interrupt after authorization
retains the host lock unless recovery validates the complete digest-bound
evidence, proves the exact worker/helper and any delegated launcher absent,
reproves source immutability, and obtains a complete empty global inventory.
Recovery never signals a process and never treats an absent PID alone as
sufficient evidence.

## Full installed-version expansion

After the representative campaign passes twice, create new attempts for the
historical 58-lane matrix: two plan types for 4.0/4.1, three plan types for
each installed 5.0 through 7.0 version. Earlier results remain historical and
are not relabeled. Known 5.x/6.0 automation boundaries must be represented by
exact pinned expected reason codes, then retested through ras-commander; an
unexplained failure or block remains in the denominator.
