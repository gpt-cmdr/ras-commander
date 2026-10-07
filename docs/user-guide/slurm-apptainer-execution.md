# Native HEC-RAS on Slurm with Apptainer

`RasApptainer` runs a HEC-RAS 6.6 **native-Linux unsteady** plan on any Slurm cluster that has
Apptainer, starting from the artifacts that Windows preprocessing already produced
(`<project>.p##.tmp.hdf`, `<project>.b##`, `<project>.x##`; see `RasPreprocess`). It is
cluster-agnostic: everything site-specific lives in a JSON site profile.

!!! note "What a receipt means"
    The receipt is computational and transfer evidence (exit codes, hashes, timings). It is not a
    statement that the results are acceptable engineering output. Review results as usual.

Choose this API for a prepared native unsteady plan. For portable execution
requests, use [RasSlurm](slurm-portable-execution.md); the
[backend comparison](execution-backends.md) explains the different input contracts.

## Concepts

| Piece | What it does |
| --- | --- |
| Site profile | JSON file: SSH target, shared staging root, node scratch, SIF path and SHA-256, Slurm account/partition/qos, cores, memory, time |
| Image | One immutable OCI image pulled **once** by an administrator into a shared SIF. Every job re-verifies the SIF SHA-256 before use |
| Job folder | Rendered locally: `inputs/` (tmp.hdf, .b, .x, `SHA256SUMS`), `engine.sh`, `job.sh`, `job.json` |
| Job run | Verifies image and inputs, copies to node-local scratch, runs the solver in Apptainer, hash-verifies the copy-back, writes `receipt.json` |
| Transport | Pluggable object with `run`, `put_tree`, `get_tree`. `SshApptainerTransport` uses OpenSSH/scp; tests use a fake |

Known fim-commander-only fields (`max_concurrent`, `memory_per_task`, `ras_executable`,
`transfer_mode`, `timeout_seconds`, `rsync_executable`, and launcher settings) are accepted as
logged compatibility no-ops; `memory_per_task` is used as `slurm_memory` only when that native
field is absent. A usable Apptainer profile still needs this API's SSH and native-image settings.
Unknown fields are rejected, mutable image tags are rejected, and the SIF SHA-256 is mandatory at
real submission time (the all-zero example placeholder is allowed only for local rendering/dry-run).

## Site profile

Start with a site-specific JSON profile. The
[example profile](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/site_profiles/clb-slurm.example.json)
shows the schema; replace its SSH target, storage paths, account, partition, and
node selection for your cluster. The credentials and SIF hashes are placeholders.
Key fields:

| Field | Meaning |
| --- | --- |
| `host`, `ssh_user`, `ssh_port`, `identity_file`, `known_hosts_file` | SSH target. Host keys are always checked (`StrictHostKeyChecking=yes`); pin the controller key in `known_hosts_file` |
| `scratch_root` | Shared filesystem root visible to login and compute nodes; job folders are staged below it |
| `node_scratch_root` | Node-local scratch (default `/scratch`); the job works in `<root>/$SLURM_JOB_ID/ras` |
| `image`, `apptainer_image_sha256`, `container_identity` | Shared SIF path, its SHA-256, and the immutable identity (`sif:sha256:<hex>` or `registry/repo@sha256:<hex>`) |
| `oci_source` | OCI reference used for the one-time pull; it may be tag- or digest-pinned (`docker://repo@sha256:...`) |
| `hecras_dir`, `ld_library_path` | Solver directory inside the image and its library path. The defaults are derived from the canonical image Dockerfile and registry metadata, not a live API qualification. |
| `stack_unlimited`, `omp_stacksize`, `kmp_stacksize` | When `stack_unlimited=true`, the job checks both host and container stack limits; it fails with `STACK_LIMIT_FAILED` if either cannot be raised. `OMP_STACKSIZE`/`KMP_STACKSIZE` default to `2G`; `OMP_NUM_THREADS`/`MKL_NUM_THREADS` follow `num_cores`. |
| `num_cores`, `slurm_memory`, `time_limit`, `account`, `partition`, `qos`, `nodelist` | Slurm resources (all but `num_cores` optional) |
| `geom_preprocess` | Enable only for an image that ships `RasGeomPreprocess`. When false (the default), inputs must already contain non-empty `/Geometry/GeomPreprocess`. |

## Canonical image and pulling it once

The default image is `rascommander/hec-ras-linux-unsteady_6.6:v1`
([Docker Hub](https://hub.docker.com/r/rascommander/hec-ras-linux-unsteady_6.6), linux/amd64).
The [container catalog](container-images.md) lists its registry digest and Docker qualification.
Its configured layout (`/opt/hecras-runtime/engine`, library directories beneath it, and no
`RasGeomPreprocess`) is derived from its Dockerfile and registry metadata. It has not yet been
qualified by a live run through this API. The proven CLB runs used `ras-hecras.sif`, which did ship
and run `RasGeomPreprocess`; they are useful operational evidence, not a qualification of this
default profile.

An administrator pulls it once, on a node, to shared storage, then records the digest:

```bash
apptainer pull /shared/images/rascommander-hec-ras-linux-unsteady_6.6-v1.sif     docker://rascommander/hec-ras-linux-unsteady_6.6:v1
sha256sum /shared/images/rascommander-hec-ras-linux-unsteady_6.6-v1.sif
```

`RasApptainer.pull_command(profile)` prints this command for a profile. Put the digest in
`apptainer_image_sha256` and `container_identity` (`sif:sha256:<digest>`). Jobs refuse to run on a
mismatch. Do not pull per job.

## Solver-ready inputs and the pre-submit check

`render_job` first runs `ras_commander.RasApptainer.check_solver_ready` on the local, completed tmp.hdf, read-only with HDF5 locking off.
It raises `InputCheckError` (exported from `ras_commander`) listing every problem, before anything is staged, when:

- gridded precipitation is present but `Event Conditions/Meteorology/Precipitation/2D Flow Areas/<area>/`
  lacks `Cell/Face Indexes/Info/Weights` (solver: "2D Flow Areas folder not found"), or
- any floating 2D property table contains NaN (including face minimum elevation, face area/elevation,
  cell volume/elevation, and cell surface area). `Cells Minimum Elevation` legitimately holds NaN
  and is ignored, or
- `geom_preprocess=false` and `/Geometry/GeomPreprocess` is absent or empty.

These 2D checks are applied only to 2D areas that exist, so completed 1D/storage-area-only plans
are supported.

Never run it on a file HEC-RAS is still writing. Pass `check_inputs=False` to skip.

### Gridded DSS dependencies

For a materialized precipitation group with `Mode=Gridded` and `Source=DSS`,
`render_job` treats `DSS Filename` and `DSS Pathname` as an input dependency.
The filename must be a non-empty relative path from the temporary HDF, resolve
to an existing regular `.dss` file within the source project's parent directory,
and fit a collision-resistant staged filename in the HDF attribute's fixed-width
capacity. Absolute paths, symlinks, missing pathnames, and paths that escape
that directory fail before staging.

The renderer copies the DSS into `inputs/` under a digest-derived filename and
rewrites **only the staged temporary HDF** to that relative filename. It reads
the attribute back and confirms that `Mode`, `Source`, `DSS Pathname`, and
`Ratio` did not change. The source HDF and DSS remain unchanged. Source and
staged DSS hashes, the source reference, staged name, and DSS pathname are
recorded in the request and input manifest. `check_solver_ready` runs again
after this staged-HDF change.

### Completed Windows preprocessing

`RasPreprocess` does not treat the presence of gridded rainfall mapping datasets
as proof that native preprocessing has finished. It waits for this launch's
exact `RasProcess.exe CompletePreProcess` writer to be observed and then exit,
followed by two seconds of unchanged file-stat state. It does not open the HDF
while the owned engine lifecycle is active. If that exact writer is never
observed, the bounded run reports a timeout instead of authorizing an early
stop. After owned processes have ended and the file is quiescent, it performs
the structural and full solver-ready checks. Missing geometry preprocessing,
precipitation mappings, or non-finite property-table values remain terminal
input failures; they are never repaired by the staging path.

## Usage

```python
from pathlib import Path
from ras_commander import RasApptainer, SshApptainerTransport

profile = RasApptainer.load_profile("my-site.json")

# 1. Render locally. No network. The source project is not modified.
job = RasApptainer.render_job(
    project_folder=r"C:\models\UPGU1", project_name="UPGU1", plan_number="01",
    profile=profile, job_directory=r"C:\jobs\upgu1_p01",
)

# 2. Dry run (default): returns the handle without contacting the cluster.
RasApptainer.submit(job, dry_run=True)

# 3. Real submission.
transport = SshApptainerTransport(profile)
job = RasApptainer.submit(job, transport=transport, profile=profile, dry_run=False)

# 4. Later (even from a new process): reload the handle, poll, collect.
job = RasApptainer.load_job(r"C:\jobs\upgu1_p01")
print(RasApptainer.status(job, transport, profile))
result = RasApptainer.collect(job, transport, profile)
print(result.success, result.problems)
```

### Status and collection

`status` uses `sacct` (falling back to `squeue`) and reports `UNKNOWN` with a reason when either
accounting command is unavailable. `cancel(job, transport, profile)` calls `scancel` only for that
job's recorded allocation.
`collect` requires a terminal allocation, downloads `out/<jobid>` into a new local directory,
validates the receipt schema, checks that the receipt is bound to this request and Slurm job, and
re-hashes every output. `success` is true only when the scheduler state is `COMPLETED`, the receipt
says `succeeded`, all hashes match, `/Results/Unsteady` is populated, and the final simulation time
matches the planned end time. Failed jobs are collected too so their logs and receipt are retained.

### Safety properties

- The request SHA-256 binds the project, plan, staged input manifest, input hashes, normalized
  `job.sh` hash, `engine.sh` hash, expected simulation end, and profile. Submission verifies staged
  local and remote inputs against that request rather than trusting a mutable manifest; collection
  verifies receipt image identity and input hashes against it.
- Every render uses a unique remote attempt directory. An interrupted pre-submission upload can be
  reconciled by cleaning only that exact attempt; ambiguous `sbatch` outcomes remain non-retryable.
- The submission intent is persisted before `sbatch`. If `sbatch` fails ambiguously the job stays
  in `SUBMITTING` and is never resubmitted automatically; reconcile on the cluster and render a new job.
- Only node-scratch copies are modified (`.b` files are staged with LF line endings; the source
  hashes and the staged hashes are both recorded in `job.json`). If `Write DSS File = T` is
  followed by a Windows-absolute DSS path, the staged `.b` copy rewrites that path to the relative
  `<project>.dss`; the original is untouched and the request and receipt record the rewrite.
- Copy-back goes to `out/<jobid>.partial`, is hash-verified, then renamed. Scratch is kept when the
  job fails and removed only after a verified success.
- The staged HDF core attributes (`1D Cores`, `2D Cores (per mesh)`) are rewritten to `num_cores`;
  the allocation and OpenMP/MKL thread counts use the same value.

## The engine command

The only code that knows how the solver is invoked is `ENGINE_SCRIPT_TEMPLATE` in
`ras_commander/RasApptainer.py`. It mirrors `RasCmdr.compute_plan_linux`: `io.*` aliases,
`LD_LIBRARY_PATH`, then `RasUnsteady <project>.p##.tmp.hdf x##`. The `x` suffix comes from the
plan's geometry (`Geom File=g##`), not from the plan number. The job checks the completion banner
and fatal markers before promoting the tmp HDF. Collection also requires the full
`RasCmdr._validate_linux_solve` fatal-marker/result check, populated `/Results/Unsteady`, and the
final `Time Date Stamp` matching the planned end time before reporting success. It collects
`engine.log` and the Slurm stdout file when available. If your image differs, adjust the profile (`hecras_dir`, `ld_library_path`,
`geom_preprocess`) or that one template. Scheduler stdout and the `logs/` directory are retained
on all job failure paths; `engine.log` exists only after node-scratch staging begins.

## Limits

- 2D/1D unsteady only from Windows pre-computed artifacts; no steady flow, no geometry-only runs.
- One plan per job. Chained jobs (for example passing DSS output from one model into the next) are not
  implemented; they need a qualified output/readback boundary, not just Slurm dependencies.
- No job arrays. A pre-submission staging interruption may retry its unique attempt; an ambiguous
  `sbatch` result must be reconciled before a new render.
- Offline tests cover rendering, validation, receipts and a mocked transport. Qualify the image and
  solver on your cluster before relying on results.


## End-to-end example

This example shows a public example project's path from preprocessing to Slurm
collection. It is a procedure, not a live qualification of the model, cluster,
or canonical image. Use HEC-RAS 6.6 throughout. Before relying on a campaign,
qualify the selected SIF and a representative prepared model on your cluster.

### 1. Install and check prerequisites

The control host needs Python, this API, and OpenSSH/scp. To use source APIs,
from a repository checkout in an activated isolated environment:

```bash
CI=1 uv pip install -e ".[compute]" h5py
```

On Windows, set `CI=1` using your shell's environment syntax before running
`uv pip install -e ".[compute]" h5py`. Use Docker Engine or Windows Docker
Desktop in Linux-container mode for the Wine preparation option below. The
cluster needs Slurm accounting commands, Apptainer, a shared writable staging
root, and writable node-local scratch. Verify SSH host keys before using the
transport and populate the profile's `known_hosts_file`.

Pull the 6.6 native image to a shared SIF once using the command above, or pull
its [immutable registry reference](container-images.md#immutable-registry-identities).
Record the resulting SIF hash. A registry digest and a SIF hash are different
identities; jobs verify the actual SIF bytes.

### 2. Make a fresh model copy and preprocess

The [public example library](../examples/example-projects.md) includes Muncie.
Extract a source copy, then make a separate working copy. Choose an unsteady
plan from its plan table:

```python
import shutil
from pathlib import Path
from uuid import uuid4
from ras_commander import RasExamples, RasDocker, RasApptainer, init_ras_project

workspace = Path("ras-slurm-example") / uuid4().hex[:12]
source = RasExamples.extract_project("Muncie", output_path=workspace / "source")
working = workspace / "working" / source.name
shutil.copytree(source, working)
model = init_ras_project(working, "6.6", load_results_summary=False)
print(model.plan_df[["plan_number", "flow_type"]])
plans = model.plan_df.loc[model.plan_df["flow_type"] == "Unsteady", "plan_number"]
if plans.empty:
    raise RuntimeError("Select an example with an unsteady plan")
plan_number = str(plans.iloc[0]).zfill(2)
project = Path(model.prj_file)

prepared = RasDocker.preprocess_plan(
    project, plan_number, version="6.6",
    image="rascommander/hec-ras-wine-precompute_6.6:v4",
    timeout=900, num_cores=2, replace_generated=True, pull="always",
)
if not prepared.success:
    raise RuntimeError(prepared.error or prepared.receipt)
print(prepared.receipt_path)
```

Inspect the selected model's dependency paths before preprocessing. Supply
`mounts={...}` for terrain/projection dependencies outside the project folder,
using the [working-copy layout guidance](container-execution.md#prepare-a-complete-working-copy).
The example above assumes required files are reachable inside the project mount.
Keep the source copy and any external dependencies unchanged. Preparation can
replace generated outputs in the working copy. Native Windows preparation with
`RasPreprocess` is another route; never stage an HDF while its writer is active.

### 3. Configure the site and render

Copy the example profile to `my-site.json` and replace all site settings:

- Use the verified SSH host/user/key and known-hosts file.
- Set shared `scratch_root`, node-local scratch, and the shared SIF path.
- Set `apptainer_image_sha256` to the real SIF hash and `container_identity`
  to `sif:sha256:<that-hash>`.
- Choose the site's account, partition, memory, wall time, and core count.
  Remove the example's `nodelist` unless that node exists at your site.
- Keep `geom_preprocess=false` for the published image, which does not contain
  `RasGeomPreprocess`. The completed temporary HDF must already contain it.

```python
profile = RasApptainer.load_profile("my-site.json")
job_directory = workspace / "jobs" / f"plan-{plan_number}"
job = RasApptainer.render_job(
    project_folder=project.parent, project_name=project.stem,
    plan_number=plan_number, profile=profile, job_directory=job_directory,
)
print(job.script_path)
print(job.remote_directory)
RasApptainer.submit(job, dry_run=True)
```

Expect `inputs/`, `engine.sh`, `job.sh`, and `job.json`. Rendering and dry-run
submission do not contact the cluster. Review the resource directives and input
manifest. An all-zero image hash is permitted only for this offline step.

### 4. Submit and inspect status

```python
from ras_commander import SshApptainerTransport

transport = SshApptainerTransport(profile)
job = RasApptainer.submit(job, transport=transport, profile=profile, dry_run=False)
print(job.slurm_job_id)
state = RasApptainer.status(job, transport, profile)
print(state.state, state.terminal, state.reason)
```

Real submission uploads this attempt and calls `sbatch`; it consumes the site's
allocation. Keep the recorded job ID and `job.json`. Query status later rather
than submitting again because the job is pending.

### 5. Reload, collect, and inspect results

```python
from ras_commander import HdfResultsPlan

job = RasApptainer.load_job(job_directory)
state = RasApptainer.status(job, transport, profile)
if state.terminal:
    result = RasApptainer.collect(job, transport, profile)
    print(result.directory, result.success, result.problems)
    if not result.success:
        raise RuntimeError(result.problems)
    final_hdf = result.directory / f"{job.project_name}.p{job.plan_number}.hdf"
    print(HdfResultsPlan.get_unsteady_summary(final_hdf))
else:
    print("Wait for a terminal scheduler state before collecting", state.reason)
```

A successful collection contains the final plan HDF, receipt, and available
engine/scheduler logs under `job_directory/collected/<jobid>`. The collection
checks the planned final time, populated unsteady results, receipt identity,
and every output hash. Inspect water-surface results and diagnostics through
[HDF modules](../api/hdf.md), then review hydraulic suitability separately.
Use a new `destination=` for another collection; an existing destination is
rejected. To stop the recorded job, call
`RasApptainer.cancel(job, transport, profile)`.

## Troubleshooting

| Symptom | Meaning and next action |
| --- | --- |
| `InputCheckError` before staging | Preparation is incomplete or structurally invalid. Finish preprocessing and inspect listed issues; do not disable checks to bypass missing solver inputs |
| SIF digest mismatch | The shared image differs from the recorded profile. Preserve the failed evidence and verify the intended image before changing the profile |
| Pending allocation | Inspect the site's resource/account/partition reason. Pending does not justify another submission |
| `UNKNOWN` status | Accounting may be delayed or unavailable. Inspect the returned reason and reconcile with the cluster before collecting or submitting again |
| `STACK_LIMIT_FAILED` | Host or container stack limit could not be raised. Check the site's limits and image environment |
| Missing geometry preprocessing | Keep `geom_preprocess=false` for the canonical image and provide a completed `/Geometry/GeomPreprocess` group |
| Submission remains `SUBMITTING` after a transport error | `sbatch` may have accepted it. Reconcile the recorded attempt on the cluster; do not retry blindly |
| Failed receipt, output hash, or final-time validation | Retain logs and receipt; inspect `result.problems`. A file's existence or scheduler `COMPLETED` alone does not establish a successful solve |
| Failed-job outputs cannot be downloaded | Inspect the exact remote attempt and retained `logs/`; failure before scratch staging may produce no `engine.log` or output receipt |

The [API reference](../api/remote.md#rasapptainer-source-reference) documents
profile, transport, job, and collection records.
