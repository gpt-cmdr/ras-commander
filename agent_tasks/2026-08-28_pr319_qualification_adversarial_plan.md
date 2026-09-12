# PR #319 adversarial qualification plan

**PR:** [#319 — Structured execution evidence integration testing](https://github.com/gpt-cmdr/ras-commander/pull/319)

**Reviewed head:** `8b9eec5` (`codex/structured-execution-evidence-integration`)

**Review mode:** source and test inspection only; no HEC-RAS process was launched
**Purpose:** independently challenge mixed-result selection, plan-scoped cleanup,
launch and quiescence gates, skip behavior, Controller ownership, worker
promotion, copied-folder timestamps, and failure handling before the branch is
retargeted to `main`.

This is a qualification specification, not a claim that the implementation has
passed the cases below. A row is complete only when it has a reproducible test
artifact, an expected outcome, and a recorded result. Generated edge cases must
be labeled as generated; they are not evidence of native HEC-RAS behavior.

## Executive risk assessment

The existing regression suite is strong on deterministic happy paths and many
single-failure paths. It directly covers modern and legacy pre/post cleanup,
selected-engine ownership, exact cleanup allowlists, mixed-format timestamp
rules, read-only skips, local copied-result rejection, incomplete WSL results,
and representative PsExec staging. The remaining risk is concentrated at the
boundaries where filesystem observations are treated as process facts or where
several file mutations together are described as one promotion.

| Rank | Risk | Source-review finding | Required disposition |
|---|---|---|---|
| P0 | Controller final cleanup without confirmed quiescence | `RasControl.run_plan()` sets `calculation_attempted=True` before `Compute_CurrentPlan`, breaks out of polling when `Compute_Complete()` raises, and calls `finalize_plan_execution_artifacts()` in an outer `finally` whenever a calculation was attempted. The finalizer is not conditioned on a positive completion/termination result. `_cleanup_session()` also treats an undetected PID as non-surviving. | Add the COM failure injections C-07 through C-11. Do not merge if an opposing artifact can be deleted while the Controller or solver may still be writing. Either establish a positive quiescence contract or retain both artifacts and fail. |
| P0 | Active solver misclassified as stopped | `RasCmdr._rasunsteady_process_running_for_tmp_hdf()` searches the process command line for one literal path string. Mapped-drive/UNC aliases, 8.3 paths, symlinks, relative paths, and PowerShell wildcard characters can produce a false negative even when the process query itself succeeds. | Run Q-01 through Q-07 with real command-line forms. Zero false `False` results are allowed. An unprovable identity must return unknown and suppress final cleanup. |
| P1 | Result-family publication is not transactional | The selected result is atomically replaced, but the opposing result is deleted in a separate operation. A lock or permission failure can leave a new selected result alongside the old opposing result after the API reports failure. Parallel/test-mode promotion can also copy message and geometry artifacts before final normalization fails. | Run W-08 through W-12 and document the supported failure state. False success is forbidden. If all-or-nothing publication is the intended API promise, add rollback or a transaction journal before merge. |
| P1 | Copied-folder time semantics are not qualified on real filesystems | Unit tests use `os.utime`, but the policy explicitly depends on misleading copy-preserved or copy-rewritten mtimes. NTFS, SMB, ZIP extraction, coarse timestamp resolution, and clock skew remain unmeasured. | Run T-01 through T-12 on the filesystems used by the project library. Ambiguity must be deterministic and must never be presented as proof of producer chronology. |
| P1 | Launch-boundary language is stronger than the observable gate | Direct compute deletes the opposing family immediately before `subprocess.run`/`Popen`; process creation can still fail after deletion. COM proceeds when watchdog startup is unavailable. | Run L-04 through L-09. Define and document which pre-launch mutations are allowed. Preserve the previously selected result and return a visible failure in every case. |
| P1 | Controller timeout and exact-version behavior need native proof | The asynchronous COM poll loop does not itself apply `max_runtime`; it depends on a watchdog that may not start when PID discovery fails. Unit coverage checks mappings, but not every installed registration and result family. | Run C-01 through C-13 in isolated processes. No hung qualification process and no silent fallback to another result family are allowed. |
| P1 | Remote promotion/retention is mainly simulated | PsExec, Docker, and WSL code has focused unit coverage, but transport loss, remote clock skew, late writers, promotion interruption, and retained-staging recovery require end-to-end evidence where runtimes exist. | Run W-13 through W-22. Unavailable infrastructure is a recorded environmental gap, not a passing lane. |
| P2 | Multi-file and multi-plan races remain underexplored | Parallel workers can share copied project state over time, and source promotion includes plan result, message sidecars, and sometimes geometry HDF. | Run Q-08 through Q-13 under repeated scheduling and file-lock contention. |

## Qualification invariants

These IDs are normative. Each test row below names the invariant it evaluates.

| ID | Invariant | Pass condition |
|---|---|---|
| INV-01 | Inspection purity | Read-only inspection changes no watched file content, size, or modification time and launches no executable or COM server. Access time is excluded because filesystem mount policy controls it. |
| INV-02 | Declared-family isolation | With both result families present, evidence comes from only the family selected by the plan declaration and ambiguity policy. Completion, runtime, messages, or producer data are never mixed across families. |
| INV-03 | Conservative ambiguity | When the unexpected family has the later mtime, or the declaration is unresolved with both families, inspection raises `ResultArtifactAmbiguityError` with paths, reason code, declaration, and both observed mtimes where available. |
| INV-04 | Engine-owned execution | Cleanup for an actual calculation follows the resolved executable or exact Controller, not `Program Version=` in the plan file. |
| INV-05 | Exact plan scope | Only the exact plan HDF, exact `.O##`, and explicitly requested message sidecars are removable. Geometry HDF, `.tmp.hdf`, DSS, terrain, other plans, unrelated logs, and files outside the project remain unchanged. |
| INV-06 | Skip immutability | Every successful skip is byte-for-byte and mtime read-only for the plan, both result families, message sidecars, and watched inputs. A mixed family is not silently skipped. |
| INV-07 | Launch gate | Pre-run cleanup occurs only after the engine is resolved and the call has committed to a real launch attempt. Failures before that point preserve both result families. Any allowed mutation after the boundary is explicit and audited. |
| INV-08 | Quiescence gate | Post-run cleanup occurs only after positive proof that the relevant launcher/Controller and solver writers have stopped, or after an owned process tree is positively terminated. Unknown is not equivalent to stopped. |
| INV-09 | No stale promotion | A copied source result, stale remote result, incomplete HDF, incomplete legacy output, or result older than the execution boundary is never published as a successful new run. |
| INV-10 | Publication integrity | A successful worker promotion atomically replaces the selected result, removes the opposing family, and leaves no promotion temp file. A failed promotion is never reported as success and has a documented recoverable state. |
| INV-11 | Failure visibility | Cleanup, verification, transport, or process-state uncertainty produces a typed exception or failed result plus sufficient artifact paths/reason codes for recovery. There is no false success. |
| INV-12 | Version provenance | Requested version, resolved executable/Controller, canonical Controller version, ProgID, declared plan version, and observed producer version remain distinct. Cross-version execution is not mislabeled as a declaration conflict. |
| INV-13 | Immutable source fixture | All execution uses a disposable copy. The immutable fixture tree's content hashes, sizes, and mtimes remain unchanged. |
| INV-14 | Process hygiene | A completed lane leaves no owned HEC-RAS launcher, solver, Controller, watchdog, PsExec service, container, or open staging writer. Unrelated sessions remain untouched. |
| INV-15 | Repeatability | Repeating the same inspection or fresh-copy execution produces the same classification and terminal artifact family, excluding runtime values and explicitly volatile messages. |
| INV-16 | Evidence stability | A file that changes while it is read or hashed does not yield a trusted digest or mixed observation. The record remains immutable and JSON-safe. |

## Harness records and comparison rules

Before each lane, recursively inventory the immutable source and disposable
project. After each phase, capture the same inventory. Store the inventory in
PyArrow-backed Parquet with at least:

- lane ID, fixture classification, source project ID, plan, plan type, and
  declared version;
- selected executable path and binary hash, or requested/resolved Controller
  version and ProgID;
- absolute and project-relative artifact path, size, `mtime_ns`, and SHA-256;
- whether the artifact is a plan input, expected result, opposing result,
  message sidecar, temporary result, geometry result, or unrelated sentinel;
- process snapshot and relevant command line before launch, at launcher return,
  at solver quiescence, and after cleanup;
- cleanup audit, evidence reason codes, exception type, return status, logs, and
  staging-retention location.

Use four fixture labels: `captured_real`, `generated_edge_case`,
`staged_execution_output`, and `archived_failed_execution`. Do not create a
minimal HDF and call it a real result. Generated bytes are suitable for path,
timestamp, locking, and error-contract tests only. HDF structure/completion
claims require an actual HEC-RAS-produced artifact.

For timestamp rows, set and record both nanosecond values and the filesystem's
observed resolution. A tie means exactly equal observed `mtime_ns`; “newer”
means at least two observed filesystem quanta later. Do not infer chronology
from creation time, access time, ZIP entry order, directory time, modeled time
window, or HDF simulation timestamps.

## A. Offline selection and evidence matrix

These tests may use captured real artifacts and controlled copies. They must
not dispatch COM or execute HEC-RAS.

| ID | Pri | Initial state / injection | Expected outcome | Invariants |
|---|---:|---|---|---|
| A-01 | P0 | Modern declaration; HDF newer than `.O##` | Select HDF, warn, record `multiple_result_formats_present`; inspect no legacy completion/message data. | 01, 02, 15 |
| A-02 | P0 | Modern declaration; equal mtimes | Same as A-01. The tie is not described as proof that HDF is newer. | 01, 02, 15 |
| A-03 | P0 | Modern declaration; `.O##` newer | Raise ambiguity with `legacy_output_timestamp_after_hdf`; inspect neither family for completion. | 01, 03, 11 |
| A-04 | P0 | Legacy declaration; `.O##` newer than HDF | Select `.O##`, warn, and do not open HDF for completion/runtime/messages. | 01, 02, 15 |
| A-05 | P0 | Legacy declaration; equal mtimes | Same as A-04. | 01, 02, 15 |
| A-06 | P0 | Legacy declaration; HDF newer | Raise ambiguity with `hdf_timestamp_after_legacy_output`. | 01, 03, 11 |
| A-07 | P0 | Missing, blank, malformed, BOM, CP1252, mixed-case, or duplicate `Program Version` with both families | Missing/unresolvable raises `program_version_unresolved_multiple_formats`; duplicate-key behavior is deterministic and documented. No family mixing. | 01, 02, 03 |
| A-08 | P1 | Sole expected family for modern and legacy plans | Select it without a multiple-format conflict. | 01, 02 |
| A-09 | P1 | Sole unexpected family for modern and legacy plans | Select the sole file, warn, and record `unexpected_result_format`; do not manufacture expected-family evidence. | 01, 02, 11 |
| A-10 | P1 | No results, known declaration | Return expected path/family with `selected_exists=False`; absence is not a failed computation. | 01, 11 |
| A-11 | P1 | No results, unresolved declaration | Select no family and record `program_version_unresolved`. | 01, 11 |
| A-12 | P0 | Selected HDF exists but is corrupt, truncated, locked, or structurally incomplete; nonselected legacy is valid | Report selected HDF structural/read failure only. Never fall back to legacy completion. | 02, 11, 16 |
| A-13 | P0 | Selected legacy exists but completion sidecar is missing, corrupt, changes during read, or contains misleading `Complete Process` substrings | Completion remains indeterminate/false as specified; nonselected HDF cannot validate it. | 02, 11, 16 |
| A-14 | P1 | Result deleted, replaced, or size-preserving rewritten between resolution, stat, hash, and parse | Do not emit a trusted digest or internally inconsistent record; return explicit unstable-source evidence or failure. | 01, 11, 16 |
| A-15 | P1 | Plan bytes change between declaration read and artifact inspection | Detect or conservatively fail; do not combine the old declaration with new result observations as trusted evidence. | 01, 11, 16 |
| A-16 | P1 | HDF/stored-message producer observations disagree, while plan declaration differs from both | Preserve independent producer conflict; do not treat declaration as the producer. | 02, 12, 16 |
| A-17 | P1 | `result_modified_after` immediately before/equal/after observed mtime and timezone offsets crossing DST | Compare absolute timezone-aware instants; reject naive datetime. Completion remains independent. | 01, 16 |
| A-18 | P1 | Repeated inspection with and without hashes, including a large captured HDF | Same classification and values; hashes are stable when files are stable; no COM dispatch. | 01, 15, 16 |

**Acceptance:** A-01 through A-18 pass 10 consecutive offline runs on NTFS and
SMB. There may be no mutation, family mixing, false success, or unexplained
flakiness. Tests that depend on platform locking must record the platform and
skip only where the locking primitive is genuinely unavailable.

## B. Cleanup and direct-launch failure matrix

All destructive cases operate on disposable project copies containing
sentinels for another plan, geometry HDF, `.tmp.hdf`, DSS, terrain, and an
unrelated same-prefix file.

| ID | Pri | Initial state / injection | Expected outcome | Invariants |
|---|---:|---|---|---|
| L-01 | P0 | Public removal of `hdf`, `legacy`, and `both`, with sidecars on/off | Remove exactly the requested allowlist; return removed and missing paths accurately. | 05, 11 |
| L-02 | P0 | Plan number path traversal, absolute path, invalid project name, symlink to outside project, junction, directory at target, and hard link | Reject escaping/non-file targets before first unlink. Removing an in-project hard-link name must not delete other names. | 05, 11 |
| L-03 | P1 | First, middle, and last unlink fail with sharing violation/permission error | Raise `PlanExecutionCleanupError` identifying the failed path and every prior removal. Never claim rollback that did not occur. | 05, 11 |
| L-04 | P0 | Engine metadata unresolved or configured family conflicts with executable family | Fail before plan/result mutation and before process launch; preserve both families. | 04, 07, 11, 12 |
| L-05 | P0 | Skip-current with every optional plan-setting mutation enabled | No process, callback, watcher, plan edit, cleanup, or timestamp change. | 01, 06 |
| L-06 | P0 | Mixed formats with `skip_existing=True` | Do not skip. Execute through selected engine in disposable copy and end with exactly its family. | 04, 06, 08 |
| L-07 | P1 | Callback setup, monitor construction, watchdog construction/start, run-log open, plan-setting mutation, and command construction each fail before the documented launch boundary | Preserve both result families. Record whether plan bytes changed; any behavior allowed by the API must match the documentation. | 07, 11 |
| L-08 | P1 | `subprocess.Popen`/`run` process creation fails after pre-run cleanup | Return failure; preserve the previously selected family; expose exactly what opposing/message cleanup already occurred. No final cleanup is credited as a run. | 05, 07, 11 |
| L-09 | P0 | Launcher returns nonzero while a solver child is active, stopped, or process state is unknown | Active/unknown retains recreated opposing artifact and fails; positively stopped may normalize. A verified fresh result may override launcher status only after quiescence. | 08, 11, 14 |
| L-10 | P0 | Complete final HDF exists while exact solver is still active and `.tmp.hdf` exists/does not exist | Wait; never finalize solely because HDF structure is complete. | 08, 14 |
| L-11 | P0 | Solver state query fails, times out, is access-denied, or produces malformed output | Treat as unknown, fail, and preserve visible conflict/staging. | 08, 11, 14 |
| L-12 | P1 | Solver is stopped but stale `.tmp.hdf` remains; solver is active but `.tmp.hdf` was already renamed; final HDF incomplete after process exit | Apply the documented conservative outcome. No false success or stale publication. | 08, 09, 11 |
| L-13 | P1 | Final cleanup cannot delete the recreated opposing result | Return/record failure, retain both visible result families, and do not corrupt the selected result. | 05, 10, 11 |
| L-14 | P1 | Preprocessing-only APIs run with mixed existing final results | Preserve both final families and messages unless the preprocessing API explicitly owns a different temporary artifact. | 05, 07 |
| L-15 | P1 | Cross-version plan declaration and actual executable in both directions | Cleanup follows executable family; declaration remains recorded as input provenance. | 04, 12 |

**Acceptance:** zero wrong-family deletion; zero mutation before the agreed launch
boundary; zero post-run deletion without positive quiescence; zero false success.
For L-03, L-08, and L-13, partial mutation is acceptable only when the API
reports it precisely and the selected prior result remains readable.

## C. COM/Controller qualification matrix

Run every COM lane in a new Python process with an immutable source and a fresh
disposable destination. Record the actual registered ProgID and executable
version. Never silently substitute an unrequested Controller.

| ID | Pri | Initial state / injection | Expected outcome | Invariants |
|---|---:|---|---|---|
| C-01 | P0 | Static mapping for every supported spelling and installed version | Requested, normalized, ProgID, and canonical version are correct and separately recorded. Unsupported versions fail before Dispatch. | 04, 12 |
| C-02 | P0 | 4.0 and 4.1 real plans through exact registered Controllers | End with `.O##` only; no HDF promotion; exact completion/message rule is satisfied. | 04, 08, 12, 14 |
| C-03 | P0 | Representative 5.x, 6.0, 6.1, 6.3.0.2, 6.3.1, 6.6, and 7.0 registrations where available | End with HDF only, preserving exact Controller identity; automation-boundary failures remain failures, not fall-forward execution. | 04, 08, 12, 14 |
| C-04 | P1 | 3.x request that intentionally maps to 4.1 | Details retain requested 3.x and resolved 4.1; result family is legacy; docs identify this explicit fallback. | 04, 12 |
| C-05 | P0 | `PlanOutput_IsCurrent=True` with exactly selected family | Skip without plan/result/message mutation. | 06, 12 |
| C-06 | P0 | `PlanOutput_IsCurrent=True` with missing selected family or both families | Recompute and normalize; never trust the ambiguous skip. | 04, 06, 08 |
| C-07 | P0 | Dispatch and `Project_Open` fail | Preserve both families. No final cleanup because calculation was not attempted. | 07, 11 |
| C-08 | P0 | Watchdog requested but PID detection/watchdog startup fails | Either abort before cleanup or explicitly prove another quiescence mechanism. It must not proceed to destructive finalization with no process ownership evidence. | 07, 08, 11, 14 |
| C-09 | P0 | `Compute_CurrentPlan` raises immediately after pre-cleanup and creates/recreates an opposing file | Positively terminate/close all owned writers before final cleanup. If termination is unknown, retain conflict and fail. | 08, 11, 14 |
| C-10 | P0 | `Compute_Complete()` raises once, repeatedly, or after a partial result appears | Never treat the exception as completion. Retain conflict unless process termination is positively confirmed. | 08, 11, 14 |
| C-11 | P0 | `Compute_Complete()` remains false beyond `max_runtime`, with watchdog started/not started and PID found/not found | Return within bounded time, stop only the owned process tree, and normalize only after termination proof. | 08, 11, 14 |
| C-12 | P0 | `QuitRas()` fails and tracked process survives, for strict and default close modes | Never finalize while the process survives. Strict mode raises; default mode must still fail or retain ambiguity rather than report safe quiescence. | 08, 11, 14 |
| C-13 | P1 | Blocking call returns malformed tuple, false status, warning/error messages, or raises after producing HDF | Completion, message health, and process status remain separate; cleanup obeys quiescence, not tuple shape alone. | 02, 08, 11, 16 |

**Acceptance:** all P0 COM simulations pass in offline isolation before native
execution. Native registered-version lanes pass twice from fresh copies. No
owned process survives and no unavailable/incorrect ProgID is silently
substituted. C-08 through C-12 are merge blockers until they demonstrate a
positive quiescence gate.

## D. Worker staging, transport, and promotion matrix

| ID | Pri | Worker / injection | Expected outcome | Invariants |
|---|---:|---|---|---|
| W-01 | P0 | Local worker copied project contains both final families and messages | Clear copied final artifacts before a forced/stale run; do not promote copied seed data. | 05, 09, 13 |
| W-02 | P0 | Docker/WSL staging contains both final families plus required `.p##.tmp.hdf` | Remove final HDF, `.O##`, and stale messages while preserving exact preprocessing `.tmp.hdf`. | 05, 09, 13 |
| W-03 | P0 | Worker-selected executable differs from source metadata and plan declaration | Actual worker executable governs family; contradictory worker metadata fails before deletion. | 04, 12, 13 |
| W-04 | P0 | Worker exits success without creating a result | Reject; source/destination prior selected result remains unchanged. | 09, 11, 13 |
| W-05 | P0 | Worker returns stale copied result with preserved or future mtime | Reject based on staging provenance/completion, not destination mtime alone. | 09, 11, 13 |
| W-06 | P0 | Incomplete/corrupt HDF, HDF with errors, legacy output without exact completion record | Reject and preserve destination prior result. | 09, 11, 13 |
| W-07 | P0 | Valid completed result and recreated opposing family | Promote selected result, remove opposite, preserve valid new messages, leave no temp. | 04, 08, 10 |
| W-08 | P1 | Copy to publication temp fails or is interrupted | Destination selected result and opposing family remain unchanged; temp is removed or explicitly retained as recovery evidence. | 10, 11 |
| W-09 | P1 | `os.replace` fails while old selected result exists | Old selected result remains intact, no success, and temp handling is deterministic. | 10, 11 |
| W-10 | P1 | Selected result replacement succeeds, opposing cleanup then fails | No false success. Record whether the supported state is both visible families or rollback to old state; inspection must subsequently raise/warn deterministically. | 03, 10, 11 |
| W-11 | P1 | Plan result copies, then message or geometry copy fails | Plan lane is failed and partial publication is fully inventoried. Do not delete the only recoverable worker staging. | 10, 11 |
| W-12 | P1 | Source destination already has newer mtime but worker result is verified from current lane | Verified worker artifact wins regardless of copied-folder mtime; provenance record explains why. | 09, 10, 15 |
| W-13 | P0 | PsExec parent returns while solver still writes result | Wait to deadline for structurally complete selected result and absent `.tmp.hdf`; do not finalize early. | 08, 09, 14 |
| W-14 | P0 | PsExec timeout, nonzero return, connection loss, and remote host reboot | Return failure, preserve staging and conflicting artifacts because completion is unconfirmed; source remains unchanged. | 08, 11, 13, 14 |
| W-15 | P1 | PsExec complete result but promotion or geometry copyback fails | Preserve remote staging; return failure with paths; source partial state is explicit. | 10, 11, 13 |
| W-16 | P1 | Concurrent PsExec calls to same host and plan | Unique service/staging identity; no cross-lane result or cleanup. | 05, 10, 14 |
| W-17 | P0 | Docker container exits zero/nonzero with missing, stale, incomplete, and complete result | Only a fresh complete exact-plan HDF is promotable. Nonzero never promotes. | 09, 10, 11 |
| W-18 | P1 | Docker daemon/SSH disconnect after container launch | Do not assume stopped; retain staging or remote locator and fail without source mutation. | 08, 11, 13, 14 |
| W-19 | P0 | WSL/Wine exits zero while final HDF is incomplete or `.tmp.hdf` remains | Reject and do not promote. | 08, 09, 11 |
| W-20 | P1 | WSL path contains spaces, Unicode, apostrophe, brackets, and mapped/UNC aliases | Exact plan reaches solver; process identity remains conservative; output returns to the correct lane only. | 05, 08, 14 |
| W-21 | P1 | Parallel/test-mode one plan succeeds and one fails from copied stale seeds | Promote only the successful exact-plan artifacts; failed plan's source results remain untouched. | 05, 09, 10 |
| W-22 | P1 | Parallel workers share geometry or a worker folder is reused while another lane is still publishing | No cross-plan deletion, no geometry/result race, and deterministic per-plan status under repeated scheduling. | 05, 10, 14, 15 |

**Acceptance:** local worker rows pass 10 repeated schedules; available remote
rows pass twice end-to-end from fresh copies. A missing runtime is reported as
`not_run_environment_unavailable` with setup evidence and remains an explicit
confidence gap. It is not converted to an xfail or pass.

## E. Copied-folder timestamp matrix

Use the same captured HDF/legacy pair and plan bytes in every row so only copy
semantics change. Record source and destination `mtime_ns`, filesystem, copy
tool, archive metadata, and clock source.

| ID | Pri | Copy operation / observed state | Expected outcome | Invariants |
|---|---:|---|---|---|
| T-01 | P0 | `shutil.copytree(copy2)` on NTFS preserves both mtimes | Same selection/error as source. | 01, 03, 15 |
| T-02 | P0 | Copy to SMB preserving both mtimes | Same selection/error as source, within observed SMB resolution. | 01, 03, 15 |
| T-03 | P0 | Explorer/Robocopy copy preserving mtimes | Same selection/error as source. | 01, 03, 15 |
| T-04 | P0 | ZIP extraction rewrites both mtimes to one equal value | Select the declared family with warning; do not claim it is newer. | 02, 03, 15 |
| T-05 | P0 | Tar/ZIP extraction preserves distinct mtimes | Apply the normal asymmetric ambiguity rule. | 02, 03, 15 |
| T-06 | P0 | Copy expected family last, making it artificially newer | Select declared family with warning; explanation states filesystem comparison only. | 02, 03 |
| T-07 | P0 | Copy unexpected family last, making it artificially newer | Raise ambiguity rather than guess producer chronology. | 03, 11 |
| T-08 | P1 | Coarse timestamp filesystem collapses distinct source times to a tie | Use tie rule deterministically; no sub-resolution guess. | 02, 03, 15 |
| T-09 | P1 | SMB/client clock skew produces future unexpected timestamp | Raise ambiguity; record clock/filesystem context. | 03, 11 |
| T-10 | P1 | Folder directory mtime newer/older than all result files | Ignore directory mtime. | 01, 03 |
| T-11 | P1 | Result creation time and mtime disagree | Use only documented mtime rule; do not substitute creation time. | 01, 03 |
| T-12 | P0 | After any T-row, execute in a selected modern/legacy engine | Ignore prior result mtimes for cleanup; end with exactly the engine-owned family. | 04, 08, 15 |

**Acceptance:** every copied destination has a before-inspection hash inventory,
and inspection changes none of it. T-01 through T-12 must produce the same
classification on two independent copies per filesystem. Conservative errors
are acceptable; a silent selection of the unexpected newer family is not.

## F. Process identity, concurrency, and repeatability matrix

| ID | Pri | Injection / schedule | Expected outcome | Invariants |
|---|---:|---|---|---|
| Q-01 | P0 | Solver command line uses the exact absolute `.tmp.hdf` path | Process query returns running while alive and stopped only after exit. | 08, 14 |
| Q-02 | P0 | Same file addressed by mapped drive versus UNC path | Resolve as same file or return unknown; never return stopped while alive. | 08, 14 |
| Q-03 | P0 | Same file addressed by 8.3 path, relative path, symlink, or junction | Resolve or return unknown; never false stopped. | 08, 14 |
| Q-04 | P0 | Path contains spaces, apostrophe, `[`, `]`, `?`, `*`, Unicode, and case differences | Query is literal-safe and cannot be altered by PowerShell wildcard parsing. | 05, 08, 14 |
| Q-05 | P0 | CIM returns access denied, timeout, malformed output, or multiple matching solvers | Unknown/multiple is explicit; cleanup is suppressed unless exact owned process termination is proven. | 08, 11, 14 |
| Q-06 | P0 | Unrelated HEC-RAS processes run concurrently against different projects/plans | Never wait for, terminate, or attribute the unrelated process. | 05, 14 |
| Q-07 | P0 | Exact launcher exits, child renames `.tmp.hdf`, writes complete HDF, then continues writing `.O##` | Final cleanup waits for child exit, not just HDF completion/rename. | 08, 14 |
| Q-08 | P1 | Two plans share one worker assignment with deliberately inverted completion times | No same-folder simultaneous execution unless explicitly synchronized; no cross-plan cleanup. | 05, 10, 14 |
| Q-09 | P1 | Two lanes promote different plans sharing one geometry HDF | Geometry promotion is serialized or conflict-detected; plan results remain correct. | 05, 10 |
| Q-10 | P1 | Two lanes target the same plan/destination | One wins through an explicit lock/idempotency rule or one fails visibly; no interleaved artifact set. | 05, 10, 11 |
| Q-11 | P1 | Cancel exact plan while another plan and another project execute | Stop only matched process tree; both unrelated runs remain healthy. | 05, 14 |
| Q-12 | P1 | Repeat representative local engine lane twice from independent fresh copies | Same terminal family, evidence classification, and conflict set; no source mutation or orphan. | 13, 14, 15 |
| Q-13 | P1 | Run deterministic offline qualification suite under randomized test order and separate-process shards | No dependence on global `ras`, COM, CLR, PROJ, process, or prior fixture state. | 01, 15, 16 |

## Real-project engine matrix

Use the compact real projects already identified for steady 1D, unsteady 1D,
and unsteady 2D. Add at least one project with DSS boundaries and one gridded
precipitation project when available, because result messages and long-lived
solver behavior differ. The source fixture is immutable; every lane gets a
fresh full-tree copy.

Minimum mandatory lanes:

1. HEC-RAS 4.0 and 4.1: steady 1D and unsteady 1D through `RasControl`.
2. Representative modern families: 5.0.x, 6.0, 6.1, 6.3.0.2, 6.3.1, 6.6,
   and 7.0 where installed, across every supported plan type.
3. Cross-family transitions: legacy-declared copy run by a modern executable,
   and modern-declared copy run by a legacy Controller.
4. Every lane starts once with only expected results, once with only opposing
   results, and once with both families whose unexpected mtime is later.
5. Run the representative matrix twice. After the harness is stable, rerun the
   full 58-lane installed-version matrix. Historical mixed outputs are inputs,
   not qualification passes for the new normalization behavior.

For every successful execution, require exactly one final result family,
positive completion evidence from that family, no active owned process, no
`.tmp.hdf` writer state, and unchanged immutable source. For every expected
failure, require the precise typed/reason-coded failure, no source mutation,
and a recoverable disposable/staging inventory.

## Release acceptance thresholds

PR #319 is ready to retarget to `main` only when all of the following are true:

1. **Zero-tolerance safety:** no wrong-plan deletion, wrong-family deletion,
   false success, stale promotion, evidence-family mixing, source-fixture
   mutation, or cleanup while a writer may be active.
2. **P0 completion:** every P0 offline/failure-injection row passes with no
   xfail. Every available P0 native lane passes twice from fresh copies.
3. **P1 disposition:** every P1 row is passed, fixed, or recorded as an explicit
   environmental gap approved by a human. A code defect cannot be waived as an
   infrastructure gap.
4. **Repeatability:** the deterministic suite passes 10 randomized/order-sharded
   repetitions. Representative native lanes pass 2/2; any first-run failure
   requires a fresh-copy rerun and root-cause classification, not majority vote.
5. **Process hygiene:** zero owned launchers, solvers, Controllers, watchdogs,
   PsExec services, containers, or file writers survive a terminal lane.
6. **Evidence completeness:** every lane produces the manifest, before/after
   artifact inventory, event record, logs, engine identity, and reason-coded
   outcome. No unexplained result remains in the summary.
7. **Known blocker closure:** C-08 through C-12 and Q-01 through Q-07 prove that
   post-run cleanup is positively quiescence-gated across CLI and COM paths.
8. **Promotion closure:** W-08 through W-12 establish and document the supported
   multi-file failure state. If the public API continues to say “atomic
   promotion,” the complete result-family transition—not merely one file
   replacement—must meet that promise.

## Recommended execution order

1. Implement the immutable inventory/event schemas and offline A/L/C failure
   injections first. These can reveal contract bugs without HEC-RAS execution.
2. Resolve all P0 failures, especially COM quiescence and path-identity cases.
3. Run the three representative real-project lanes for legacy and modern
   families in isolated Python processes.
4. Exercise copy semantics on NTFS and SMB, then the cross-version transitions.
5. Exercise LocalWorker, PsExec, Docker, and WSL/Wine only where the configured
   runtime can be identified and the disposable destinations are confirmed.
6. Repeat representative lanes, then execute and classify the full installed-
   version matrix.
7. Attach the Parquet qualification bundle and concise Markdown summary to the
   PR before retargeting it to `main`.
