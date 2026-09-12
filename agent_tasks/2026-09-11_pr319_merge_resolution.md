# PR 319 merge resolution

The maintainer requested resolving and merging PR 319 on 2026-09-11 as the
shared structured execution-evidence API for the container workflow. This
supersedes the original task's instruction to stop on its draft testing base.
It does not convert unfinished or failed qualification into passing evidence.

## Source integration

- Original PR head: `b0bfb42bded59d58d4823714688b3cd6b17e5438`.
- Current-main integration checkpoint: `71c63a98fb081338516d4b194849446fc3b27198`,
  incorporating main `ac50b62bf64432870f22bb70ba870b65424bd6cd`.
- Retained follow-up work reviewed from
  `acd6780d4e62a0bdc8a23f5c2f7d3edc8ca671e1`: Controller cleanup identity fixes
  and exact dialog observation, including the recorded legacy execution gap.
- The qualification module `run_io.py` was recovered from the retained source;
  a broad ignore rule had omitted it from the public PR. A narrow exception now
  keeps that required module in Git.

Current-main integration preserves the HEC-RAS 5.x project-only launcher,
unambiguous Current Plan ownership, process-local 6.3 WMIC compatibility,
native CPU controls, and current result-record exports. Synthetic executable
tests explicitly model TCU acceptance instead of consulting the user's registry.

## Findings requiring correction

1. HEC-RAS 4.0/4.1 expose an inherently blocking, two-argument
   `Compute_CurrentPlan`. A same-thread poll after it returns cannot enforce a
   timeout. The API and qualification evidence must describe the blocking
   return and independent watchdog accurately.
2. A Windows virtual-environment launcher PID can differ from the interpreter
   running the orphan watchdog. The worker must publish its own identity;
   the parent must verify that identity and its launcher ancestry before
   recording a process that cleanup may signal.
3. Legacy diagnostics need exact Controller-scoped observation before
   `Project_Open`, with unknown dialogs retained without interaction.
4. Native Docker output does not require the Windows `Complete Process`
   message. Both remote Docker routes must validate their current solver log
   and exact final HDF through the native validation API.
5. PsExec copyback must preserve fresh completion-message sidecars with its
   selected result, remove stale destination messages transactionally, and
   retain staged evidence if publication fails. Its command-line route must
   reject pre-5 engines requiring COM and use the supported project-only
   launcher form for 5.x, with Current Plan set only in the staged project.

## Evidence retained before fresh qualification

The integrated checkpoint passed 472 affected tests (2 skipped), 410
qualification-harness tests (1 skipped), and 50 TCU tests. These results precede
the follow-up corrections above and do not qualify their final source.

The original captured replay retained 13 lanes: 10 passed and 3 expected
ambiguity failures. All 30 captured artifacts and all 133 pinned source files
remain intact. Its source commit is historical; fresh qualification must pin
the corrected integration commit.

The latest retained live campaign passed steady 6.6 and 7.0. Its steady 6.1
verification failed on `Geometry/River Edge Lines not found in
WriteAttributePreCheck`, also present in the pre-PR baseline. That diagnostic
must remain a failure even though HDF mechanical completion is true. The 4.1
retry produced no result and no terminal receipt; recovery did not qualify it.

Read-only inspection of the retained native 6.5, 6.6 and 7.0.1 outputs confirms
267 timestamps by 6,548 finite water-surface values over the requested 266-hour
window. All three pass the unchanged native validators. Their generic HDF
completion attribute was already true in the prepared input; they lack the
Windows completion-message dataset. Structured observations are supplementary
diagnostics, while native log and result checks remain the acceptance gate.

External evidence is retained in the task's `pr319-integration-20260911`
artifact directory. No installers, runtime files, model data, result HDFs, or
machine credentials belong in this repository.

## Fresh qualification and merge status

The initial implementation candidate is
`c326a1bfc38ec3f090399e7b7fe4df17991207fc`. Notebook inventory/index ordering
corrections preserve its runtime and qualification source. A subsequent
Windows inventory correction is described below and requires a new source
pin for live qualification.

- Affected API, ownership, Controller, message and TCU suite: 611 passed,
  2 skipped.
- Complete qualification-harness suite: 441 passed, 1 skipped.
- Remote/native/PsExec suite: 103 passed, 1 platform skip; WSL ownership checks
  passed separately. Overlapping tests are not added to the first total.
- A real Python-only watchdog worker completed identity verification and
  cleanup. This test did not invoke HEC-RAS.
- Fresh captured replay: 13 attempts, 10 passed and 3 expected ambiguity
  failures; all 36 independently reconstructed invariants passed. Every
  request and receipt pins the implementation candidate and records no HEC-RAS
  invocation.
- Independent review rehashed all 133 fixture files, verified their preserved
  identities, and checked the conversion from historical framed fingerprints
  to the current canonical JSON fingerprint format. Added Controller binary
  pins identify the available binaries; they do not establish retrospective
  historical-engine provenance.

The first live dispatch was refused before launching a worker because another
HEC-RAS job was active; the existing process was left untouched. An idle CLB
qualification host has matching installed binaries, but psutil reports an
empty name for its protected Windows `Secure System` process. The strict
inventory correctly refused to treat that incomplete scan as quiescence.

The correction recovers only empty string names through a read-only Windows
Tool Help snapshot. It verifies the original creation time against two fresh
process identities around the lookup. Unknown names, access failures and
identity changes still fail the scan; recovered HEC-RAS names still require
the ordinary metadata checks. There is no process-name or PID allowlist.
The actual host probe returned `Secure System` with identical creation times
before and after the query. Independent review cleared the implementation;
137 focused tests and 637 affected regression tests (2 skipped) passed. The
complete qualification-harness suite also passed again: 441 tests, 1 skipped.

The maintainer explicitly authorized TCU acceptance for all HEC-RAS versions.
The selected legacy installations now verify accepted through `RasTcu.accept`;
before/after status, donor preservation, binary identities and the actual API
acceptance audit are retained externally. No GUI interaction was claimed.

The corrected `9a254c43b071` candidate passed hosted documentation CI and a
fresh captured replay: 13 attempts, 10 passes, three expected ambiguity
failures and 36 passing invariants. Independent review found no classification
or observation drift. Its public process inventory on CLB08 was complete and
empty, with all five selected runtime TCU states accepted.

The first CLB08 steady 6.6 attempt exposed a qualification-harness contract
error before staging: it compared `TcuStatus.version`, a resolved version
label, with the full executable path passed to `RasTcu.status`. Both worker
and supervisor now compare the label with the declared version and separately
bind the exact executable argument and installation directory. Controller
checks also use the pinned executable path. The public TCU API and acceptance
behavior are unchanged. The failed attempt remains `worker_crashed` with an
unknown invocation field and verified safe process cleanup; no pass was
inferred from its empty postflight inventory.

The two live-harness test files and the public TCU suite passed 350 tests,
including the real public version-label behavior and independent rejection
of wrong versions, executable arguments and installation directories.
The remaining qualification files passed 158 tests, with one skip; those
files exclude the two live-harness files already counted above.
Representative live regression remains pending the corrected harness source
pin. This PR remains a draft until those runs and final CI are reviewed.

The historical 58-lane matrix, all transports, and broad hydraulic-model
coverage must not be represented as fully requalified by this merge.
