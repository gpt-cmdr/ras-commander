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

Run plans with a local Docker daemon and an HEC-RAS Linux image:

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

## Portable Steady Execution

Portable execution runs one prepared steady plan per request, always with one
CPU core, inside a pinned container. Requests and receipts are versioned JSON
(`ras-commander-execution-request/v1`, `ras-commander-execution-receipt/v1`),
and every path in a request is relative to the request file's directory, so
the same bundle runs through Docker or Slurm/Apptainer without changes.

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
- In the container, `python -m ras_commander.remote.execute_request
  execute-request /job/request.json` copies the project to
  `<output>/runtime_project`, runs `RasCmdr.compute_plan(num_cores=1,
  max_runtime=timeout_seconds)`, parses the compute messages, runs
  `validate_steady_results`, and writes `<output>/execution_receipt.json`. On
  Linux, a Windows `ras_executable` is run through Windows Python under Wine.
  This needs the image variables `RAS_COMMANDER_WINE_PREFIX_SEED` and
  `RAS_COMMANDER_WINE_PYTHON`, plus `RAS_COMMANDER_WINE_ARCH` (optional,
  default `win64`). Each request gets its own copy of the Wine prefix.
- `RasPortableDocker.execute_request()` and `execute_pool(max_concurrent=8)`
  mount the bundle read-only and only the output directory writable.
- `RasSlurm.render_submission()`, `stage()`, `submit()`, `status()`,
  `cancel()`, `collect()`, and `submit_batch()` run one exclusive-node Slurm
  allocation. `SlurmTransportConfig` supports `mode="local"` or `mode="ssh"`,
  with `transfer_mode="rsync"` or `"scp"`.
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
  | `STORED_MAPS_PRODUCT_MISSING` | A product's primary file is missing. |
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
