# Docker preprocessing and native Linux computation

Use [RasDocker.preprocess_plan()][docker-source] and
[RasDocker.compute_plan()][docker-source] from the same Python program on
Windows or Linux. The first call prepares the plan with Windows HEC-RAS under
Wine. The second runs the matching official HEC-RAS Linux unsteady solver.
Both containers use [ras-commander](https://rascommander.info/ras/) to drive
HEC-RAS; the containers supply its runtime and manage files, processes, and
receipts.

The host needs Python with this version of the library and a working Docker
CLI connected to a Linux container engine. On Windows, use Docker Desktop
with Linux containers. HEC-RAS, Wine, and Windows Python are included in the
preprocessing image; a separate host HEC-RAS installation or Wine profile
mount is unnecessary.

Install the pinned host API and notebook inspection dependencies in an
activated Python environment:

```bash
uv pip install "ras-commander[compute] @ git+https://github.com/gpt-cmdr/ras-commander.git@15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5" jupyterlab matplotlib xarray geopandas
```

The image contains its own installed library. This command installs the host
API used to launch the containers and inspect their outputs. This host
revision accepts HEC-RAS 6.5, 6.6, and 7.0.1. Image qualification and
publication status are listed below.

Native images install library source `604704d440c49a39d6f6e8bae262e2233d895dd0`; the host API uses `15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5`. Wine controllers use `dc60b219091e85bcb4564eca45313475c39ce58a`, with Windows library source `9e4217713e954236b0c16023e1815c6f2b7a5309`.

## Select matching images

**Qualification status:** All three matching versions passed the full 266-hour Linux sample and the one-hour Windows Docker Desktop notebook, using two CPUs per container. Linux results contained 267 output times; Windows results contained two, with 6,548 finite water-surface values at every time. Live progress, resume and sequential batch checks passed on both hosts; the six Linux Wine LF/CRLF cases also passed. The images are published on Docker Hub, and anonymous pulls verified all six matching payloads. See the [current release record][release].

| HEC-RAS | Wine preprocessing image | Native unsteady image |
|---|---|---|
| 6.5 | `rascommander/hec-ras-wine-precompute_6.5:v4` | `rascommander/hec-ras-linux-unsteady_6.5:v1` |
| 6.6 | `rascommander/hec-ras-wine-precompute_6.6:v4` | `rascommander/hec-ras-linux-unsteady_6.6:v1` |
| 7.0.1 | `rascommander/hec-ras-wine-precompute_7.0.1:v4` | `rascommander/hec-ras-linux-unsteady_7.0.1:v1` |

Pull both matching images before the first run to refresh the local tags:

```bash
docker pull rascommander/hec-ras-wine-precompute_6.5:v4
docker pull rascommander/hec-ras-linux-unsteady_6.5:v1
```

For 6.6 or 7.0.1, change the version in both repository names. Wine `v4` and native `v1` also have matching `latest` tags. The API examples use `pull="always"` to refresh the selected image.

Use matching HEC-RAS versions. A missing image fails explicitly; the API does not choose another version. The native worker requires populated 2D meshes and validates their complete water-surface output.

## Prepare a complete working copy

Start with a fresh, complete model copy containing its original populated
geometry HDF. Keep the source project separate. A previous failed run that
lost its 2D geometry is not a valid preprocessing baseline.

For the ras2fim sample, keep the following relative layout:

```text
02_model_copies/
  <model-name>/
    <model-name>.prj
    <model-name>.p01
    <model-name>.g01
    <model-name>.g01.hdf
    <model-name>.u01
    <model-name>.u01.hdf
    <model-name>.rasmap
    ... other original model files ...
  source_terrain/
    Terrain.hdf
    ... every terrain TIFF or other referenced raster ...
  projection/
    EPSG_2277.prj
```

The selected plan determines the geometry and unsteady-flow numbers; they
need not all be `01`. The terrain HDF alone is insufficient when it references
separate raster files. For another project, supply the dependencies declared
by that project's plan, map, and terrain files.

The project directory is mounted read/write at `/job`. In the sample,
references to `..\\source_terrain` and `..\\projection` resolve through additional
read-only mounts at `/source_terrain` and `/projection`. Mounting just the
project folder does not expose its sibling directories. All host paths must
be accessible to the Docker engine, not only to the Python process.

## Call both phases

This code uses a working copy prepared beforehand. The
[example notebook][notebook] includes a fresh-copy setup and result checks.

```python
from pathlib import Path
from ras_commander import RasDocker

models = Path("/path/to/working/02_model_copies")
# On Windows, for example: Path(r"C:\Users\you\ras-runs\02_model_copies")
name = "your-model-name"
project = models / name / f"{name}.prj"
version = "6.5"
preprocess_image = f"rascommander/hec-ras-wine-precompute_{version}:v4"
compute_image = f"rascommander/hec-ras-linux-unsteady_{version}:v1"

prepared = RasDocker.preprocess_plan(
    project,
    "01",
    version=version,
    image=preprocess_image,
    mounts={
        "/source_terrain": models / "source_terrain",
        "/projection": models / "projection",
    },
    timeout=900,
    num_cores=2,
    replace_generated=True,
    pull="always",
)
print(prepared.receipt_path)
if not prepared.success:
    raise RuntimeError(prepared.error or prepared.receipt)

computed = RasDocker.compute_plan(
    project,
    "01",
    version=version,
    image=compute_image,
    prepare_receipt=prepared.receipt_path,
    timeout=14400,
    num_cores=2,
    pull="always",
)
print(computed.receipt_path)
if not computed.success:
    raise RuntimeError(computed.error or computed.receipt)
```

`replace_generated=True` authorizes preprocessing to replace generated model
files, including existing plan outputs. Use it on the working copy. Stop on
a failed preprocessing result; do not pass an incomplete preparation to
the solver. Each call returns a result with `success`, `receipt_path`,
`receipt`, `stdout`, `stderr`, `returncode`, and `error` for programmatic inspection.
The `error` field explains host-side failures, such as a failed image pull;
`receipt` contains the container diagnostics when a receipt was produced.

## CPU limits, progress, resume, and batch summaries

The pinned host API and native source above provide these features. The
container runs one selected plan at a time; scheduling multiple models stays
on the host.

### Match solver cores to container resources

`num_cores` defaults to **2** and accepts integers from **1 through 8**.
[RasDocker][docker-source] passes it as Docker's `--cpus` for both stages and
as `--num-cores` for each stage. The native worker passes the count
to [RasCmdr.compute_plan_linux()][cmdr-source], which sets the plan/HDF core
settings and `OMP_NUM_THREADS`/`MKL_NUM_THREADS`.

Docker's CPU limit controls aggregate CPU time. It does not reserve exclusive
physical cores or pin the process; CPU affinity is a separate setting.
Resource limits belong in the launch command, while the Dockerfile defines
the installed environment. See [Docker CPU constraints](https://docs.docker.com/engine/containers/resource_constraints/#cpu).
The Wine worker calls [RasPlan.set_num_cores()][wine-plan-source] and
[RasPlan.set_2d_flow_options()][wine-plan-source] before preprocessing. The second
call uses `include_default=True` and inserts missing default or named-mesh
processor settings. It reads the setting back with [RasPlan.get_plan_value()][wine-plan-source], so the selected
plan's processor count matches the container quota.
Both receipts record the effective count in `arguments.num_cores`. Resume
requires that recorded count to match the new request.

Each container runs one selected plan. Running several model containers is
the host or scheduler's responsibility. For example, four simultaneous jobs
at two cores each need eight CPU equivalents plus sufficient memory and
scratch storage for all four models.

### Receive live output and lifecycle callbacks

Use the same partial `ExecutionCallback` pattern as
[RasCmdr][cmdr-source], or implement `on_container_event` to distinguish
projects, plans, stages and output streams:

```python
class Progress:
    def on_container_event(self, event):
        label = f"{event.project_path.stem} / {event.plan_number} / {event.stage}"
        print(f"[{label}] {event.kind}: {event.message}", flush=True)

computed = RasDocker.compute_plan(
    project, "01", version=version, num_cores=2,
    image=compute_image, pull="always",
    prepare_receipt=prepared.receipt_path, replace_generated=True,
    stream_callback=Progress(), resume=True,
)
```

Events are `start`, `message`, `complete`, or `resumed`. Messages preserve
their `stdout`/`stderr` source and arrive as the container emits them.
`complete.success` includes the container receipt check. A resumed stage
emits `resumed` and does not pretend that a new process ran.

The compatible methods are `on_prep_start`, `on_prep_complete`,
`on_exec_start`, `on_exec_message`, `on_exec_complete`, and `on_verify_result`.
Preparation completion is emitted only on success; native completion includes
the success flag. For this API, verification means the container's validation
receipt passed. An ordinary callback exception is logged without failing the
model; `KeyboardInterrupt` propagates after owned-container cleanup. Keep
callbacks quick, and use project-aware events when different models share a
plan number.

The native worker forwards its solver log while computation is running,
handling CRLF, LF and lone-CR progress records. Live callbacks matched the
complete ordered solver log in all three Linux qualification runs. Timing
depends on when HEC-RAS flushes its output; the API does not fabricate
percentages during silent periods.

### Resume completed stages

Enable `resume=True` on the first and subsequent calls. After a successful
stage, the host saves a resume record under `.ras-commander/resume/`. A later
call reuses it only if the model inputs, read-only dependency contents,
version, image reference, core count, receipt, and output artifacts match.
Model/dependency contents are read to check this, which can be expensive for
large terrain datasets. The default `resume=False` does not build that extra
inventory. Use an immutable image reference when reproducibility must include
the exact image contents; resume compares the requested image reference and
does not contact the registry to resolve a mutable tag.

This resumes the workflow at completed-stage boundaries; it is not a HEC-RAS
restart from a partially computed simulation. A failed or changed stage runs
normally, and `replace_generated` still controls whether existing outputs
can be replaced. Existing receipts created before resume was enabled are
insufficient by themselves. A cache hit returns `resumed=True`, the original
receipt, and `returncode=None` because no Docker process ran. It also skips
pulling an image, regardless of the requested pull policy.

### Collect a batch summary

[RasDocker.run_batch()][docker-source] processes working copies sequentially
on the host, records each outcome, and continues after ordinary job failures:

```python
jobs = [
    {"project_path": models / "model-a" / "model-a.prj", "plan_number": "01"},
    {"project_path": models / "model-b" / "model-b.prj", "plan_number": "01"},
]
batch = RasDocker.run_batch(
    jobs, stage="run", version=version, num_cores=2,
    preprocess_image=preprocess_image, compute_image=compute_image, pull="always",
    mounts={"/source_terrain": models / "source_terrain",
            "/projection": models / "projection"},
    resume=True, stream_callback=Progress(),
)
display(batch.summary_df)
batch.summary_df.to_csv(models / "batch-summary.csv", index=False)
```

Use `stage="prepare"` or `stage="compute"` for a single phase. Each job can
override shared options. `batch.results` retains the per-job preparation and
computation results; `summary_df` includes status, reuse, elapsed time,
receipt paths and errors, including invalid jobs. A failed preparation skips
that job's computation. An interrupt stops the batch and cleans up the active
container. Resume records remain available for a later invocation.

For TACC, use an external scheduler to distribute independent runs. The
[implementation comparison and TACC design notes](container-hpc-design.md)
describe the proposed Apptainer/Slurm integration and the staging changes
needed in ras2fim. That backend has not yet been implemented or qualified.

## What runs inside each container

```mermaid
flowchart TD
    P["Host Python: RasDocker.preprocess_plan()"] --> W["Wine container: init_ras_project()"]
    W --> G["RasPlan.get_plan_path()"]
    G --> CPU["RasPlan.set_num_cores()"]
    CPU --> CPU2D["RasPlan.set_2d_flow_options(cores=N, include_default=True)"]
    CPU2D --> CHECK["RasPlan.get_plan_value(): verify requested cores"]
    CHECK --> C["GeomPreprocessor.clear_geompre_files()"]
    C --> F["RasPlan.update_run_flags()"]
    F --> PRE["RasPreprocess.preprocess_plan()"]
    PRE --> H["Windows HEC-RAS under Wine"]
    H --> T["Validated .p01.tmp.hdf, .b01 and geometry inputs on host"]
    T --> D["Host Python: RasDocker.compute_plan()"]
    D --> S["Native container: private Linux project copy"]
    S --> INIT["init_ras_project()"]
    INIT --> PLAN["RasPlan.get_plan_value(): geometry and time window"]
    PLAN --> N["RasCmdr.compute_plan_linux(retry=False, num_cores=N)"]
    N --> R["Official Linux RasUnsteady"]
    R --> E["RasCmdr.inspect_execution_evidence(): supplementary observations"]
    E --> V["Validate results and completed simulation time"]
    V --> O["Publish .p01.hdf and compute receipt to host"]
    O --> Q["HdfResultsMesh.get_mesh_timeseries()"]
```

Inspect the actual API implementations:
[RasDocker][docker-source], [Wine init_ras_project()][wine-project-source],
[Wine RasPlan.get_plan_path() and RasPlan.update_run_flags()][wine-plan-source],
[RasPlan.set_num_cores(), RasPlan.set_2d_flow_options() and RasPlan.get_plan_value()][wine-plan-source],
[GeomPreprocessor.clear_geompre_files()][geom-source],
[RasPreprocess.preprocess_plan()][preprocess-source],
[native init_ras_project()][native-project-source],
[native RasPlan.get_plan_value()][native-plan-source],
[RasCmdr.compute_plan_linux() and RasCmdr.inspect_execution_evidence()][cmdr-source], and
[HdfResultsMesh.get_mesh_timeseries()][mesh-results-source]. The
[preprocessing worker][wine-worker] and [native container worker][native-worker]
show how these calls are connected.

### Wine and Windows preprocessing

Wine implements the Windows interfaces needed by the installed HEC-RAS
application within Linux. The image contains a prepared Windows directory and
registry tree, called a Wine prefix, under `/runtime/wine-seed/prefix`.
Its `drive_c` directory contains Windows Python and the installed HEC-RAS
application. `/runtime/wine-seed/runtime.json` identifies the matching HEC-RAS
version and its installed paths. For version `V`, the executable is
`C:\Program Files (x86)\HEC\HEC-RAS\V\Ras.exe`, backed by
`/runtime/wine-seed/prefix/drive_c/Program Files (x86)/HEC/HEC-RAS/V/Ras.exe`.
Windows Python is `C:\Python311\python.exe`.

Each run copies the profile into `/run/ras-job/<run-id>/wineprefix`, its
private writable scratch space. Windows
Python runs the [preprocessing worker][wine-worker], which calls the linked
[ras-commander](https://rascommander.info/ras/) APIs. HEC-RAS reads and writes the
host working model through `/job`; Wine provides Windows access to those
mounted Linux paths. The profile template remains reusable between runs.

In the standard API launch, `/run/ras-job` and `/tmp` use the container's
writable layer. Docker removes that layer with `--rm`; the host bind mounts
remain. The root-owned seed is protected from UID 1000, while root could write
it; the controller directs ordinary job changes to its copied prefix. The
[ras2fim launcher](https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/src/stage_hecras_for_linux_wine_02b.py)
separately configures a read-only root, temporary-memory mount and scratch volume.

Preflight checks the project and its dependencies before changing model files.
Selected model text is normalized to Windows CRLF line endings, including
when it was created on Linux. The worker forces geometry preprocessing and
checks the generated geometry and temporary plan HDFs for retained 2D areas,
cell counts, and populated hydraulic property tables before reporting success.

### Native Linux unsteady computation

The second image contains the official Linux solver and its shared libraries
at `/opt/hecras-runtime/engine/RasUnsteady` and
`/opt/hecras-runtime/engine/libs/`, with settings in
`/opt/hecras-runtime/runtime.json`. It does not use Wine. The
[container worker][native-worker] stages a private project copy on Linux
storage and calls [RasCmdr.compute_plan_linux()][cmdr-source]. That API handles
the Linux solver's runtime library environment and `io.*` file aliases.

Private Linux storage allows those aliases and solver scratch writes to work
consistently even when `/job` comes from a Windows drive. Scratch text uses Linux LF line endings; binary HDFs are not text-normalized.
The host `.p01.tmp.hdf`, `.b01` and `.x01` preparation artifacts are preserved. After a successful calculation and result checks,
the worker publishes the final `.p01.hdf` back through the host mount. A
failed calculation is recorded in its receipt; an unvalidated result is not
promoted to the final host result path.

The worker checks that the compiled inputs still belong to the successful
preparation. If the plan or prepared files change, run preprocessing again.

## Inspect preparation and results separately

A prepared `.p01.tmp.hdf` contains geometry and boundary data for the next
phase. It is not expected to contain `/Results`. File size alone cannot prove
that preparation succeeded. Inspect the preparation receipt and use
[HdfBase.get_2d_flow_area_names_and_counts()][base-source],
[HdfMesh.get_mesh_cell_property_tables() and
HdfMesh.get_mesh_face_property_tables()][mesh-source] to inspect its content.

The final `.p01.hdf` should contain time-dependent unsteady results. Use
[HdfResultsPlan.get_unsteady_summary()][plan-results-source] for reported
completion information and [HdfResultsMesh.get_mesh_timeseries()][mesh-results-source]
for finite water-surface values and timestamps. Check every value for
finiteness and require the observed time extent to match exactly with
[HdfPlan.get_plan_start_time() and HdfPlan.get_plan_end_time()][hdf-plan-source].
Collection metadata can report a different cell count from the number of
stored coordinate rows. The sample reports 6,201 cells but stores 6,548
coordinate rows and water-surface columns. The notebook uses
[HdfMesh.get_mesh_sloped_topology()][mesh-source] to compare the result-array
width with the actual prepared coordinate count, while also checking that
collection metadata stays unchanged.

The notebook demonstrates these checks with the real sample; it does not use
the presence of `/Results` or a zero process exit code as the sole success test.

The updated native worker also retains
[RasCmdr.inspect_execution_evidence()][cmdr-source] observations in the compute
receipt's `execution_evidence` field. Those observations remain separate from
the native acceptance checks: the HDF completion attribute can already be true
in a prepared `.tmp.hdf`, and native results can omit the Windows
`Complete Process` message. A generic completion flag alone therefore cannot
prove the native stage finished. An unreadable diagnostic channel is recorded
as `inspection_error`; the solver log, full output window, dimensions, and
finite-value checks still determine whether the result can be published.

Receipts are retained below `.ras-commander/runs/<run-id>/` in the working
project. Keep them with the resulting model when reporting a problem. The
notebook demonstrates execution mechanics; model suitability and interpretation
of hydraulic results remain engineering decisions.

The current [Wine runtime inventory](https://github.com/gpt-cmdr/ras2fim-2d/blob/codex/phase2-linux-wine-preprocessing/containers/hecras-prepare/runtime-inventory-current.json) and [native runtime inventory](https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/containers/hecras-unsteady/runtime-inventory-current.json) list installed packages, source identities and runtime paths for all three versions.

For instructions to build from the source
checkout and an external vendor runtime, see
[How to re-create the native container][container-readme]. The existing
[Wine container operating guide][wine-guide] documents its corresponding
installed runtime and build inputs. For 7.0.1, the
[runtime reconstruction guide][runtime-701] and
[extract_installer.py][extractor-701] document extraction of the official
combined installer into the native build inputs.

[docker-source]: https://github.com/gpt-cmdr/ras-commander/blob/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5/ras_commander/RasDocker.py
[native-worker]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/ras_commander/_container_compute.py
[project-source]: https://github.com/gpt-cmdr/ras-commander/blob/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5/ras_commander/RasPrj.py
[plan-source]: https://github.com/gpt-cmdr/ras-commander/blob/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5/ras_commander/RasPlan.py
[geom-source]: https://github.com/gpt-cmdr/ras-commander/blob/9e4217713e954236b0c16023e1815c6f2b7a5309/ras_commander/geom/GeomPreprocessor.py
[preprocess-source]: https://github.com/gpt-cmdr/ras-commander/blob/9e4217713e954236b0c16023e1815c6f2b7a5309/ras_commander/RasPreprocess.py
[cmdr-source]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/ras_commander/RasCmdr.py
[base-source]: https://github.com/gpt-cmdr/ras-commander/blob/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5/ras_commander/hdf/HdfBase.py
[mesh-source]: https://github.com/gpt-cmdr/ras-commander/blob/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5/ras_commander/hdf/HdfMesh.py
[mesh-results-source]: https://github.com/gpt-cmdr/ras-commander/blob/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5/ras_commander/hdf/HdfResultsMesh.py
[plan-results-source]: https://github.com/gpt-cmdr/ras-commander/blob/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5/ras_commander/hdf/HdfResultsPlan.py
[hdf-plan-source]: https://github.com/gpt-cmdr/ras-commander/blob/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5/ras_commander/hdf/HdfPlan.py
[container-readme]: https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/containers/hecras-unsteady/README.md
[notebook]: https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/examples/512_docker_precompute_and_linux_compute.ipynb
[wine-worker]: https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/windows_worker.py
[wine-guide]: https://github.com/gpt-cmdr/ras2fim-2d/blob/codex/phase2-linux-wine-preprocessing/containers/hecras-prepare/OPERATION.md

[release]: https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/containers/hecras-unsteady/RELEASE-CURRENT.md


[runtime-701]: https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/containers/hecras-unsteady/RUNTIME-7.0.1.md
[extractor-701]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/extract_installer.py

[wine-project-source]: https://github.com/gpt-cmdr/ras-commander/blob/9e4217713e954236b0c16023e1815c6f2b7a5309/ras_commander/RasPrj.py
[wine-plan-source]: https://github.com/gpt-cmdr/ras-commander/blob/9e4217713e954236b0c16023e1815c6f2b7a5309/ras_commander/RasPlan.py
[native-project-source]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/ras_commander/RasPrj.py
[native-plan-source]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/ras_commander/RasPlan.py
