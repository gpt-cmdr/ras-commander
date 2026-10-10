# Core Classes

Core classes for HEC-RAS project management and execution.

## Important Notes

Most operation classes are static namespaces: call `RasCmdr.compute_plan()` or
`RasPlan` methods directly. `RasPrj` project objects, workers, result records,
and configuration types are instances. Construct those as documented.

!!! warning "RASMapper Flag Inversion"
    When using `RasPlan.update_run_flags()`, note that RASMapper flags have **inverted logic**:

    - Standard flags: `True = -1`, `False = 0`
    - RASMapper flag: `True = 0`, `False = -1`

    This is a HEC-RAS quirk, not a library bug.

!!! tip "Input Flexibility"
    Decorated HDF readers accept the input forms documented for each method.
    Project selectors require initialization; direct paths are also supported:
    ```python
    # Accepted by this reader:
    HdfResultsMesh.get_mesh_max_ws("01")           # Plan number
    HdfResultsMesh.get_mesh_max_ws(1)              # Integer
    HdfResultsMesh.get_mesh_max_ws(Path("x.hdf")) # Path object
    ```

## Project Management

### init_ras_project

<a id="ras_commander.init_ras_project--create-a-new-rasprj-instance-with-prj-file"></a>

<a id="ras_commander.init_ras_project--initialize-using-direct-prj-file-path-new-feature"></a>

<a id="ras_commander.init_ras_project--initialize-using-project-folder-existing-behavior"></a>

<a id="ras_commander.init_ras_project--skip-results-loading-for-faster-initialization"></a>

::: ras_commander.init_ras_project
    options:
      show_root_heading: true
      heading_level: 3

### RasPrj

Project initialization populates paths and metadata tables on a `RasPrj` instance.
See the [DataFrame reference](../reference/dataframe-reference.md) for those
instance attributes; the operations below are the source-derived methods.

<a id="ras_commander.RasPrj"></a>

::: ras_commander.RasPrj.RasPrj
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - check_initialized
        - find_ras_prj
        - get_boundary_conditions
        - get_flow_entries
        - get_geom_entries
        - get_hdf_entries
        - get_hdf_paths
        - get_plan_entries
        - get_plan_info
        - get_plan_value
        - get_plans_with_results
        - get_plans_without_results
        - get_prj_entries
        - get_project_name
        - get_project_units
        - get_results_entries
        - get_unsteady_entries
        - initialize
        - print_data
        - refresh_project_crs
        - set_current_plan
        - update_results_df

### Project asset inspection

`inspect_project_assets()` builds a read-only, PyArrow-backed inventory of a
project's declared components, plan dependency closure, HDF sidecars,
RASMapper references, DSS links, restart/prior-water-surface inputs, and
gridded precipitation inputs. Use an explicit inspection depth rather than
assuming every file beside a project is required by the current plan.
The shallow `project` depth initializes project tables without opening HDF or
raster datasets for geometry metadata or CRS discovery.

```python
from ras_commander import inspect_project_assets

assets = inspect_project_assets(
    r"C:\Models\Source\Model.prj",
    depth="current_plan",
    hash_files=True,
    dss_inspection="none",
)

not_ready = assets.loc[
    (assets["required"] == True) & (assets["readiness"] == "not_ready")
]
```

::: ras_commander.RasProject.inspect_project_assets
    options:
      show_root_heading: true
      heading_level: 3

### Atomic project staging

`stage_project()` copies a complete project tree into a unique temporary
sibling, verifies every source and copied file with streaming SHA-256, creates
an explicit `RasPrj`, inventories the staged dependencies, writes a stage
manifest, and publishes with one final directory rename. It never runs or
preprocesses HEC-RAS.

The destination's parent must already exist and the destination itself must
not exist. The operation fails closed on overlap, reparse/symlink ambiguity,
lock artifacts, source or copy drift, an invalid project population, and
destination races. Failures use typed `ProjectStageError` subclasses with a
machine-readable `reason_code`; an initially existing destination retains the
standard `FileExistsError`. Existing `RasCmdr` copy behavior is unchanged.

```python
from ras_commander import stage_project

staged = stage_project(
    r"C:\Models\Source\Model.prj",
    r"D:\Runs\model-2026-08-23",
)

print(staged.destination_project_file)
print(staged.execution_readiness)
print(staged.fingerprint_algorithm)
```

The four `StageProjectResult` fingerprint fields share the explicitly versioned
`ras_commander.stage_project.framed_tree.v1` algorithm. That digest covers the
staged tree's directory population and framed file records. It is deliberately
not interchangeable with a qualification-harness source snapshot, whose
canonical-JSON digest has a separate algorithm identifier. Consumers should
compare fingerprints only when their algorithm identifiers also match. The
same stage algorithm identifier is persisted in `.ras-commander/stage.json`.

::: ras_commander.RasProject.stage_project
    options:
      show_root_heading: true
      heading_level: 3

::: ras_commander.RasProject.StageProjectResult
    options:
      show_root_heading: true
      heading_level: 3

### Exact boundary-block deletion

`RasUnsteady.delete_boundary()` intentionally requires an atomically staged
project. First inspect the staged unsteady file, select one unique row, and
pass back all of its exact evidence. Preview is the default and does not write.

```python
from ras_commander import RasUnsteady, stage_project

staged = stage_project(
    r"C:\Models\Source\Model.prj",
    r"D:\Runs\model-boundary-edit",
)
blocks = RasUnsteady.inspect_boundary_blocks(staged, unsteady_number="01")

candidate = blocks.loc[
    (blocks["bc_type"] == "Lateral Inflow Hydrograph")
    & (blocks["river"] == "River A")
    & (blocks["reach"] == "Reach 1")
    & (blocks["river_station"] == "1200")
]
if len(candidate) != 1:
    raise RuntimeError(f"Expected one exact boundary, found {len(candidate)}")
row = candidate.iloc[0]

evidence = {
    "unsteady_number": str(row["unsteady_number"]),
    "boundary_id": str(row["boundary_id"]),
    "expected_source_sha256": str(row["owner_sha256"]),
    "expected_block_sha256": str(row["block_sha256"]),
    "expected_bc_type": str(row["bc_type"]),
    "expected_location_raw": str(row["boundary_location_raw"]),
}
preview = RasUnsteady.delete_boundary(staged, **evidence)
assert preview.state == "previewed"

applied = RasUnsteady.delete_boundary(staged, **evidence, dry_run=False)
assert applied.state == "applied"
```

The operation is generic across recognized 1D and 2D boundary types; it does
not encode a protected-type policy. It rejects direct paths, partial or
index-only selectors, ambiguous encodings/types, reparse points, stale file or
block evidence, and non-local apply targets. Apply performs one verified byte
splice, CRLF newline serialization, and atomic replacement without creating a
`.bak` file. Retained content and encoding are preserved apart from newline
normalization; source selectors remain bound to the original bytes. Any mutation
invalidates the stage snapshot, so another edit requires a fresh stage and
inventory. If an exception exposes `mutation_applied=True`, the replacement
committed before a later verification/refresh failure and the stage must be
treated as requiring manual review.

## Plan Execution

### RasCmdr

<a id="ras_commander.RasCmdr"></a>

::: ras_commander.RasCmdr.RasCmdr
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - cancel_plan
        - cancel_plan_exact
        - compute_parallel
        - compute_plan
        - compute_plan_linux
        - compute_test_mode
        - inspect_execution_evidence
        - inspect_plan_processes
        - preprocess_geometry_linux
        - remove_plan_execution_artifacts

### Structured execution evidence

`RasCmdr.inspect_execution_evidence()` reads existing plan-result artifacts
without executing HEC-RAS or opening COM. It keeps HDF attributes, embedded
messages, stored message sidecars, legacy output files, process outcome, and
COM outcome as separate observations. Mechanical completion does not imply
hydraulic acceptance or an error-free computation.

`result_modified_after`, when provided, must be a timezone-aware `datetime`.
`result_artifact_structural_state` narrowly reports whether the plan-
information group is present; it does not claim that a readable HDF is a
complete result. Embedded HDF messages take precedence for health parsing,
with stored messages used as a fallback.

When HDF and `.O##` results coexist, selection follows the current plan-file
`Program Version=` declaration. Unsafe combinations raise
`ResultArtifactAmbiguityError`; the inspector never combines completion or
runtime evidence from two result families. Use
`RasCmdr.remove_plan_execution_artifacts()` for explicit, permanent,
plan-scoped remediation, or rerun through ras-commander so the selected engine
normalizes the artifacts. Actual runs clean before and after execution;
skipped runs do not delete result artifacts. Cleanup requires a resolvable selected engine
version and fails before mutation when that version is unknown. Worker and
Docker promotion accepts only a successful plan's exact final result family;
Linux preprocessing `.tmp.hdf` files are never published as results.

#### Batch promotion safety

`compute_parallel()` and `compute_test_mode()` treat destination promotion as
one batch safety decision. Immediately before copying any plan result, message
sidecar, or shared geometry HDF, ras-commander acquires an exact-create,
tokenized destination lock and requires a complete, globally empty strict
HEC-RAS process inventory. This intentionally blocks promotion when *any*
recognized HEC-RAS launcher, solver, or preprocessor is active, even when it
belongs to another plan: shared geometry makes plan-only occupancy checks
insufficient.

If the lock is already held, process inspection is incomplete, or the strict
inventory is nonempty, no candidate in the batch is promoted or finalized.
Every otherwise successful candidate is returned as unsuccessful with the
lock and process-gate evidence in `execution_details_by_plan`. Fresh outputs
remain available for explicit review or recovery at the exact
`retained_worker_folder` or `retained_test_folder` path recorded there.

The same recoverability rule applies after the gate succeeds. A missing
primary result, any artifact copy that raises or returns `False`, or a
finalization error marks the affected plan unsuccessful and retains its worker
or test folder. Each candidate plan uses a destination-local publication
transaction. Ras-commander first copies and hash-verifies the primary result,
same-run message sidecars, and any selected shared geometry HDF under a unique
hidden stage, without changing any recognized destination artifact. It then
quarantines both result families, every known plan-message sidecar, and the
shared geometry artifact being replaced. Only after that quarantine succeeds
does it commit the fresh same-run set and run finalization.

If staging, commit, verification, or finalization fails, ras-commander first
removes every fresh artifact from recognized names. It restores the complete
prior primary-family set as one safety group, then restores supporting
artifacts. If either group cannot be completed, every artifact restored so far
is re-quarantined; this avoids exposing one primary family with an ambiguous
or partial sidecar set. Hash verification must prove the exact prior
destination state before the transaction is discarded. When that proof
succeeds, `rollback_confirmed` is true and no partial publication remains.
When it cannot be proved, later publication in that batch is refused,
`partial_promotion_possible` is true, and the hidden transaction, backup
paths, and fresh worker or test folder remain available for explicit recovery.
This ordering prevents an old result primary from being paired with a message
sidecar from the failed new run.

The lock prevents two cooperative ras-commander promotion batches from racing.
It cannot prevent a person or unrelated program from launching HEC-RAS after
the process snapshot, so do not open or compute the destination project in the
GUI during promotion.

#### WSL solver supervision

On Windows, `compute_plan_linux()` uses a fail-closed WSL adapter. Before any
solver launch it atomically acquires a per-plan lease and verifies that Bash,
`setsid --wait`, `/proc` identity, durable sync, and process-group signalling
are available. The solver runs as a session/process-group leader and publishes
the lease token, its Linux PID, `/proc` start-time tick, and process-group ID
before `exec`. Recovery rejects state that is not bound to the held lease.

On timeout or Python interruption, ras-commander kills only its Windows WSL
launcher and invokes a separate WSL recovery command. Recovery sends TERM and,
if needed, KILL only after the current `/proc` identity exactly matches the
published PID, start time, and process group; it then waits for positive group
absence. Identity mismatch, unavailable identity, or incomplete recovery is
recorded as indeterminate and never authorizes a signal.

The WSL path deliberately does not remove an opposing result family before
launch. It finalizes result artifacts only after exact solver quiescence is
proved. If that proof or owned-state cleanup is uncertain, both visible result
families and the per-plan lease are preserved, result validation/promotion and
retry are refused, and a subsequent duplicate execution fails closed.

### Structured process safety

`RasControl.inspect_processes()` returns a strict host-wide inventory of
recognized HEC-RAS launchers, solvers, preprocessors, sediment, and
water-quality engines. `RasCmdr.inspect_plan_processes()` narrows that evidence
to one initialized project and plan using exact path/token signatures. Both
records expose `complete` and explicit query errors; callers making safety
decisions must fail closed when inspection is incomplete.

`RasCmdr.cancel_plan_exact()` revalidates process identity as `(pid,
create_time)` before signalling and returns matched, stopped, survivor, query-
error, timing, and tri-state quiescence evidence. Use this structured method
for supervision and recovery. An incomplete exact-plan inventory is returned
as indeterminate without sending any signal. The older Boolean
`cancel_plan()` remains a compatibility wrapper: it returns `True` only when
it found an exact match and quiescence was positively proved. Process creation,
observation, and cancellation start/finish times are Unix epoch seconds.

::: ras_commander.ExecutionEvidence.ExecutionEvidence
    options:
      show_root_heading: true
      heading_level: 4

::: ras_commander.ExecutionEvidence.EvidenceObservation
    options:
      show_root_heading: true
      heading_level: 4

::: ras_commander.ExecutionArtifacts.PlanExecutionCleanup
    options:
      show_root_heading: true
      heading_level: 4

::: ras_commander.ExecutionArtifacts.PlanExecutionCleanupError
    options:
      show_root_heading: true
      heading_level: 4

::: ras_commander.ExecutionArtifacts.ResultArtifactAmbiguityError
    options:
      show_root_heading: true
      heading_level: 4

#### Real-Time Execution Monitoring (v0.88.0+)

The `compute_plan()` `stream_callback` parameter enables real-time progress
monitoring during HEC-RAS execution. The
[execution capability and return table](../user-guide/plan-execution.md#execution-capabilities-and-return-values)
distinguishes the single-plan and batch entry points.

```python
from ras_commander import RasCmdr
from ras_commander.callbacks import ConsoleCallback

# Simple console monitoring
callback = ConsoleCallback(verbose=True)
RasCmdr.compute_plan("01", stream_callback=callback)
```

**Output:**
```
[Plan 01] Starting execution...
[Plan 01] Geometry Preprocessor Version 6.6
[Plan 01] Computing Cross Section HTAB's
[Plan 01] Starting Unsteady Flow Computations
[Plan 01] Time: 01JAN2020 0600 [  1.25% Done]
[Plan 01] SUCCESS in 45.2s
```

##### Callback Lifecycle

Callbacks receive notifications at key execution points:

1. `on_prep_start(plan_number)` - Before plan setup, including requested preprocessor-file clearing and core settings
2. `on_prep_complete(plan_number)` - After plan setup; engine preprocessing may still be required
3. `on_exec_start(plan_number, command)` - Immediately before launching the HEC-RAS subprocess
4. `on_exec_message(plan_number, message)` - Each .bco file message (real-time)
5. `on_exec_complete(plan_number, success, duration)` - After execution
6. `on_verify_result(plan_number, verified)` - After HDF verification (if `verify=True`)

##### Built-in Callbacks

::: ras_commander.callbacks.ConsoleCallback
    options:
      show_root_heading: true
      heading_level: 6

::: ras_commander.callbacks.FileLoggerCallback
    options:
      show_root_heading: true
      heading_level: 6

::: ras_commander.callbacks.ProgressBarCallback
    options:
      show_root_heading: true
      heading_level: 6

::: ras_commander.callbacks.SynchronizedCallback
    options:
      show_root_heading: true
      heading_level: 6

##### Custom Callbacks

Create custom callbacks by implementing the `ExecutionCallback` protocol:

```python
class CustomCallback:
    """Minimal custom callback - implement only what you need."""

    def on_exec_complete(self, plan_number, success, duration):
        status = "SUCCESS" if success else "FAILED"
        print(f"Plan {plan_number}: {status} in {duration:.1f}s")

# Use it
RasCmdr.compute_plan("01", stream_callback=CustomCallback())
```

`compute_parallel()` and `compute_test_mode()` do not accept `stream_callback`.
For serial monitoring, call `compute_plan()` in a loop.
`SynchronizedCallback` protects callbacks shared by caller-managed threads; it
does not enable callbacks on the batch APIs. Callback completion notifications
are distinct from the final `ComputeResult` and its artifact-handling outcome.

##### Linux-Hosted Unsteady Preparation

<a id="ras_commander.RasPreprocess"></a>

::: ras_commander.RasPreprocess.RasPreprocess
    options:
      show_root_heading: true
      heading_level: 6
      members:
        - preprocess_plan
        - run_ras_geom_preprocess
        - verify_preprocessing

`preprocess_plan()` runs Windows HEC-RAS through native Windows Python or
Windows Python hosted by Wine. For ordinary plans it stops at either the
detailed `.bco` signal or an owned `RasUnsteady.exe` descendant after
`.tmp.hdf`, `.b##`, and `.x##` are all non-empty. The returned
`PreprocessResult.signal_source` records which path was used. First-run
legal-assent dialogs are reported as blockers and are never accepted
automatically.

Gridded precipitation has a stricter readiness gate. The unsteady-flow HDF
contains the authored source payload under
`Event Conditions/Meteorology/Precipitation/Imported Raster Data`; HEC-RAS
preprocessing must materialize the solver-facing `Precipitation/Values` and
`Precipitation/Timestamp` datasets in the temporary plan HDF. The `.bco`
marker can precede that handoff, so `preprocess_plan()` waits for fresh,
complete preprocessing artifacts and validates both materialized datasets
before reporting success. Plans without gridded precipitation retain the owned
solver-process fallback. Treat a failed `PreprocessResult` as a failed
precompute; do not launch
the native solver with an incomplete temporary HDF.

`run_ras_geom_preprocess()` performs the matching vendor geometry-preprocessor
step with a bounded timeout, executable hash, before/after HDF hashes,
compute-message parsing, and HDF readability/`Geometry`-group validation.

##### BcoMonitor Utility

<a id="ras_commander.BcoMonitor"></a>

::: ras_commander.RasBco.BcoMonitor
    options:
      show_root_heading: true
      heading_level: 6
      members:
        - enable_detailed_logging
        - monitor_until_signal

##### ExecutionCallback Protocol

<a id="ras_commander.ExecutionCallback"></a>

::: ras_commander.ExecutionCallback.ExecutionCallback
    options:
      show_root_heading: true
      heading_level: 6

All callback methods are **optional** - implement only what you need. The protocol uses `@runtime_checkable` for flexible duck-typing.

### RasControl

<a id="ras_commander.RasControl"></a>

::: ras_commander.RasControl.RasControl
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - cleanup_orphans
        - force_cleanup_all
        - get_comp_msgs
        - get_controller_progid
        - get_output_times
        - get_plans
        - get_steady_results
        - get_unsteady_results
        - inspect_processes
        - list_processes
        - run_plan
        - scan_orphans
        - set_current_plan

#### RasControl Details

!!! info "Open-Operate-Close Pattern"
    Unlike other ras-commander classes, RasControl opens HEC-RAS, performs one operation, then closes it. This prevents conflicts with modern workflows and ensures clean resource management.

##### Supported Versions

| Version | Registry Key | HEC-RAS Years |
|---------|-------------|---------------|
| `"31"` | 3.1 | Legacy |
| `"41"` | 4.1 | ~2008-2014 |
| `"501"`, `"503"`, `"505"`, `"506"` | 5.0.x | 2015-2019 |
| `"60"` | 6.0 | 2020 |
| `"63"` | 6.3 | 2021-2022 |
| `"66"` | 6.6 | 2023-2024 |
| `"70"` | 7.0 | 2025+ |

##### RasControl vs RasCmdr

| Aspect | RasControl | RasCmdr |
|--------|------------|---------|
| **HEC-RAS Versions** | 3.x - 7.x (COM) | 5.x+ (command line) |
| **Data Source** | Live COM extraction | HDF file results |
| **Requires GUI** | Yes (HEC-RAS installed) | Yes (HEC-RAS installed) |
| **Use Case** | Legacy models, validation | Modern automation |
| **Returns** | pandas DataFrame | bool / dict |

##### Understanding "Max WS" in Unsteady Results

When extracting unsteady results, the **first row per cross section** (time_index=1) contains "Max WS" - the maximum at ANY computational timestep:

```python
# Unsteady results include special "Max WS" row
df = RasControl.get_unsteady_results("01")

# time_index=1 is "Max WS" (maximum at any timestep)
df_max = df[df['time_string'] == 'Max WS']

# time_index=2+ are actual output intervals
df_timeseries = df[df['time_string'] != 'Max WS']

# Parse datetime for analysis
df_timeseries['datetime'] = pd.to_datetime(
    df_timeseries['time_string'],
    format='%d%b%Y %H%M'
)
```

!!! warning "Max WS vs Output Interval Maximums"
    "Max WS" captures peaks that may occur BETWEEN output intervals. This is critical for design applications - always use "Max WS" for peak values, not `max()` of output intervals.

##### Result Columns

**Steady Results** (`get_steady_results`):

| Column | Type | Description |
|--------|------|-------------|
| `river` | str | River name |
| `reach` | str | Reach name |
| `node_id` | str | Cross section station |
| `profile` | str | Profile name |
| `wsel` | float | Water surface elevation |
| `velocity` | float | Total velocity |
| `flow` | float | Total flow |
| `froude` | float | Froude number |
| `energy` | float | Energy grade elevation |
| `max_depth` | float | Maximum channel depth |
| `min_ch_el` | float | Minimum channel elevation |

**Unsteady Results** (`get_unsteady_results`): Same columns plus `time_index`, `time_string`, `datetime`.

##### Compute Messages Fallback

The `get_comp_msgs()` method attempts to read computation messages from multiple sources:

1. First tries `.computeMsgs.txt` (modern format)
2. Falls back to `.comp_msgs.txt` (legacy format)
3. Returns empty string if neither exists

## File Operations

### RasPlan

<a id="ras_commander.RasPlan"></a>

::: ras_commander.RasPlan.RasPlan
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - add_hdf_output_variable
        - apply_hdf_output_profile
        - clone_geom
        - clone_plan
        - clone_steady
        - clone_unsteady
        - create_plan_variants
        - delete_geom
        - delete_plan
        - delete_steady
        - delete_unsteady
        - disable_hdf_output_variable
        - enable_hdf_output_variable
        - get_2d_flow_options
        - get_flow_path
        - get_geom_path
        - get_hdf_output_options
        - get_hdf_output_variables
        - get_hdf_write_parameters
        - get_next_number
        - get_plan_flow_type
        - get_plan_path
        - get_plan_title
        - get_plan_value
        - get_restart_output_settings
        - get_results_path
        - get_sediment_output_variables
        - get_shortid
        - get_unsteady_path
        - is_plan_steady_state
        - list_2d_flow_option_names
        - list_available_hdf_output_variables
        - list_hdf_output_setting_profiles
        - read_flow_description
        - read_geom_description
        - read_plan_description
        - remove_hdf_output_variable
        - renumber_geom
        - renumber_plan
        - renumber_steady
        - renumber_unsteady
        - set_2d_equation_set
        - set_2d_flow_options
        - set_geom
        - set_geom_preprocessor
        - set_hdf_output_options
        - set_hdf_output_variable
        - set_hdf_output_variables
        - set_hdf_write_parameters
        - set_num_cores
        - set_plan_title
        - set_restart_output_settings
        - set_sediment_output_variables
        - set_shortid
        - set_steady
        - set_unsteady
        - update_flow_description
        - update_geom_description
        - update_plan_description
        - update_plan_intervals
        - update_run_flags
        - update_simulation_date
        - use_optimal_hdf_settings

### RasFlowOptimization

<a id="ras_commander.RasFlowOptimization"></a>

::: ras_commander.RasFlowOptimization.RasFlowOptimization
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - compute_plan_and_get_trials
        - copy_plan_with_optimization
        - disable_plan
        - enable_plan
        - get_settings
        - get_trial_results
        - list_flow_hydrographs
        - parse_compute_messages
        - set_settings

### RasGeo

`RasGeo` is a deprecated compatibility namespace. Prefer the
[geometry APIs](geometry.md), including `GeomLandCover` for roughness editing.


<a id="ras_commander.RasGeo"></a>

::: ras_commander.RasGeo.RasGeo
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - clear_geompre_files
        - clone_geom
        - get_mannings_baseoverrides
        - get_mannings_regionoverrides
        - set_mannings_baseoverrides
        - set_mannings_regionoverrides

### RasUnsteady

<a id="ras_commander.RasUnsteady"></a>

::: ras_commander.RasUnsteady.RasUnsteady
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - batch_update_dss_references
        - configure_gridded_dss_precipitation
        - delete_boundary
        - disable_meteorology
        - ensure_2d_boundary_location
        - extract_boundary_and_tables
        - extract_tables
        - get_dss_boundaries
        - get_gate_openings
        - get_gridded_precipitation_capabilities
        - get_groundwater_interflow
        - get_initial_conditions
        - get_initial_flow_method
        - get_initial_storage_elevations
        - get_inline_hydrograph_boundaries
        - get_lateral_inflow_hydrograph
        - get_met_precipitation_config
        - get_meteorological_stations
        - get_min_storage_elevations
        - get_navigation_dam
        - get_non_newtonian_clastic
        - get_non_newtonian_concentration
        - get_non_newtonian_herschel_bulkley
        - get_non_newtonian_method
        - get_non_newtonian_shear
        - get_point_evapotranspiration
        - get_prior_ws_filename
        - get_rating_curve
        - get_restart_settings
        - get_rules_bc
        - get_stage_flow_hydrograph
        - get_uniform_lateral_inflow_hydrograph
        - get_unique_dss_subbasins
        - identify_tables
        - inspect_boundary_blocks
        - parse_fixed_width_table
        - preview_dss_references
        - print_boundaries_and_tables
        - read_unsteady_description
        - replace_2d_boundary_locations
        - set_boundary_dss_link
        - set_boundary_inline_hydrograph
        - set_constant_precipitation
        - set_flow_hydrograph_qmin
        - set_flow_hydrograph_slope
        - set_gate_openings
        - set_gridded_precipitation
        - set_gridded_precipitation_geotiff
        - set_gridded_precipitation_grib
        - set_groundwater_interflow
        - set_hydrograph_fixed_start_time
        - set_ic_from_output_profile
        - set_initial_conditions
        - set_initial_flow_method
        - set_initial_storage_elevation
        - set_lateral_inflow_hydrograph
        - set_met_precipitation_mode
        - set_meteorological_station
        - set_navigation_dam
        - set_non_newtonian_clastic
        - set_non_newtonian_concentration
        - set_non_newtonian_herschel_bulkley
        - set_non_newtonian_method
        - set_non_newtonian_shear
        - set_normal_depth_boundary
        - set_point_evapotranspiration
        - set_precipitation_hyetograph
        - set_prior_ws_filename
        - set_rating_curve
        - set_restart_settings
        - set_rules_bc
        - set_stage_flow_hydrograph
        - set_stage_hydrograph_tw_check
        - set_uniform_lateral_inflow_hydrograph
        - update_boundary_dss_paths
        - update_dss_path_by_station
        - update_dss_run_identifier
        - update_flow_multiplier_by_station
        - update_flow_title
        - update_restart_settings
        - update_unsteady_description
        - validate_initial_flow_stations
        - write_table_to_file

### RasSteady

<a id="ras_commander.RasSteady"></a>

::: ras_commander.RasSteady.RasSteady
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - boundary
        - create_flow_file
        - critical_depth
        - known_water_surface
        - normal_depth
        - rating_curve
        - read_flow_file
        - update_flow_file
        - validate_flow_file_data
        - write_flow_file

Compatibility aliases: `create` → `create_flow_file`, `known_ws` → `known_water_surface`, `parse_flow_file` → `read_flow_file`, `read` → `read_flow_file`, `update` → `update_flow_file`, `validate` → `validate_flow_file_data`, `write` → `write_flow_file`, `write_file` → `write_flow_file`.

## Utilities

### RasUtils

<a id="ras_commander.RasUtils"></a>

::: ras_commander.RasUtils.RasUtils
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - backup_files
        - calculate_error_metrics
        - calculate_percent_bias
        - calculate_rmse
        - check_file_access
        - clone_file
        - consolidate_dataframe
        - convert_to_dataframe
        - create_directory
        - decode_byte_strings
        - discover_ras_versions
        - dos2unix
        - find_files_by_extension
        - find_nearest_neighbors
        - find_nearest_value
        - find_valid_ras_folders
        - get_file_modification_time
        - get_file_size
        - get_next_number
        - get_plan_path
        - horizontal_distance
        - ignore_windows_reserved
        - is_valid_ras_folder
        - is_windows_reserved_name
        - normalize_ras_number
        - perform_kdtree_query
        - remove_prj_entry
        - remove_with_retry
        - rename_prj_entry
        - rollback_geometry
        - safe_resolve
        - safe_write_geometry
        - save_to_excel
        - update_file
        - update_plan_file
        - update_project_file
        - validate_geometry_file_basic

#### Method Categories

##### File Operations

| Method | Description |
|--------|-------------|
| `create_directory(path)` | Ensure directory exists, create if needed |
| `find_files_by_extension(folder, ext)` | Find all files with given extension |
| `get_file_size(path)` | Get file size in bytes |
| `get_file_modification_time(path)` | Get file modification timestamp |
| `clone_file(src, dest)` | Copy file to new location |
| `update_file(path, content)` | Write content to file |
| `remove_with_retry(path, retries=3)` | Delete file with retry logic |
| `check_file_access(path, mode)` | Verify file access permissions |

##### Plan/Project Helpers

| Method | Description |
|--------|-------------|
| `normalize_ras_number(number)` | Convert "1", "01", "p01" to "01" format |
| `get_plan_path(plan_number)` | Get full path to plan file |
| `get_next_number(folder, prefix)` | Find next available plan/geom number |
| `update_plan_file(path, key, value)` | Update single key in plan file |
| `update_project_file(prj_path, updates)` | Batch update .prj file |

##### Data Conversion

| Method | Description |
|--------|-------------|
| `convert_to_dataframe(path)` | Load CSV/Excel to DataFrame |
| `save_to_excel(df, path, sheet)` | Save DataFrame to Excel |
| `decode_byte_strings(data)` | Decode HDF byte strings to Python strings |
| `consolidate_dataframe(df, group_by)` | Group and aggregate DataFrame rows |

##### Statistical Analysis

| Method | Description |
|--------|-------------|
| `calculate_rmse(observed, predicted)` | Root Mean Square Error |
| `calculate_percent_bias(obs, pred)` | Percent bias metric |
| `calculate_error_metrics(obs, pred)` | All metrics (RMSE, NSE, PBIAS, R²) |

```python
from ras_commander import RasUtils
import numpy as np

observed = np.array([100, 120, 140, 160, 180])
predicted = np.array([105, 125, 135, 165, 175])

metrics = RasUtils.calculate_error_metrics(observed, predicted)
print(f"RMSE: {metrics['rmse']:.2f}")
print(f"NSE: {metrics['nse']:.3f}")
print(f"PBIAS: {metrics['pbias']:.1f}%")
```

##### Spatial Operations

| Method | Description |
|--------|-------------|
| `perform_kdtree_query(points, query, max_dist)` | Find nearest points using KDTree |
| `find_nearest_neighbors(points, max_dist)` | Find nearest neighbor for each point |
| `find_nearest_value(array, target)` | Find value closest to target |
| `horizontal_distance(p1, p2)` | Calculate 2D distance between points |

```python
from ras_commander import RasUtils
import numpy as np

# Find nearest mesh cell for a list of query points
mesh_centroids = np.array([[0, 0], [10, 10], [20, 20]])
query_points = np.array([[5, 5], [15, 15]])

indices = RasUtils.perform_kdtree_query(
    mesh_centroids,
    query_points,
    max_distance=10.0
)
# Returns [1, 2] - nearest cell indices
```

### RasExamples

<a id="ras_commander.RasExamples"></a>

::: ras_commander.RasExamples.RasExamples
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - clean_projects_directory
        - download_fema_ble_model
        - download_sciencebase_model
        - extract_project
        - get_example_projects
        - get_sciencebase_model_info
        - inspect_sciencebase_model
        - is_project_extracted
        - list_categories
        - list_projects
        - list_sciencebase_models
        - organize_ebfe_model
        - validate_sciencebase_model

<a id="ras_commander.RasMap"></a>

### RasMap

See the [RASMapper API section](rasmapper/index.md) for the complete task-grouped
reference for display, classification authoring, and geometry completion.
[Meshing](meshing.md), [Results Queries](results-queries.md), and
[Stored Maps](stored-maps.md) have dedicated reference pages.

Full method reference: [RasMap](rasmapper/index.md).

#### RASMapper Layer Discovery

The layer-list methods read the `.rasmap` file and return one dataframe row per layer. Use these when a workflow needs discoverable layer names and resolved paths instead of the compact, list-valued `ras.rasmap_df` project summary.

```python
from ras_commander import RasMap

terrain_layers = RasMap.list_terrain_layers(project_path)
terrain_display = RasMap.list_terrain_display_settings(project_path)
landcover_layers = RasMap.list_landcover_layers(project_path)
soils_layers = RasMap.list_soils_layers(project_path)
infiltration_layers = RasMap.list_infiltration_layers(project_path)
```

`list_land_classification_layers()` is the broad parser for RASMapper `Type="LandCoverLayer"` entries. The land-cover, soils, and infiltration methods are filtered convenience wrappers around that catalog.

#### Classification Polygon Overrides

`RasMap.list_land_classification_polygons()` provides read-only extraction for
land-classification sidecars. For HEC-RAS 6.x and 7.0.x
`LC Type=LandCover` sidecars, `add_land_classification_polygon()`,
`update_land_classification_polygon()`, and
`delete_land_classification_polygon()` persist one polygon through the native
RASMapper feature-layer API. The selected class must already exist; these
methods do not remap raster classifications or create/remove classes.

Polygon input must contain one effective polygon. A one-member `MultiPolygon`
is normalized, while true multipart input and interior rings are rejected
before mutation. HEC-RAS 6.0 through 7.0.1 persists native polygon holes but
its land-cover classification resampler flattens them; accepting them would
therefore misrepresent their hydraulic effect. Model an exclusion by splitting
the intended coverage into explicit, non-overlapping hole-free polygons.
GeoPandas inputs must use the sidecar CRS; raw Shapely and GeoJSON coordinates
are assumed to already use that CRS. Every supported mutation creates a durable
backup, saves through RASMapper, and validates a fresh reload.

HEC-RAS 5.x, soils/infiltration polygon mutation, and
`remove_unused_class=True` fail with migration guidance. Geometry Manning
regions remain the supported 5.x override route, while soils and infiltration
sidecars should be rebuilt through their native authoring APIs when their
classification structure changes.

This is separate from polygon inputs accepted by `restrict_to_extent`: those
inputs define a single buffered processing extent and remain supported.

#### Terrain Display Settings

`RasMap.list_terrain_display_settings()`, `RasMap.get_terrain_display_settings()`, and `RasMap.set_terrain_display_settings()` expose RASMapper terrain display controls persisted in `.rasmap` XML. They cover hillshade display and Z factor, contour display and interval, and terrain stitch-edge plot options such as `Plot stitch TIN edges`.

```python
RasMap.set_terrain_display_settings(
    project_path,
    terrain_name="TerrainWithChannel",
    hillshade_enabled=True,
    hillshade_z_factor=2.0,
    contour_enabled=True,
    contour_interval=5.0,
    stitch_edges_enabled=True,
)
```

CLB-272 owns these terrain display toggles. CLB-253 remains the separate terrain-modification gap for generating terrain changes such as channel modifications and interpolated cross-section terrain products.

#### Geometry HDF Layer Associations

`RasMap.get_hdf_geometry_association()` reads `/Geometry` association
attributes from geometry HDFs and plan/result HDFs without mutation.
`RasMap.associate_geometry_layers()` delegates association changes to the
selected HEC-RAS generation's native geometry-association API and validates
the native readback.

```python
association = RasMap.get_hdf_geometry_association("MyModel.g01.hdf")
print(association["terrain_hdf_path"])

RasMap.associate_geometry_layers(
    project_path,
    "MyModel.g01.hdf",
    terrain_hdf_path="Terrain/ExistingTerrain.hdf",
    landcover_hdf_path="Land Classification/LandCover.hdf",
    infiltration_hdf_path="Land Classification/Infiltration.hdf",
)
```

!!! warning "Compiled HDF only"
    `associate_geometry_layers()` updates an existing `.g##.hdf` through
    HEC-RAS. It does not compile plain-text `.g##` geometry into HDF or create
    missing geometry datasets.

To exclude infiltration from a derived child, call
`RasMap.clear_geometry_infiltration("Child.g02.hdf")` on a cloned geometry.
It removes only the compiled geometry's infiltration filename, layer name,
and file-date attributes, verifies the association is absent, and returns the
resolved `Path`. It accepts `str` or `Path`, is idempotent, and rejects filenames
other than `.gNN.hdf` before opening them. Terrain, land-cover, and other
attributes are preserved. Existing infiltration property tables remain stale;
rebuild native geometry/property tables before using the child. The method
requires a directly linked `/Geometry` group owned by the supplied HDF;
external links, soft links, and non-group objects are rejected before writable
access. It edits a temporary copy in the same directory, verifies all three
attributes are absent, and atomically replaces the supplied HDF only after
validation. Staging, deletion, validation, or replacement failures preserve
the original bytes. An absent association leaves the file byte-identical.
The directory must allow temporary-file creation and replacement. The method
does not edit a RAS Mapper file or plan.

<a id="ras_commander.RasProcess"></a>

### RasProcess

See [stored maps](stored-maps.md) and
[geometry completion](rasmapper/index.md) for the full method reference.

Full method reference: [RasProcess](stored-maps.md).

#### RasProcess Details

!!! info "RasProcess.exe CLI"
    RasProcess.exe is an undocumented command-line interface bundled with HEC-RAS that enables headless automation of RASMapper operations. The `RasProcess` class wraps this CLI for programmatic access.

##### Geometry Association Validator

`validate_geometry_association_cli()` runs the native `RasProcess.exe SetGeometryAssociation` command and compares the resulting `/Geometry` attributes against ras-commander's expected HEC-RAS-style attributes.

```python
from ras_commander import RasProcess

result = RasProcess.validate_geometry_association_cli(
    "MyModel.g01.hdf",
    terrain_hdf_path="Terrain/ExistingTerrain.hdf",
    landcover_hdf_path="Land Classification/LandCover.hdf",
    ras_version="7.0",
)

print(result["passed"])
print(result["return_code"])
print(result["mismatches"])
```

The returned dictionary includes the native command arguments, return code, stdout/stderr, before/after attributes, expected attributes, mismatch list, and `passed`.

!!! danger "In-place mutation"
    This method mutates the supplied HDF. It exists as a native reference validator for disposable copies or intentional validation runs. Normal workflows should call `RasMap.associate_geometry_layers()`.

##### Supported Map Types

| Parameter | XML Type | Display Name | Default |
|-----------|----------|--------------|---------|
| `wse` | elevation | WSE | True |
| `depth` | depth | Depth | True |
| `velocity` | velocity | Velocity | True |
| `froude` | froude | Froude | False |
| `shear_stress` | Shear | Shear Stress | False |
| `depth_x_velocity` | depth and velocity | D * V | False |
| `depth_x_velocity_sq` | depth and velocity squared | D * V² | False |

##### Profile Selection

The `profile` parameter accepts:

- `"Max"` - Maximum values across all timesteps (default)
- `"Min"` - Minimum values across all timesteps
- Specific timestamp string from `get_plan_timestamps()` (e.g., `"10SEP2018 02:30:00"`)

##### Basic Usage

```python
from ras_commander import init_ras_project, RasProcess

# Initialize project
init_ras_project("path/to/project", "7.0")

# Generate default maps (WSE, Depth, Velocity)
results = RasProcess.store_maps(
    plan_number="01",
    profile="Max",
    wse=True,
    depth=True,
    velocity=True
)

# Results is a dict: {'wse': [Path(...)], 'depth': [...], ...}
for map_type, files in results.items():
    print(f"{map_type}: {len(files)} file(s)")
```

##### Batch Processing

```python
# Generate maps for ALL plans with HDF results
all_results = RasProcess.store_all_maps(
    profile="Max",
    wse=True,
    depth=True,
    velocity=True,
    froude=True
)

for plan_num, files in all_results.items():
    print(f"Plan {plan_num}: {sum(len(f) for f in files.values())} files")
```

##### Timestep Maps

```python
# Get available timestamps
timestamps = RasProcess.get_plan_timestamps("01")
print(f"Available: {timestamps[:3]}...")  # ['10SEP2018 00:00:00', ...]

# Generate map for specific time
results = RasProcess.store_maps(
    plan_number="01",
    profile=timestamps[10],  # 10th timestep
    wse=True
)
```

##### Steady Profile Batch

`RasProcess.store_maps_at_steady_profiles()` configures all requested profile
products in one `.rasmap` update and invokes aggregate `StoreAllMaps` exactly
once. `profiles=None` selects all HDF profiles; exact names and zero-based
indexes can be mixed. One inundation boundary for the final selected profile is
included by default. Supported profile rasters are `wse`, `depth`, `velocity`,
`froude`, `shear_stress`, `depth_x_velocity`, `depth_x_velocity_sq`, and
`flow`.

```python
frame = RasProcess.store_maps_at_steady_profiles(
    "01",
    profiles=None,
    map_types=("depth",),
    output_path="steady_maps",
)
```

Rows carry `status` (`generated` or `missing`). When a requested product is
missing, generated products are preserved and
`StoredMapProductsIncompleteError` is raised with the full frame in
`error.frame` (`raise_on_missing=False` returns the frame instead).

Use `RasMap.store_all_maps(mode="steady_profiles", ...)` when a directly
JSON-serializable project summary is preferred.

!!! warning "Georeferencing Fix"
    RasProcess.exe has a known bug where generated TIFs may lack proper CRS information.
    Set `fix_georef=True` (default) to automatically apply the CRS from the project's
    projection file using rasterio.

##### Custom Output Path

By default, RasProcess.exe writes to `<project_folder>/<Plan ShortID>/`. Use the `output_path` parameter to redirect output to any directory:

```python
# Output to custom location
results = RasProcess.store_maps(
    plan_number="01",
    output_path="C:/Exports/FloodMaps",
    depth=True, wse=True
)
# Files moved to C:/Exports/FloodMaps/ after generation
```

!!! note "How output_path Works"
    The default `StoreAllMaps` command hardcodes output to `<Plan ShortID>/`.
    When `output_path` is specified, individual `StoreMap` XML commands are
    used instead, with an absolute `OutputBaseFilename` that bypasses the
    ShortID prefix via C#'s `Path.Combine()` behavior. Relative paths are
    resolved against the project folder.
