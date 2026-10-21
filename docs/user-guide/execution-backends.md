# Choose an execution backend

Choose the API by the runtime and input contract you need. Docker supplies a
container engine; Apptainer runs a SIF image on a cluster; Slurm allocates the
cluster resources. Installing one does not configure the others.

| API | Use it for | Inputs and runtime | Scheduling and resources |
| --- | --- | --- | --- |
| [`RasDocker`](container-execution.md) | Wine preprocessing followed by native Linux unsteady computation on Windows or Linux | Complete working model, terrain/projection dependencies, and matching published Wine/native images | Local Docker CLI; engine must see bind-mount paths. One plan per container, 1–8 solver cores; `run_batch` is sequential |
| [`DockerWorker`](remote-execution.md#docker-worker-setup) | Native computation in a distributed worker pool | Host preprocessing plus an image implementing the worker's `run_ras.sh` contract | Local daemon or remote Docker over SSH; pool configured with `cores_total` and `cores_per_plan` |
| [`RasPortableDocker`](../api/remote.md#portable-plan-execution) | Portable steady/unsteady execution requests | Complete project bundle, immutable OCI identity, and an image with the portable Python executor; Windows execution on Linux requires a prepared Wine runtime | One core per request; `execute_pool` controls concurrent requests |
| [`RasSlurm`](slurm-portable-execution.md) | Schedule portable steady/unsteady execution requests through Apptainer, including Windows HEC-RAS under Wine | Same portable request contract, a shared [executor SIF](apptainer-images.md), and `SlurmSiteConfig` | One-core contained steps with private node scratch; one exclusive-node pool or a throttled job array; local scheduler or SSH transport |
| [`RasApptainer`](slurm-apptainer-execution.md) | Run a native HEC-RAS 6.x/7.x unsteady plan on Slurm, optionally after a Wine prepare job on the same cluster | Solver-ready temporary HDF, boundary and geometry inputs (or a complete project for the prepare job); shared SIFs and a JSON site profile | One plan per allocation; solver cores match the allocation; OpenSSH/scp transport |
| [`LocalWorker` / `PsexecWorker`](remote-execution.md) | Local Windows or distributed Windows execution | Installed Windows HEC-RAS and complete projects | Local processes or remote Windows hosts |

`init_ras_worker` supports `psexec`, `local`, and `docker` workers. Use
`RasSlurm` or `RasApptainer` for Slurm execution; the two Slurm APIs have
different profiles and receipts.

The Apptainer paths mirror the Docker workflow: `RasDocker.preprocess_plan`
corresponds to `RasApptainer.render_prepare_job` (Wine preprocessing in an
executor SIF), and `RasDocker.compute_plan` to `RasApptainer.render_job`
(native solve). `RasPortableDocker` corresponds to `RasSlurm`.

## Start with the appropriate guide

- **Docker on a workstation:** follow [Container Execution](container-execution.md)
  and [notebook 512](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/512_docker_precompute_and_linux_compute.ipynb).
- **Prepared native unsteady plan on a cluster:** follow the
  [Slurm + Apptainer tutorial](slurm-apptainer-execution.md#end-to-end-example).
- **Portable request pool or job array on a cluster:** follow
  [Portable Slurm Execution](slurm-portable-execution.md).
- **Building or converting images for a cluster:** follow
  [Apptainer images](apptainer-images.md).
- **Existing distributed worker pool:** follow [Remote Execution](remote-execution.md).

## Image compatibility and qualification

The [container catalog](container-images.md) lists the published image pairs,
digests, architecture, source revisions, and qualification scope. These images
are tested through `RasDocker`. Their existence does not establish compatibility
with every executor: `DockerWorker` expects its configured shell runner, while
portable execution expects `python -m ras_commander.remote.execute_request` and
a compatible installed runtime.

CLB has run `RasSlurm` (Wine steady requests) and `RasApptainer` (native
unsteady solves) live on its Slurm cluster with site-built SIFs, and has run
Wine preprocessing under Apptainer with the per-task prefix pattern these APIs
use. On October 13, 2026 the current APIs were run live with the 6.6 Wine
executor built from this repository and the published native 6.6 SIF: a
`RasSlurm` pool and a job array (two concurrent Wine requests each), and a
`RasApptainer` Wine prepare job followed by a native solve, all collected
successfully. Qualify the exact images and a representative model on your
cluster first. See
[HPC design and qualification boundaries](container-hpc-design.md).

Keep source models separate from working copies. Match the HEC-RAS version
across preparation and computation, retain receipts and logs, and inspect the
result HDF and modeled time window. A computational success receipt does not
establish that the results are acceptable engineering output.
