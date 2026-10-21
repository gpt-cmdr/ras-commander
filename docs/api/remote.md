# Remote Modules

Classes and functions for distributed HEC-RAS execution across local, PsExec,
and Docker workers.

## Factory Function

### init_ras_worker

Create workers with `init_ras_worker()` and the options for the selected worker
type. The factory returns a `LocalWorker`, `PsexecWorker`, or `DockerWorker` for
the implemented backends.

## Worker Classes

### LocalWorker

Run plans in isolated folders on the control machine:

```python
from ras_commander.remote import init_ras_worker

local = init_ras_worker(
    "local",
    worker_folder=r"C:\RasRemote",
    cores_total=8,
    cores_per_plan=4,
)
```

### PsexecWorker

Run plans on a Windows machine through PsExec and an accessible network share:

```python
from ras_commander.remote import init_ras_worker

remote = init_ras_worker(
    "psexec",
    hostname="WORKSTATION-01",
    share_path=r"\\WORKSTATION-01\RasRemote",
    worker_folder=r"C:\RasRemote",
    ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.6\Ras.exe",
    session_id=2,
    cores_total=16,
    cores_per_plan=4,
)
```

`session_id` must be a positive integer. PsExec always targets that desktop
session with `-i <session_id>`. When `system_account=True`, the command uses both
`-s` and `-i <session_id>`; SYSTEM remains unsuitable for most interactive
HEC-RAS runs.

The PsExec worker uses the command-line interface and requires HEC-RAS 5 or
newer. It rejects 4.x before staging because those versions require COM.
For 5.x, it sets Current Plan only in the staged project and uses the
project-first command form. Result copyback publishes the selected result
and exact fresh completion-message sidecars together, removes stale
destination messages, and retains the worker copy if publication fails.

### DockerWorker

Run plans with a local Docker daemon and an image implementing the
`DockerWorker` shell-runner contract. `hecras:6.6` below is an illustrative
local image tag, not a public Docker Hub reference. For the published paired
images, use [RasDocker](containers.md) and the
[container catalog](../user-guide/container-images.md):

```python
from ras_commander.remote import init_ras_worker

docker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    staging_directory=r"C:\RasDocker",
    cores_total=8,
    cores_per_plan=4,
)
```

### Supported worker types

`init_ras_worker()` accepts `"psexec"`, `"local"`, and `"docker"`. Any other
worker type raises `ValueError`. Slurm/HPC execution is not a worker backend:
use the `RasSlurm` portable-request adapter below
([Slurm Portable Execution](../user-guide/slurm-portable-execution.md)) or
`RasApptainer`, a static API for one native-Linux unsteady solve per Slurm
allocation with an optional Wine prepare job
([Slurm + Apptainer Execution](../user-guide/slurm-apptainer-execution.md)).

## Execution

### compute_parallel_remote

Execute queued plans across the worker pool:

```python
from ras_commander.remote import compute_parallel_remote

results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04"],
    workers=[local, remote],
    num_cores=4,
    force_rerun=False,
    max_concurrent=None,
    autoclean=True,
    copy_geometry_outputs=True,
)
```

`num_cores` must be at least 1. The scheduler enforces each worker's effective
capacity as the smaller of its configured `max_parallel_plans` and
`cores_total // num_cores`. Plans remain queued until a real worker slot is free,
so a slow host cannot be oversubscribed and a faster host can accept later plans.
Workers with lower `queue_priority` values are preferred when capacity is
available.

For PsExec runs, the staged plan is rewritten to use `num_cores`; the source plan
and source project dataframes are not changed. For local and PsExec workers, set
`copy_geometry_outputs=False` to copy the plan-result HDF back without copying
geometry HDF and preprocessor outputs. The default remains `True`.

!!! warning "Concurrent geometry copyback"
    `copy_geometry_outputs=True` preserves the previous behavior, but concurrent
    local or PsExec plans that share a geometry can race while copying the same
    geometry outputs. For concurrent scenario ensembles using already-preprocessed
    shared geometry, set `copy_geometry_outputs=False`.

The return value maps each plan number to an `ExecutionResult` with `success`,
`worker_id`, `hdf_path`, `result_path`, `result_format`, `error_message`, and
`execution_time` fields. `result_path` identifies the selected HDF or legacy
output artifact; `result_format` is `"hdf"` or `"legacy"` when one result
family is available.

The progress watchdog stops queued submissions when no plan finishes within the
slowest worker's `max_runtime_minutes` plus a staging/copy-back margin. It then
waits for already-started worker tasks before returning so those tasks cannot
continue mutating copied project outputs after the API call has returned.

## Portable Plan Execution

Use the [portable Slurm tutorial](../user-guide/slurm-portable-execution.md)
for site configuration, rendering, staging, submission, and collection.
The [backend comparison](../user-guide/execution-backends.md) explains how
this contract differs from `RasDocker`, `DockerWorker`, and `RasApptainer`.

Portable execution runs one prepared steady or unsteady plan per request,
always with one CPU core, inside a pinned container. Requests and receipts are
versioned JSON (`ras-commander-execution-request/v1`,
`ras-commander-execution-receipt/v1`), and every path in a request is relative
to the request file's directory, so the same bundle runs through Docker or
Slurm/Apptainer without changes.

```python
from ras_commander.remote import (
    RasExecutionRequest,
    RasPortableDocker,
    validate_execution_receipt,
)
from ras_commander.RasSlurm import RasSlurm, SlurmSiteConfig, SlurmTransportConfig

request = RasExecutionRequest.create(
    execution_id="reach-001",
    request_directory="bundles/reach-001",
    source_project_path="input/Model.prj",
    plan_number="02",
    output_directory="results",
    ras_executable=r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe",
    container_identity="registry.example/hecras-steady@sha256:<64 hex>",
)
request_path = request.write("bundles/reach-001/request.json")
docker_result = RasPortableDocker.execute_request(request_path)
```

- `RasExecutionRequest.create()` records the SHA-256 of the project file and
  of the whole project tree. `read()` and `from_dict()` reject unknown fields.
- `request.payload_sha256` (also available as the backward-compatible
  `request.digest`) identifies the retained JSON request. Optional fields that
  were omitted stay omitted, while supplied values are emitted in their
  validated portable spelling. A new receipt therefore binds the caller's
  retained field set rather than silently inserting defaults.
- `request.specification_sha256` identifies the normalized execution meaning.
  Requests that differ only by omission of default-valued optional fields have
  different payload identities but the same specification identity. Use this
  second digest for cache keys or governed retry comparisons; continue using
  the payload identity to authenticate a particular retained request. Receipt
  validation also accepts the normalized digest written by older v1 executors,
  preserving validation of existing results.
- In the container, `python -m ras_commander.remote.execute_request
  execute-request /job/request.json` copies the project to
  `<output>/runtime_project`, runs `RasCmdr.compute_plan(num_cores=1,
  max_runtime=timeout_seconds)`, parses the compute messages, runs
  `validate_steady_results`, and writes `<output>/execution_receipt.json`. On
  Linux, a Windows `ras_executable` is run through Windows Python under Wine.
  This needs the image variables `RAS_COMMANDER_WINE_PREFIX_SEED` and
  `RAS_COMMANDER_WINE_PYTHON`, plus `RAS_COMMANDER_WINE_ARCH` (optional,
  default `win64`) and `RAS_COMMANDER_WINE_CPU_SHIM` (optional absolute path to
  the [CPU-numbering shim](../user-guide/apptainer-images.md#cpu-numbering-shim),
  preloaded for Wine processes; empty or `0` disables it). The executor also
  disables the Wine debugger (`winedbg.exe=d`) so a crash exits instead of
  waiting. The [Wine executor image](../user-guide/apptainer-images.md#wine-executor-image)
  sets all four. Each request gets its own copy of the Wine prefix in
  Python's temporary directory, selected through the process `TMPDIR` where
  applicable. Fleet runners should bind that directory to writable node-local
  scratch. The temporary parent must be an absolute regular directory outside
  the request bundle and image seed. The executor maps the actual copied prefix
  into Windows, removes it after the attempt, and keeps project results and
  receipts in the declared output directory. Runtime staging messages identify
  prefix-copy start, completion, and delegated execution start. Solver deadlines
  and the requirement for an absent or empty output directory remain unchanged.
- `RasPortableDocker.execute_request()` and `execute_pool(max_concurrent=8)`
  mount the bundle read-only and only the output directory writable.
- `RasSlurm.render_submission()`, `stage()`, `submit()`, `status()`,
  `cancel()`, `collect()`, and `submit_batch()` run requests as one
  exclusive-node pool (`execution_mode="pool"`) or a throttled job array
  (`execution_mode="array"`, `array_throttle`). Each step runs
  `apptainer exec --contain --cleanenv` with a private
  `<node_scratch_root>/<jobid>/ras-commander-<execution_id>-*` bound as `/tmp`.
  `SlurmTransportConfig` supports `mode="local"` or `mode="ssh"`, with
  `transfer_mode="rsync"` or `"scp"`.
- `validate_execution_receipt()` checks that a receipt belongs to its request
  and container image. Pass `verify_result_hdf_digest=True` after results cross
  a transfer boundary.

### Stored maps after hydraulic validation

A request can also ask for RASMapper steady-profile stored maps:

```python
request = RasExecutionRequest.create(
    ...,  # the same arguments as above
    stored_maps={
        "terrain_name": "FIM 3DEP Terrain",
        "profiles": None,            # every profile, or exact names / 0-based indexes
        "map_types": ["depth"],      # default
        "inundation_boundary": False,  # default
        "timeout_seconds": 1800,     # default
    },
)
```

- The block is validated by `StoredMapsRequest`. It records its own schema
  (`ras-commander-stored-maps-request/v1`) and rejects unknown fields. Without
  the block, request and receipt JSON is exactly the original v1 contract, and
  request digests don't change. Executors from before this block reject a
  request that has one, because they don't accept unknown fields.
- The executor runs `RasProcess.store_maps_at_steady_profiles()` only after
  the steady results pass hydraulic validation. It runs on the runtime project
  copy with a newly initialized `RasPrj` and writes to `<output>/maps`.
- The receipt gets a `stored_maps` section with these fields:
  - `requested`: the block from the request
  - `status`: `passed`, `failed`, or `skipped`
  - `reason_code`
  - `elapsed_seconds`
  - `output_directory` (always `maps`)
  - `products`: one row per product, with `profile_index`, `profile_name`,
    `map_type`, `primary_path` (relative to the output directory), and
    `file_count`
  - `error`
- The reason codes are:

  | Code | Meaning |
  |---|---|
  | `STORED_MAPS_COMPLETED` | Every requested product was produced. |
  | `STORED_MAPS_SKIPPED_HYDRAULICS_NOT_VALIDATED` | Hydraulic validation did not pass, so maps were not run. |
  | `STORED_MAPS_FAILED` | Map generation raised an error. |
  | `STORED_MAPS_TIMEOUT` | Map generation ran past `timeout_seconds`. |
  | `STORED_MAPS_OUTPUT_INVALID` | The product table returned is missing required columns. |
  | `STORED_MAPS_NO_PRODUCTS` | No products were returned. |
  | `STORED_MAPS_PRODUCT_MISSING` | A requested product was not produced (`StoredMapProductsIncompleteError`, or a primary file is missing). The products that were generated are still listed in `products`. |
  | `STORED_MAPS_OUTPUT_OUTSIDE_RESULTS` | A product was written outside `maps/`. |
  | `STORED_MAPS_RESULT_HDF_CHANGED` | Mapping changed the result HDF after it was validated. |

- **Success rule:** a mapping failure never changes `solver_verified`,
  `hydraulic_validated`, `result_validation`, or `result_hdf_sha256`. When maps
  are requested, receipt `success` requires hydraulic success and a `passed`
  `stored_maps` section. `validate_execution_receipt()` also checks that the
  section matches the request and that every product's primary file exists
  under the output directory.
- **Receipt consistency:** a `passed` section must list exactly one row for
  each requested profile and map type, plus a boundary row only when one was
  requested. `skipped` appears exactly when hydraulic validation did not pass.
- **`null` is rejected:** leave the block out instead of writing
  `"stored_maps": null`.
- **Timeouts:** each executor's time limit is
  `timeout_seconds + stored_maps.timeout_seconds`
  (`RasExecutionRequest.execution_timeout_seconds`). Each executor adds its own
  margin on top of that: 120 s for Docker, 300 s for the Wine handoff, and
  420 s for the Slurm step launcher. The launcher script is unchanged. Only
  the StoreAllMaps helper run itself is bounded by `stored_maps.timeout_seconds`. Setting
  up the project, fixing georeferencing, and re-hashing the result HDF use the
  executor margin. `SlurmSiteConfig.time_limit` is not checked against the step
  budgets, so set it high enough for all of them.

## Installation

```bash
# Base package, including local and PsExec workers
pip install ras-commander

# Docker and all optional remote backends
pip install ras-commander[remote-docker]
pip install ras-commander[remote-all]
```

## Complete source reference

### init_ras_worker source reference

::: ras_commander.remote.RasWorker.init_ras_worker
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### load_workers_from_json source reference

::: ras_commander.remote.RasWorker.load_workers_from_json
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### compute_parallel_remote source reference

::: ras_commander.remote.Execution.compute_parallel_remote
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### get_worker_status source reference

::: ras_commander.remote.Execution.get_worker_status
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### LocalWorker source reference

::: ras_commander.remote.LocalWorker.LocalWorker
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### PsexecWorker source reference

::: ras_commander.remote.PsexecWorker.PsexecWorker
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### DockerWorker source reference

::: ras_commander.remote.DockerWorker.DockerWorker
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### ExecutionResult source reference

::: ras_commander.remote.Execution.ExecutionResult
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### PreprocessPolicy source reference

::: ras_commander.remote.ExecutionContract.PreprocessPolicy
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### RasExecutionRequest source reference

::: ras_commander.remote.ExecutionContract.RasExecutionRequest
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - create
        - from_dict
        - read
        - resolve_paths
        - to_dict
        - write

### RasExecutionReceipt source reference

::: ras_commander.remote.ExecutionContract.RasExecutionReceipt
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - read
        - to_dict
        - write

### StoredMapsRequest source reference

::: ras_commander.remote.ExecutionContract.StoredMapsRequest
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - from_dict
        - to_dict

### validate_execution_receipt source reference

::: ras_commander.remote.ExecutionContract.validate_execution_receipt
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### validate_steady_results source reference

::: ras_commander.remote.PortableExecution.validate_steady_results
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### validate_unsteady_results source reference

::: ras_commander.remote.PortableExecution.validate_unsteady_results
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### RasPortableDocker source reference

::: ras_commander.remote.RasPortableDocker.RasPortableDocker
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - build_execute_command
        - execute_pool
        - execute_request

### PortableDockerExecutionResult source reference

::: ras_commander.remote.RasPortableDocker.PortableDockerExecutionResult
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### PortableDockerPoolResult source reference

::: ras_commander.remote.RasPortableDocker.PortableDockerPoolResult
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### RasSlurm source reference

::: ras_commander.RasSlurm.RasSlurm
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - cancel
        - collect
        - render_submission
        - stage
        - status
        - submit
        - submit_batch

### RasApptainer source reference

::: ras_commander.RasApptainer.RasApptainer
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - cancel
        - check_solver_ready
        - collect
        - collect_prepare
        - load_profile
        - pull_command
        - render_job
        - render_prepare_job
        - status
        - submit

### RasContainerImages source reference

::: ras_commander.RasContainerImages.RasContainerImages
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - applicable_roles
        - cache_directory
        - catalog
        - ensure_sif_command
        - get
        - normalize_version
        - resolve_sif

### SlurmSiteConfig source reference

::: ras_commander.RasSlurm.SlurmSiteConfig
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### SlurmTransportConfig source reference

::: ras_commander.RasSlurm.SlurmTransportConfig
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### SlurmSubmission source reference

::: ras_commander.RasSlurm.SlurmSubmission
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - from_dict
        - read
        - to_dict
        - write

### SlurmStatus source reference

::: ras_commander.RasSlurm.SlurmStatus
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### SlurmTaskAccounting source reference

::: ras_commander.RasSlurm.SlurmTaskAccounting
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### SlurmCollection source reference

::: ras_commander.RasSlurm.SlurmCollection
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### Wine request path translation

On POSIX hosts, the portable CLI checks the copied task-private prefix's `Z:`
symlink. When it resolves to the POSIX root, an absolute request path without
parent traversal or Windows drive/separator syntax in a POSIX component is translated directly to the equivalent `Z:` path. This
avoids a separate cold Wine startup just to translate a path. Prefixes with
other drive mappings or incompatible component names retain `winepath` conversion and its error handling.
Delegated Windows Python execution, request validation, execution deadlines,
source immutability and task-private wineserver shutdown stay unchanged.
