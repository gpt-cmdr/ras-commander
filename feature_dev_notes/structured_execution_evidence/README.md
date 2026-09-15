# Structured execution evidence

Status: **E01a implemented; installed-engine qualification completed where the host automation path is usable**

Date: 2026-08-25

## Purpose

RAS Commander currently reports execution through several useful but lossy
surfaces:

- `ComputeResult.success` can describe the process outcome, a skipped result,
  or a verified computation depending on caller options;
- `completion_verified=None` means verification was not requested, while
  `False` can combine incomplete, unreadable, stale, conflicting, and
  hydraulically unhealthy results;
- `results_df.completed=False` also covers absent or unreadable evidence; and
- message, runtime, completion, version, and currency observations do not share
  one provenance model.

The proposed feature records what was actually inspected, where it came from,
and what it means. It derives **mechanical completion only**. It does not assert
convergence quality, model fitness, volume-accounting acceptability, or
hydraulic acceptance.

## Smallest recommended public contract

Add one read-only entry point and two immutable value types:

```python
evidence = RasCmdr.inspect_execution_evidence(
    "01",
    ras_object=project,
    result_modified_after=None,
    hash_files=False,
)
```

```python
@dataclass(frozen=True)
class EvidenceObservation(Generic[T]):
    state: Literal[
        "available",
        "not_available_in_version",
        "not_inspected",
        "failed",
    ]
    value: T | None
    channel: Literal[
        "derived",
        "filesystem",
        "hdf",
        "stored_message",
        "legacy_output",
        "process",
        "com",
    ]
    source_locator: str | None
    source_sha256: str | None
    observed_program_version: str | None
    inspected_at: datetime
    reason_code: str | None
    detail: str | None


@dataclass(frozen=True)
class ExecutionEvidence:
    schema_version: int
    evidence_id: str
    inspected_at: datetime
    project_file: Path
    plan_file: Path
    plan_number: str
    declared_program_version: str | None
    mechanical_completion: EvidenceObservation[bool]
    observations: Mapping[ObservationName, EvidenceObservation[Any]]
    conflicts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]: ...
```

`ObservationName` is a fixed public registry, not an open-ended string. Every
record contains the same keys and each key has a documented value type and
allowed channels. Version differences change observation states, not the
schema. The immutable result defensively copies the mapping before exposing a
read-only view.

The observation mapping keeps the top-level object small without expanding a
wide dataclass or `results_df`. The initial stable observation names are:

- `result_artifact_exists`
- `result_artifact_modified_at`
- `result_artifact_modified_after_threshold`
- `result_artifact_structural_state`
- `producer_program_version`
- `completion_attribute`
- `completion_message_hdf`
- `completion_message_stored`
- `message_error_count`
- `message_warning_count`
- `message_first_error`
- `runtime_seconds`
- `simulation_start`
- `simulation_end`
- `process_success`
- `com_completion`

`mechanical_completion` is an explicit top-level observation and is not
duplicated in the mapping. `process_success` and `com_completion` remain
`not_inspected` in the initial
read-only implementation. They reserve explicit channels for later attachment
to `ComputeResult` and `RasControlResult` without pretending that stored files
came from the live process or controller.

### State invariants

- `available(value=False)` means the channel was inspected and supplied a
  negative value.
- `not_available_in_version` means the version capability table establishes
  that the producer does not implement that channel.
- `not_inspected` means no trustworthy value or assertion was established.
  This includes an absent source, an unrequested optional check, and inspected
  message text that contains no exact completion marker.
- `failed` means inspection was attempted but could not produce a trustworthy
  value.
- A missing optional HDF field in a producer lane not yet established by the
  capability table remains `not_inspected` with reason
  `version_shape_not_established`; it is not generalized to the whole version.
- Contradictory completion sources retain their raw observations and derive
  `mechanical_completion=failed`, reason `conflicting_evidence`.
- Completion and message health are independent. A completed computation may
  still have parsed errors; errors and warnings are health observations, not
  completion conflicts.
- Hydraulic acceptance is omitted. Core mechanical inspection cannot supply
  it.

## Version and channel rules

The initial implementation should probe only existing files. It must not start
HEC-RAS, preprocess a project, or open a COM controller.

| Producer lane | Result artifact | Completion/message channel | Structured runtime | Initial behavior |
|---|---|---|---|---|
| 3.x | `.O##` | stored message through the `RasControl` stored-file path when present; live COM not inspected | not available in the HDF contract | Record legacy output existence/currentness. Completion is indeterminate when no stored message exists. |
| 4.x | `.O##` | `.p##.comp_msgs.txt` through the `RasControl` stored-file path when present; live COM not inspected | message-derived only | Parse exact completion records and runtime from the stored message. |
| 5.0.1 / 5.0.3 | `.p##.hdf` | embedded HDF messages, then source-preserving stored-message fallback | message-derived; inspected samples lack `Compute Processes` | Record `Time Window` when explicit start/end attributes are absent. |
| 5.0.6 / 5.0.7 | `.p##.hdf` | embedded HDF messages plus stored-message observation | HDF when present, message fallback otherwise | Preserve plan-declared and HDF-observed versions separately. |
| 6.1-6.7 observed lanes | `.p##.hdf` | completion attribute and embedded/stored messages | HDF `Compute Processes`, message fallback | Derive completion from non-conflicting sources; never convert parsed errors into incomplete execution. |
| 5.0.2 / 5.0.4 / 5.0.5, exact 6.0, native 7.0 | version-appropriate artifact | probe actual artifact, but do not assert unproved field availability | probe actual artifact | Mark unestablished missing fields explicitly; keep these lanes in the confidence backlog. |

The source-preserving message reader must report whether text came from the
HDF dataset, `.comp_msgs.txt`, `.computeMsgs.txt`, or `.bco##`. Existing
`get_compute_messages*()` and `RasControl.get_comp_msgs()` return only text and
therefore cannot, by themselves, supply this provenance.

## Derived mechanical-completion rule

The rule is intentionally narrow:

1. If any inspected authoritative completion source explicitly reports false,
   derive false unless another authoritative source reports true; disagreement
   is `failed/conflicting_evidence`.
2. Otherwise, an exact `Complete Process` message record or a true
   `Event Conditions/Completed Successfully` attribute supplies true.
3. Message text without an exact completion record makes no completion
   assertion. It is not an explicit false value. A result artifact without an
   accepted completion source is therefore indeterminate, not false.
4. `result_modified_after` evaluates a caller-supplied, timezone-aware
   filesystem threshold
   independently. An older but otherwise completed artifact remains
   mechanically completed and separately reports
   `result_artifact_modified_after_threshold=False`. This is deliberately not
   called `current`, because full RAS input currency is a different test.
5. Parsed errors and warnings are retained as health observations, but do not
   rewrite mechanical completion.

This corrects the current conflation in `RasCmdr._verify_completion()`, where
`check_errors=True` makes a mechanically completed run appear incomplete.
Existing behavior remains backward compatible; the new inspector is additive.

## Implementation slices

### E01a — Offline evidence contract and channel readers

- Add `EvidenceObservation`, the fixed `ObservationName` registry, and
  `ExecutionEvidence`.
- Add source-preserving readers for HDF messages and stored sidecars.
- Extract and reuse the exact completion-record parser already used by
  `HdfResultsProducts`; do not use substring matching and do not invoke the
  product-readiness inspector.
- Add version-family/capability rules from the observed matrix.
- Add `RasCmdr.inspect_execution_evidence()`.
- Add synthetic edge-case tests and read-only tests over existing producer
  artifacts. No HEC-RAS run is required.

### E01b — Existing execution result integration

- Add optional `execution_evidence` to `ComputeResult` and
  `RasControlResult`, preserving boolean and tuple compatibility.
- Capture requested executable and selected controller ProgID separately from
  declared and observed producer versions.
- Keep process outcome, mechanical completion, message health, and hydraulic
  acceptance distinct.

E01b should follow installed-engine validation because its exact evidence is
created during execution.

### E01c — Exact-version confidence lanes

- Run only separately approved staged-copy packets.
- Fill exact 6.0 and native 7.0 first, then 5.0.4/5.0.5 if exact engines and
  public fixtures are available.
- Preserve failure/cancel/partial-HDF evidence as first-class fixtures.

## Test plan

Pure read-only/synthetic coverage:

- true, false, absent, malformed, and conflicting completion attributes;
- exact versus misleading `Complete Process` text;
- HDF, sidecar, `.bco##`, and absent-message source selection;
- available-false versus not-inspected versus failed;
- 3.x/4.x legacy output without HDF;
- 5.0.x `Time Window` fallback and absent `Compute Processes`;
- declared-versus-observed producer-version disagreement;
- HDF-versus-stored-message producer-version disagreement;
- stale artifacts independent from completion;
- before/after SHA-256 proof for real read-only fixtures; and
- JSON serialization without full compute-message disclosure.

Installed-engine coverage remains a separate human gate. Prepared lanes exist
for RAS 6.6 Davis p02, RAS 6.7 Beta 5 Beaver Lake p01, and native RAS 7.0 TWRA
Wu p01. None is authorized by this note.

## Approval decision

The maintainer approved E01a with:

1. `RasCmdr.inspect_execution_evidence()` as the entry point, with
   `result_modified_after` as the optional freshness threshold;
2. `EvidenceObservation` plus `ExecutionEvidence` as the return contract;
3. the four public evidence states and fixed observation registry; and
4. omission of hydraulic acceptance from the mechanical schema.

That approval did not authorize an installed-engine run, preprocessing, a COM
session, or real-project mutation.

## E01a implementation checkpoint

The approved offline contract is implemented on the feature branch. Focused
unit/regression coverage passes for modern HDF, legacy output, stored message,
5.0.x time-window/runtime fallback, completion conflicts, malformed
attributes, misleading completion substrings, freshness thresholds,
serialization, immutability, and declared/observed version disagreement.

`result_artifact_structural_state` reports only the structure actually
observed (`plan_information_present` or `plan_information_absent`). It does
not label a readable HDF as complete. When hashing is requested, an HDF digest
is attached only when inspection and hashing share one unchanged size/mtime
window. Stored-message digests are computed directly from the same bytes that
were decoded and inspected. Message-health parsing uses embedded HDF messages
first and stored messages as a fallback while retaining both completion
observations independently.

Read-only validation also exercised five pre-existing producer lanes: RAS 3.13
legacy output, RAS 4.1 stored messages, RAS 5.0.1 HDF, RAS 6.1 HDF, and RAS 6.6
HDF. The watched project, plan, result, output, and message identities were
unchanged before and after inspection. The real lanes established two rules
now covered by regression tests:

- legacy RAS 4.1 accepts the exact `Complete Process<TAB>1.44 sec` record; and
- a `.bco##` file without a completion marker does not contradict positive HDF
  completion evidence because that stored detail channel makes no explicit
  false assertion.

No HEC-RAS executable, preprocessor, or COM controller was invoked.

## Installed-engine qualification checkpoint

A later human-in-the-loop approval authorized execution against staged copies
of three real projects. This does not change the earlier E01a checkpoint: that
checkpoint remains the record of the read-only work completed before execution
was authorized.

| Plan family | Real plan | Versions staged |
|---|---|---|
| steady 1D | Chapter 4 EX1, plan 01, `Existing Conditions Run` | 4.0 through 7.0 |
| unsteady 1D | Hager lateral-weir example, plan 06, `Unsteady Broad Crest S=10ft/mi` | 4.0 through 7.0 |
| unsteady 2D | Bald Eagle dam-break example, plan 18, `2D to 2D Run` | 5.0 through 7.0 |

The exact installed set was 4.0, 4.1.0, 5.0, 5.0.1, 5.0.3, 5.0.4,
5.0.5, 5.0.6, 5.0.7, 6.0, 6.1, 6.2, 6.3, 6.3.1, 6.4.1, 6.5, 6.6,
6.7 Beta 4, 6.7 Beta 5, and 7.0. The 2D fixture starts at 5.0 because only
RAS 5 and newer support that plan family.

The matrix contains 58 canonical lanes. Attempts retained in separate
`__attempt_*` archive folders are excluded from these counts.

| Version family | Lanes | Completed | Attempted and failed | Blocked before plan execution |
|---|---:|---:|---:|---:|
| 4.0-4.1 | 4 | 4 | 0 | 0 |
| 5.0-5.0.7 | 21 | 0 | 8 | 13 |
| 6.0 | 3 | 0 | 1 | 2 |
| 6.1-7.0 | 30 | 30 | 0 | 0 |
| **Total** | **58** | **34** | **9** | **15** |

`Failed` means an execution API or controller was actually attempted and did
not produce a successful process result. `Blocked` means the real project copy
was staged and its PR #314 plan classification was validated, but plan
execution was deliberately not attempted after the same engine-level gate had
already been reproduced. A temporary harness bug initially labeled a 5.0.6
`success=False` result as completed; the record and harness were corrected
before deriving these totals.

The version boundary observed on this host is:

- RAS 4.0 and 4.1 execute through their exact COM controllers. Both steady and
  unsteady outputs were read back through `RasControl`; the probes returned 30
  and 21 result rows respectively for each version.
- RAS 5.x command-line computation is not usable, while the registered 5.x
  controllers fail or block during `Project_Open`, before plan dispatch. The
  installed `RAS506` registration also resolves to the 5.0.5 executable, so it
  cannot establish exact 5.0.6 controller attribution on this host.
- RAS 6.0 has the same pre-dispatch automation boundary: command-line
  computation stalls and `RAS60.Project_Open` blocks.
- RAS 6.1 and newer execute successfully through `RasCmdr.compute_plan()`.
  All 30 modern lanes produced fresh plan HDFs with verified completion.

All 34 completed lanes originally recorded `process_success=True`, mechanically
verified completion, a fresh hashed result artifact, unchanged plan
classification, and no evidence conflicts under the then-current HDF-first
selection rule. That conflict conclusion is superseded by the ambiguity policy
below; the archived engine outcomes remain valid, but the mixed-format lanes
must be rerun through the cleanup-enabled compute path before they become clean
execution-evidence fixtures. Thirty-two completed lanes had zero parsed errors
and warnings. The steady and unsteady 1D RAS 6.1 lanes each retain one message:
`WRITE ATTR ERROR: ERROR: Geometry/River Edge Lines not found in
WriteAttributePreCheck`. Both computations still carry positive completion
evidence. This is why message health remains separate from mechanical
completion.

The real transition runs also exposed why HDF-first selection is unsafe. Every
successful modern steady-1D and unsteady-1D lane contains both a plan HDF and a
plan `.O##`. The `.O##` modification time is generally a few seconds after the
HDF, demonstrating that HEC-RAS 6.1-7.0 actively recreates this companion output
during computation rather than merely leaving the copied legacy file in place.
Pre-run cleanup alone therefore cannot maintain a single-format invariant.

The approved replacement rule reads `Program Version=` directly from the
current `.p##` bytes. A sole HDF or sole `.O##` remains readable even when its
family differs from the declaration, with `unexpected_result_format` recorded;
this preserves clean old-plan/new-engine transitions because HEC-RAS does not
reliably rewrite the plan declaration. When both formats exist:

1. a HEC-RAS 5+ declaration selects HDF and warns only when its modification
   time is equal to or after the `.O##` time;
2. a modern declaration with a later `.O##` timestamp raises
   `ResultArtifactAmbiguityError`;
3. a HEC-RAS 4-or-earlier declaration selects `.O##` and warns only when the
   HDF modification time is equal to or before the `.O##` time;
4. a legacy declaration with a later HDF timestamp raises the same error; and
5. an unresolved declaration with both formats raises the same error.

Filesystem timestamps are a conservative ambiguity trigger, not proof of
which computation is newer; copied folders can preserve or rewrite them. When
legacy output is selected, HDF completion, runtime, producer, and message
evidence cannot validate the legacy result.

Compute cleanup does not use artifact timestamps. It follows the actual
selected executable/controller, not the plan declaration. Modern runs remove
`.O##` and stale message sidecars at the launch boundary and remove a recreated
`.O##` after every launched attempt whose solver completion or termination is
confirmed. Legacy runs remove the plan HDF and stale messages at the same
boundary and enforce the same result family afterward. An unconfirmed active
solver fails without final normalization, leaving possible conflicts visible.
Skipped computations preserve both result artifacts and plan-file bytes.
Parallel, test-mode, local, PsExec, Docker, Linux/WSL, and remote-promotion
paths apply the same plan-scoped rule. The public
`RasCmdr.remove_plan_execution_artifacts()` helper permanently removes an
explicitly selected family from an exact allowlist and never includes geometry
HDF, DSS, terrain, or `.p##.tmp.hdf` files.

Cleanup is fail-closed: a versioned command-line executable is authoritative,
and a `ras_version`/executable mismatch across result families stops before
either family is deleted. `RasControl` follows the selected controller version.
An unversioned `Ras.exe` path is not silently treated as modern. Preprocessing-
only APIs are deliberately excluded because they must not delete prior final
results and are not an ambiguity-normalization workflow. The public cleanup
helper validates all exact
targets and their project containment before the first unlink; if the operating
system fails during deletion, `PlanExecutionCleanupError` reports both the
failed path and any partial removal. Public currency inspection uses the same
plan-declaration resolver as execution evidence. Compute-oriented currency is a
separate internal policy tied to the selected engine and treats any dual-format
project as needing a normalizing rerun.

Worker promotion is limited to successful plans, replaces destination results
atomically without treating copied mtimes as authority, and copies only the
selected primary result, exact message sidecars, and one deterministic geometry
HDF per shared geometry. Docker staging removes copied final HDF/legacy results
while preserving the required `.tmp.hdf` preprocessing input; only the exact,
structurally complete final `.p##.hdf` can be published.

One RAS 4.1 first-launch attempt encountered the optional example-project
installation prompt. The watchdog now explicitly chooses `No`/`Cancel`/`Close`
for that prompt and never installs examples as a side effect. The first attempt
is archived; the repeat lane completed successfully.

The 2D project copies contain 98 files totaling 354,028,433 bytes and executed
successfully in every 6.1-7.0 lane. Their linked DSS assets existed, but were
accepted with `execution_readiness=unknown` because this packet did not perform
deep DSS coverage inspection. It therefore establishes execution and evidence
behavior, not complete linked-asset or simulation-window coverage. That gap
remains assigned to the separate linked-asset research effort.

The archived successful outputs were inspected offline without invoking
HEC-RAS or COM under the earlier rule. They now serve as regression inputs for
mixed-format detection. A future, separately approved rerun through the
cleanup-enabled APIs is required to regenerate the canonical clean fixtures.
A final `RasControl.list_processes(show_all=True)` check found no remaining RAS
processes after the original matrix execution.

## Validation status and baseline test debt

The focused evidence, artifact-cleanup, currency, controller, command-line,
preprocessing, parallel/test-mode, local/PsExec/Docker, and remote-promotion suite passes:
**198 passed, 2 skipped**. The complete non-integration suite is not green: the final
rerun produced **2,299 passed, 40 skipped, 30 deselected, and 43 failed**. It
reproduced the same 43 unrelated failure clusters recorded at the branch base;
the increased pass count comes from the added regression coverage.
A fresh-process rerun of only the failing files produced 36 deterministic
failures and 226 passes; seven failures were suite-order dependent.

Nine representative failures spanning every major failure cluster were then
run from a temporary detached worktree at the pre-change commit `c9311e3`.
All nine failed there with the same symptoms, including citation/package
version drift, stale logging expectations, an executed tutorial notebook,
HRRR timing-fixture assumptions, Windows relative-path resolution, and the
missing `RasUnsteady._clean_boundary_selector` helper referenced by the merged
DSS-link selector tests. This establishes that those sampled failures predate
the controller, watchdog, and artifact-selection commits. It does not make the
branch globally green or waive the need to reconcile the broader baseline
failures before merge.
