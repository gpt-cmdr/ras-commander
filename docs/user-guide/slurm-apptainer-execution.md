# Native HEC-RAS on Slurm with Apptainer

`RasApptainer` runs a HEC-RAS 5.0.7, 6.1, 6.5, 6.6 or 7.x **native-Linux unsteady** plan on any Slurm cluster
that has Apptainer, starting from the artifacts that Windows preprocessing produced
(`<project>.p##.tmp.hdf`, `<project>.b##`, `<project>.x##`, plus `<project>.c##` for releases
before 6.3.1 such as 5.0.7 and 6.1; see
`RasPreprocess`). Those artifacts
can come from a Windows workstation or from a
[Wine prepare job on the same cluster](#wine-preparation-on-the-cluster), which mirrors
`RasDocker.preprocess_plan` followed by `RasDocker.compute_plan`. It is cluster-agnostic:
everything site-specific lives in a JSON site profile.

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
| Job folder | Rendered locally: `inputs/` (tmp.hdf, .b, .x, the .c for pre-6.3.1 releases, `SHA256SUMS`), `engine.sh`, `job.sh`, `job.json` |
| Prepare job (optional) | Rendered locally from a complete project: `inputs/` (the project tree), `job.sh`, `job.json`. Runs Windows preprocessing under Wine in a separate executor SIF and returns the solver inputs |
| Job run | Verifies image and inputs, copies to node-local scratch, runs the solver in Apptainer, hash-verifies the copy-back, writes `receipt.json` |
| Transport | Pluggable object with `run`, `put_tree`, `get_tree`. `SshApptainerTransport` uses OpenSSH/scp; tests use a fake |

Unknown fields are rejected (including other tools' fields such as `memory_per_task` or
`max_concurrent`; use `slurm_memory`), mutable image tags are rejected, and the SIF SHA-256 is mandatory at real
submission time (the all-zero example placeholder is allowed only for local rendering/dry-run).

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
| `hecras_dir`, `ld_library_path` | Solver directory inside the image and its library path. The defaults are derived from the canonical image Dockerfile and registry metadata, not a live API qualification. For the `bin_ras` layout an omitted `hecras_dir` defaults to `/opt/hecras-runtime/engine/bin_ras` (where the native 5.0.7 image puts HEC's `bin_ras` folder) and an omitted `ld_library_path` to `hecras_dir` alone (HEC colocates the 5.0.7 libraries with the binary). |
| `native_layout` | Optional library layout: `canonical` (6.1+/7.x `RasUnsteady` with a `libs/` tree) or `bin_ras` (5.0.7 `rasUnsteady64` with colocated libraries). Omit it to derive the layout from `ras_version`; a layout that does not match the release is rejected. |
| `solver_arguments` | Optional solver argument convention, independent of the layout: `cfile` (`<engine> <project>.c## b##`) or `tmphdf` (`RasUnsteady <project>.p##.tmp.hdf x##`). Omit it to derive it from `ras_version`: releases before 6.3.1 (5.0.7, 6.1; 6.2 and 6.3 are treated the same) use `cfile`, 6.3.1 and later `tmphdf`. `bin_ras` accepts only `cfile`. An explicit value is recorded in the request. See [Solver argument conventions](#solver-argument-conventions-by-release). |
| `stack_unlimited`, `omp_stacksize`, `kmp_stacksize` | When `stack_unlimited=true`, the job checks both host and container stack limits; it fails with `STACK_LIMIT_FAILED` if either cannot be raised. `OMP_STACKSIZE`/`KMP_STACKSIZE` default to `2G`; `OMP_NUM_THREADS`/`MKL_NUM_THREADS` follow `num_cores`. |
| `num_cores`, `slurm_memory`, `time_limit`, `account`, `partition`, `qos`, `nodelist` | Slurm resources (all but `num_cores` optional) |
| `geom_preprocess` | Enable only for an image that ships `RasGeomPreprocess`. When false (the default), 6.x/7.x inputs must already contain non-empty `/Geometry/GeomPreprocess`. Rejected for `bin_ras`: the 5.0.7 Linux distribution has no `RasGeomPreprocess`. Also rejected for `cfile` releases (for example 6.1), which consume the Windows-computed `.c##` geometry. |
| `ras_version` | HEC-RAS release of the native engine: `5.0.7`, `6.1`, `6.5`, `6.6`, or `7.x` (for example `7.0.1`). HEC published no Linux engine for 5.0–5.0.6, 6.0, or 6.2–6.4.1; those are rejected (run them entirely under Wine with `RasSlurm`). 4.x is not supported in containers. It also selects the default Windows `Ras.exe` for prepare jobs |
| `prepare_image`, `prepare_image_sha256` | Optional shared [Wine executor SIF](apptainer-images.md#wine-executor-image) and its SHA-256, required only by `render_prepare_job`. Set both or neither |
| `prepare_ras_executable`, `prepare_python_executable`, `prepare_timeout_seconds` | Windows `Ras.exe` inside the executor (default `C:\Program Files (x86)\HEC\HEC-RAS\<ras_version>\Ras.exe`), the image's Linux Python (default `python`), and the preprocessing timeout (default 3600 s) |

## Canonical image and pulling it once

The default image is `rascommander/hec-ras-linux-unsteady_6.6:v1`
([Docker Hub](https://hub.docker.com/r/rascommander/hec-ras-linux-unsteady_6.6), linux/amd64).
The [container catalog](container-images.md) lists its registry digest and Docker qualification.
Its configured layout (`/opt/hecras-runtime/engine`, library directories beneath it, and no
`RasGeomPreprocess`) is derived from its Dockerfile and registry metadata. The same layout is used
for 6.5 and 7.0.1 (`rascommander/hec-ras-linux-unsteady_<version>:v1`); set `ras_version` and
`oci_source` together.

!!! info "Production evidence"
    CLB has run `RasApptainer.render_job`, `submit`, and `collect` live on its Slurm cluster
    with a site-built HEC-RAS 6.6 native SIF (`ras-hecras.sif`, which ships `RasGeomPreprocess`).
    Those jobs collected successfully with verified copy-back, populated unsteady results, and the
    planned final simulation time. On October 13–14, 2026 a Wine prepare job followed by a native
    solve ran end to end through this API for HEC-RAS 5.0.7, 6.1, 6.5, 6.6, 7.0, and 7.0.1 on the
    Muncie 2D plan; see the
    [qualification table](apptainer-images.md#qualification-status). Water surfaces matched the
    Windows engine under Wine to within 0.012 ft at any time step (maximum-WSE map within
    0.0005 ft). Qualify the image you pull with one representative plan before a campaign.

An administrator pulls it once, on a node, to shared storage, then records the digest:

```bash
apptainer pull /shared/images/rascommander-hec-ras-linux-unsteady_6.6-v1.sif     docker://rascommander/hec-ras-linux-unsteady_6.6:v1
sha256sum /shared/images/rascommander-hec-ras-linux-unsteady_6.6-v1.sif
```

`RasApptainer.pull_command(profile)` prints this command for a profile. To reuse a local or cached SIF (or fill a shared cache once), use
`RasContainerImages.resolve_sif()` or `ensure_sif_command()`; see
[Use a local or cached image](apptainer-images.md#use-a-local-or-cached-image).
 Put the digest in
`apptainer_image_sha256` and `container_identity` (`sif:sha256:<digest>`). Jobs refuse to run on a
mismatch. Do not pull per job.

## HEC-RAS 5.0.7 (`bin_ras` layout)

HEC's 5.0.7 Linux distribution (`HEC-RAS_507_linux.zip`) ships `bin_ras/rasUnsteady64` with its
libraries alongside it, not the 6.x `RasUnsteady` plus `libs/` tree. With `ras_version: "5.0.7"`
the profile derives `native_layout: "bin_ras"`, and `RasApptainer` mirrors
`RasCmdr.compute_plan_linux` for that layout:

- Windows 5.0.7 preprocessing must also have produced the computed-geometry file
  `<project>.c<geom>` (the geometry number comes from the plan's `Geom File=g##`). `render_job`
  requires it to be present and non-empty and stages it byte-for-byte; it is binary and is never
  line-ending converted (the `.b`/`.x` text files still are).
- The engine runs `"$HECRAS/rasUnsteady64" <project>.c<geom> b<plan>` with cwd `/job`
  (cwd-relative basenames, as in HEC's own run script) and
  `LD_LIBRARY_PATH` set to `hecras_dir` by default. It fails with exit code 6 and a clear message
  if `$HECRAS/rasUnsteady64` is not executable. The solver writes results into the tmp HDF, which
  is promoted to `<project>.p##.hdf` after the completion banner and fatal-marker checks, as for 6.x.
- The compiled-HDF core attributes are not rewritten (5.0.7 stores `1D Cores`/`2D Cores` scalars
  that `compute_plan_linux` also leaves alone); `OMP_NUM_THREADS`/`MKL_NUM_THREADS` follow
  `num_cores`.
- `render_job` refuses a 5.x tmp HDF with a 6.x/7.x profile, and a 6.x/7.x tmp HDF with a
  `bin_ras` profile, based on the root `File Version` attribute.
- The rendered request records `native_layout: "bin_ras"` and `ctoken`; canonical requests are
  unchanged.

The image must provide `rasUnsteady64` and its libraries in `hecras_dir`
(default `/opt/hecras-runtime/engine`), including a `libgfortran.so.3` link to HEC's
`libgfortran.so` (the binary needs that soname); the
[native image recipe](https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-unsteady/README.md)
builds it from `HEC-RAS_507_linux.zip`. No published 5.0.7 native image exists yet: set `image`,
`apptainer_image_sha256`, `container_identity` and `oci_source` for the SIF you build. Collection
validation is the same as for 6.x, since the 5.0.7 result HDF has the same
`Results/Unsteady/.../Time Date Stamp` structure. On October 14, 2026 a 5.0.7 prepare job (Wine)
and native
solve of Muncie plan 03 ran on the CLB cluster: 74 s on 2 cores, water surfaces within 0.012 ft of
the Windows engine under Wine.

## Solver argument conventions by release

The library layout and the solver's argument convention are independent. Verified against HEC's
official Linux distributions:

| Release | Library layout | Solver arguments (cwd = project) | Needs `.c##` |
| --- | --- | --- | --- |
| 5.0.7 (`HEC-RAS_507_linux.zip`) | `bin_ras` | `rasUnsteady64 <project>.c<geom> b<plan>` (`cfile`) | yes |
| 6.1 (`HEC-RAS_610_Linux.zip`) | canonical (`RasUnsteady` + `libs/`, `libs/mkl`, `libs/rhel_8`) | `RasUnsteady <project>.c<geom> b<plan>` (`cfile`) | yes |
| 6.5, 6.6, 7.x | canonical | `RasUnsteady <project>.p<plan>.tmp.hdf x<geom>` (`tmphdf`) | no |

HEC's 6.1 solver exits with code 29 when given the 6.3.1+ `tmp.hdf x##` arguments. HEC published
no Linux engine for 6.0 or 6.2–6.4.1. For a `cfile` profile with the
canonical layout (`ras_version: "6.1"`), `render_job` stages the non-empty `.c##` file byte-for-byte,
leaves the compiled-HDF core attributes untouched (`OMP_NUM_THREADS`/`MKL_NUM_THREADS` still follow
`num_cores`), runs `"$HECRAS/RasUnsteady" "$PROJECT.$CTOKEN" "b$PLAN"`, and records
`native_layout: "canonical"`, `solver_arguments: "cfile"` and `ctoken` in the request. `render_job`
also refuses a tmp HDF whose root `File Version` release uses a different convention than the
profile (for example a 6.1 file with a 6.6 profile). Requests, engine scripts and job scripts for
6.3.1+ profiles are byte-identical to earlier versions. The 6.1 path ran live on October 14, 2026
(Muncie plan 03, 40 s on 2 cores, water surfaces within 0.0085 ft of the Windows engine under Wine).

`RasCmdr.compute_plan_linux` (and the RasDocker native worker that calls it) chooses the same
convention from the tmp HDF `File Version`, falling back to the install layout (`bin_ras` →
`cfile`, otherwise `tmphdf`) when the attribute is absent. It finds HEC's 6.1 `libs/` tree two
levels above `Ras_v61/Release`, and when `libs/rhel_8` exists it omits `libs/centos_7`, as HEC's
`run_unsteady.sh` does.

## Solver-ready inputs and the pre-submit check

`render_job` first runs `ras_commander.RasApptainer.check_solver_ready` on the local, completed tmp.hdf, read-only with HDF5 locking off.
It raises `InputCheckError` (exported from `ras_commander`) listing every problem, before anything is staged, when:

- `Event Conditions` does not report `Completed Successfully=True` (including a missing attribute),
- point or gridded precipitation lacks a non-empty two-dimensional
  `Event Conditions/Meteorology/Precipitation/Values` dataset,
- gridded precipitation is present but `Event Conditions/Meteorology/Precipitation/2D Flow Areas/<area>/`
  lacks `Cell/Face Indexes/Info/Weights` (solver: "2D Flow Areas folder not found"), or
- any floating 2D property table contains NaN (including face minimum elevation, face area/elevation,
  cell volume/elevation, and cell surface area). `Cells Minimum Elevation` legitimately holds NaN
  and is ignored, or
- `geom_preprocess=false` and `/Geometry/GeomPreprocess` is absent or empty.

These 2D checks are applied only to 2D areas that exist, so completed 1D/storage-area-only plans
are supported. For a tmp HDF from a release before 6.3.1 (root `File Version` `HEC-RAS 5.*` or
`HEC-RAS 6.1`–`6.3`) the `/Geometry/GeomPreprocess` and 2D property-table NaN checks are skipped,
because those releases read their computed geometry, including the 2D property tables, from the
`.c##` file; `render_job` requires that non-empty `.c##` file instead. `Completed Successfully` is
skipped only for 5.x, which never writes it; it stays required for 6.1. The 6.1 relaxation follows
from the `cfile` invocation and has not yet been checked against a live 6.1 Windows output.

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

## Wine preparation on the cluster

Instead of preprocessing on a Windows workstation, run Windows HEC-RAS preprocessing under Wine on
the cluster. Add the Wine executor SIF to the profile:

```json
"prepare_image": "/shared/images/hec-ras-wine-executor_6.6.sif",
"prepare_image_sha256": "<sha256sum of that SIF>"
```

For HEC-RAS 6.0 and earlier (here, 5.0.7), add
`"environment": {"APPTAINERENV_RAS_COMMANDER_WINE_ACCEPT_TCU": "1"}` (see
[HEC-RAS 6.0 and earlier](apptainer-images.md#hec-ras-60-and-earlier)).

```python
from ras_commander import RasApptainer, SshApptainerTransport

profile = RasApptainer.load_profile("my-site.json")
transport = SshApptainerTransport(profile)

# 1. Stage the complete project (terrain and other subfolders included) and submit.
prep = RasApptainer.render_prepare_job(
    project_folder=r"C:\models\UPGU1", project_name="UPGU1", plan_number="01",
    profile=profile, job_directory=r"C:\jobs\upgu1_p01_prepare",
)
prep = RasApptainer.submit(prep, transport=transport, profile=profile, dry_run=False)

# 2. When terminal, verify and assemble the prepared project (new or empty folder).
prepared = RasApptainer.collect_prepare(prep, transport, profile, r"C:\jobs\upgu1_p01_prepared")
if not prepared.success:
    raise RuntimeError(prepared.problems)

# 3. Render and submit the native solve from the prepared project, exactly as above.
job = RasApptainer.render_job(
    project_folder=prepared.project_folder, project_name="UPGU1", plan_number="01",
    profile=profile, job_directory=r"C:\jobs\upgu1_p01",
)
```

The prepare job verifies the executor SIF and input hashes, copies the project to node scratch, and
runs `python -m ras_commander.remote.apptainer_prepare prepare` in
`apptainer exec --contain --cleanenv` with a node-scratch `/tmp`. Inside the container it:

1. copies the image's baked Wine prefix into `/tmp` (the SIF stays read-only; no overlay or
   `--writable-tmpfs`), preloads the image's [CPU-numbering shim](apptainer-images.md#cpu-numbering-shim),
   and disables the Wine debugger so a crash exits instead of hanging the allocation;
2. under Windows Python, sets the plan's solver cores to `num_cores`
   (`RasPlan.set_num_cores`, `RasPlan.set_2d_flow_options`), clears stale geometry preprocessing,
   and runs `RasPreprocess.preprocess_plan`;
3. checks that `.p##.tmp.hdf`, `.b##`, and `.x##` exist and pass `check_solver_ready`, and writes
   `prepare_receipt.json` with their hashes.

Only files the preparation changed or created are copied back, hash-verified, to `out/<jobid>`.
`collect_prepare` requires scheduler state `COMPLETED`, a matching `SHA256SUMS`, and a succeeded
receipt bound to this request whose artifact hashes match the downloaded files. Only then does it
write the prepared project: the staged tree overlaid with the changed files. The source project is
never modified. Failed prepare jobs are collected too (`logs/prepare.log`), and their node scratch
is retained for diagnosis.

Keep everything the model needs inside `project_folder`; external terrain or DSS paths are not
followed. Use `RasApptainer.check_solver_ready` and the normal solve-job render checks as the
handoff gate; they run unchanged on the prepared files.

!!! warning "Qualification status"
    CLB has run `RasPreprocess.preprocess_plan` under Wine inside Apptainer on Slurm with the same
    per-task prefix pattern, then solved the prepared models natively. On one model, RasMapper's
    direct property-table API crashed under Wine while `RasPreprocess.preprocess_plan` succeeded,
    which is why the prepare job uses the latter. On October 13, 2026 `render_prepare_job` and
    `collect_prepare` prepared Muncie plan 03 (2D) on the CLB cluster in the 6.6 executor SIF built
    from `containers/hecras-wine-executor` (34 s, CPU shim loaded) and the prepared project solved
    natively as described above; on October 14 the same ran for 5.0.7, 6.1, 6.5, 7.0, and 7.0.1.
    That is one model per release; run a representative model end to end on your cluster before
    relying on them.

## The engine command

The only code that knows how the solver is invoked is `ENGINE_SCRIPT_TEMPLATE` in
`ras_commander/RasApptainer.py`. It mirrors `RasCmdr.compute_plan_linux`: `io.*` aliases,
`LD_LIBRARY_PATH`, then `RasUnsteady <project>.p##.tmp.hdf x##` for 6.3.1+, or the pre-6.3.1
`cfile` form: `RasUnsteady <project>.c## b##` (6.1, canonical layout) or `rasUnsteady64
<project>.c## b##` (5.0.7 `bin_ras` layout). The `x`/`c` suffix comes from the
plan's geometry (`Geom File=g##`), not from the plan number. The job checks the completion banner
and fatal markers before promoting the tmp HDF. Collection also requires the full
`RasCmdr._validate_linux_solve` fatal-marker/result check, populated `/Results/Unsteady`, and the
final `Time Date Stamp` matching the planned end time before reporting success. It collects
`engine.log` and the Slurm stdout file when available. If your image differs, adjust the profile (`hecras_dir`, `ld_library_path`,
`geom_preprocess`) or that one template. Scheduler stdout and the `logs/` directory are retained
on all job failure paths; `engine.log` exists only after node-scratch staging begins.

## Limits

- 2D/1D unsteady only, from Windows pre-computed artifacts (workstation or prepare job); no steady
  flow, no geometry-only runs. Steady and one-core unsteady request pools use
  [RasSlurm](slurm-portable-execution.md), which also supports job arrays.
- One plan per solve job. Chained models (for example passing DSS output from one model into the
  next) are not implemented; they need a qualified output/readback boundary, not just Slurm
  dependencies.
- A prepare job and its solve job are two submissions with a local collection in between, so the
  solve job's render-time checks run on the actual prepared files.
- A pre-submission staging interruption may retry its unique attempt; an ambiguous `sbatch` result
  must be reconciled before a new render.
- Offline tests cover rendering, validation, receipts and a mocked transport. Qualify the image and
  solver on your cluster before relying on results.


## End-to-end example

This example shows a public example project's path from preprocessing to Slurm
collection. It is a procedure, not a live qualification of the model, cluster,
or canonical image. Use HEC-RAS 6.6 throughout. Before relying on a campaign,
qualify the selected SIF and a representative prepared model on your cluster.

### 1. Install and check prerequisites

The control host needs Python, this API, and OpenSSH/scp. The primary
preparation recipe below uses a Windows host with installed HEC-RAS 6.6;
completed artifacts can later be rendered and submitted from Windows or Linux.
To use source APIs,
from a repository checkout in an activated isolated environment:

```bash
CI=1 uv pip install -e ".[compute]" h5py
```

`CI=1` skips the maintainer knowledge-base generation step during installation.
On Windows, set it using your shell's environment syntax before running
`uv pip install -e ".[compute]" h5py`. The optional Wine recipe requires Docker
Engine or Windows Docker Desktop in Linux-container mode. The
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
from ras_commander import RasExamples, RasPreprocess, RasApptainer, init_ras_project

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

prepared = RasPreprocess.preprocess_plan(
    plan_number, ras_object=model, max_wait=900, clear_existing=True,
)
if not prepared.success:
    raise RuntimeError(prepared.error)
print(prepared.tmp_hdf_path)
```

Keep all referenced terrain, projection, and other dependencies reachable from
the working project. `clear_existing=True` clears stale preprocessing artifacts
in the working copy; keep the source and external dependencies unchanged.
Never stage or inspect an HDF while its writer is active.

#### Alternative: Wine preparation on the cluster

To keep preparation on Linux, skip the Windows call above and use
[`render_prepare_job` and `collect_prepare`](#wine-preparation-on-the-cluster); then continue at
step 3 with `prepared.project_folder`. On a Linux workstation with Docker,
`RasDocker.preprocess_plan(..., image="rascommander/hec-ras-wine-precompute_6.6:v4")` is the
equivalent single-host route.

For **either** preparation route, check the completed local HDF before rendering:

```python
tmp_hdf = project.parent / f"{project.stem}.p{plan_number}.tmp.hdf"
problems = RasApptainer.check_solver_ready(tmp_hdf, geom_preprocess=False)
if problems:
    raise RuntimeError("Complete Windows preprocessing before staging: " + "; ".join(problems))
```

If the prepared output lacks `/Geometry/GeomPreprocess`, stop and use the native
Windows `RasPreprocess` route on a fresh working copy. Do not synthesize the
missing group or disable input checks. Passing this offline check establishes
structural readiness only.

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
    final_hdf = result.directory / "project" / f"{job.project_name}.p{job.plan_number}.hdf"
    print(HdfResultsPlan.get_unsteady_summary(final_hdf))
else:
    print("Wait for a terminal scheduler state before collecting", state.reason)
```

A successful collection is rooted at `job_directory/collected/<jobid>`.
Its `project/` subfolder contains the final plan HDF and `solver.log`,
`logs/` contains available engine/scheduler logs, and `receipt.json` is at
that collection root. The collection
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
| Prepare job `PREPARE_FAILED` | Read `logs/prepare.log` and `prepare_receipt.json` (`detail`, `worker`). Check the executor's Wine environment variables, the `Ras.exe` path for `ras_version`, and that all model files are inside the project folder |
| Intermittent `0xC0000005` in `RasProcess.exe` during preparation | The allocation's CPU set does not start at CPU 0 and the executor lacks the CPU shim; rebuild it from the current recipe |
| Submission remains `SUBMITTING` after a transport error | `sbatch` may have accepted it. Reconcile the recorded attempt on the cluster; do not retry blindly |
| Failed receipt, output hash, or final-time validation | Retain logs and receipt; inspect `result.problems`. A file's existence or scheduler `COMPLETED` alone does not establish a successful solve |
| Failed-job outputs cannot be downloaded | Inspect the exact remote attempt and retained `logs/`; failure before scratch staging may produce no `engine.log` or output receipt |

The [API reference](../api/remote.md#rasapptainer-source-reference) documents
profile, transport, job, and collection records.
