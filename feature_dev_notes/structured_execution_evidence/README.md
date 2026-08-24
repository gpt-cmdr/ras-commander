# Structured execution evidence

Status: **E01a public API approved and implemented; installed-engine gates remain closed**

Date: 2026-08-24

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
