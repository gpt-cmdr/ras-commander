# Native HEC-RAS on Slurm with Apptainer

`RasApptainer` runs a HEC-RAS 6.6 **native-Linux unsteady** plan on any Slurm cluster that has
Apptainer, starting from the artifacts that Windows preprocessing already produced
(`<project>.p##.tmp.hdf`, `<project>.b##`, `<project>.x##`; see `RasPreprocess`). It is
cluster-agnostic: everything site-specific lives in a JSON site profile.

!!! note "What a receipt means"
    The receipt is computational and transfer evidence (exit codes, hashes, timings). It is not a
    statement that the results are acceptable engineering output. Review results as usual.

## Concepts

| Piece | What it does |
| --- | --- |
| Site profile | JSON file: SSH target, shared staging root, node scratch, SIF path and SHA-256, Slurm account/partition/qos, cores, memory, time |
| Image | One immutable OCI image pulled **once** by an administrator into a shared SIF. Every job re-verifies the SIF SHA-256 before use |
| Job folder | Rendered locally: `inputs/` (tmp.hdf, .b, .x, `SHA256SUMS`), `engine.sh`, `job.sh`, `job.json` |
| Job run | Verifies image and inputs, copies to node-local scratch, runs the solver in Apptainer, hash-verifies the copy-back, writes `receipt.json` |
| Transport | Pluggable object with `run`, `put_tree`, `get_tree`. `SshApptainerTransport` uses OpenSSH/scp; tests use a fake |

The profile field names are a superset of fim-commander's `PortableSiteProfile`, so existing
profiles load unchanged. Unknown fields are rejected, mutable image tags are rejected, and the SIF
SHA-256 is mandatory.

## Site profile

See `examples/site_profiles/clb-slurm.example.json` for the CLB cluster (placeholders only; no
host names, keys or secrets are committed). Key fields:

| Field | Meaning |
| --- | --- |
| `host`, `ssh_user`, `ssh_port`, `identity_file`, `known_hosts_file` | SSH target. Host keys are always checked (`StrictHostKeyChecking=yes`); pin the controller key in `known_hosts_file` |
| `scratch_root` | Shared filesystem root visible to login and compute nodes; job folders are staged below it |
| `node_scratch_root` | Node-local scratch (default `/scratch`); the job works in `<root>/$SLURM_JOB_ID/ras` |
| `image`, `apptainer_image_sha256`, `container_identity` | Shared SIF path, its SHA-256, and the immutable identity (`sif:sha256:<hex>` or `registry/repo@sha256:<hex>`) |
| `oci_source` | OCI reference used for the one-time pull (default `docker://rascommander/hec-ras-linux-unsteady_6.6:v1`) |
| `hecras_dir`, `ld_library_path` | Solver directory inside the image and its library path (defaults match the canonical image: `/opt/hecras-runtime/engine`, `.../libs`, `.../libs/mkl`, `.../libs/rhel_8`) |
| `stack_unlimited`, `omp_stacksize`, `kmp_stacksize` | `ulimit -s unlimited`, `OMP_STACKSIZE`, `KMP_STACKSIZE` (default `2G`). Without them the solver crashes at its first wet step on large 2D meshes. `OMP_NUM_THREADS`/`MKL_NUM_THREADS` follow `num_cores` |
| `num_cores`, `slurm_memory`, `time_limit`, `account`, `partition`, `qos`, `nodelist` | Slurm resources (all but `num_cores` optional) |
| `geom_preprocess` | Opt in to running `RasGeomPreprocess` inside the image before the solver (default off) |

## Canonical image and pulling it once

The canonical image is `rascommander/hec-ras-linux-unsteady_6.6:v1` (Docker Hub, linux/amd64).
Contract read from the registry image config: user `rasworker`, workdir `/job`, entrypoint
`tini -- python -m ras_commander._container_compute` (bypassed: jobs use `apptainer exec`).
Solver `/opt/hecras-runtime/engine/RasUnsteady`; libraries `/opt/hecras-runtime/engine/libs`,
`libs/mkl`, `libs/rhel_8`. The image does **not** contain `RasGeomPreprocess` (leave
`geom_preprocess` false); preprocessing happens on Windows.

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
- the 2D property tables (`Faces Minimum Elevation`, `Faces Area Elevation Values/Info`,
  `Cells Volume Elevation Values/Info`, `Cells Surface Area`) contain NaN (solver SIGSEGV).
  `Cells Minimum Elevation` legitimately holds NaN and is ignored.

Never run it on a file HEC-RAS is still writing. Pass `check_inputs=False` to skip.

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

`status` uses `sacct` (falling back to `squeue`) and reports `UNKNOWN` until accounting appears.
`collect` requires a terminal allocation, downloads `out/<jobid>` into a new local directory,
validates the receipt schema, checks that the receipt is bound to this request and Slurm job, and
re-hashes every output. `success` is true only when the scheduler state is `COMPLETED`, the receipt
says `succeeded`, and all hashes match. Failed jobs are collected too so their logs and receipt are
retained.

### Safety properties

- The request SHA-256 binds the project, plan, staged input hashes, engine script and profile.
- The remote job folder is created exclusively; `submit` never reuses one.
- The submission intent is persisted before `sbatch`. If `sbatch` fails ambiguously the job stays
  in `SUBMITTING` and is never resubmitted automatically; reconcile on the cluster and render a new job.
- Only node-scratch copies are modified (`.b` files are staged with LF line endings; the source
  hashes and the staged hashes are both recorded in `job.json`).
- Copy-back goes to `out/<jobid>.partial`, is hash-verified, then renamed. Scratch is kept when the
  job fails and removed only after a verified success.
- Compiled HDF core counts (`1D Cores`, `2D Cores (per mesh)`) come from Windows preprocessing and
  are not rewritten; `num_cores` sets the allocation and the OpenMP/MKL thread counts.

## The engine command

The only code that knows how the solver is invoked is `ENGINE_SCRIPT_TEMPLATE` in
`ras_commander/RasApptainer.py`. It mirrors `RasCmdr.compute_plan_linux`: `io.*` aliases,
`LD_LIBRARY_PATH`, then `RasUnsteady <project>.p##.tmp.hdf x##`. The `x` suffix comes from the
plan's geometry (`Geom File=g##`), not from the plan number. Completion is accepted only with the
`Finished Unsteady Flow Simulation` banner and no fatal markers; the tmp HDF is then promoted to the
plan HDF. If your image differs, adjust the profile (`hecras_dir`, `ld_library_path`,
`geom_preprocess`) or that one template.

## Limits

- 2D/1D unsteady only from Windows pre-computed artifacts; no steady flow, no geometry-only runs.
- One plan per job. Chained jobs (for example passing DSS output from one model into the next) are not
  implemented; they need a qualified output/readback boundary, not just Slurm dependencies.
- No automatic retries and no job arrays; retry means rendering a new job.
- Offline tests cover rendering, validation, receipts and a mocked transport. Qualify the image and
  solver on your cluster before relying on results.
