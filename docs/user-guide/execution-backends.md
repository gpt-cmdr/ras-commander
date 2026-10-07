# Choose an execution backend

Choose the API by the runtime and input contract you need. Docker supplies a
container engine; Apptainer runs a SIF image on a cluster; Slurm allocates the
cluster resources. Installing one does not configure the others.

| API | Use it for | Inputs and runtime | Scheduling and resources |
| --- | --- | --- | --- |
| [`RasDocker`](container-execution.md) | Wine preprocessing followed by native Linux unsteady computation on Windows or Linux | Complete working model, terrain/projection dependencies, and matching published Wine/native images | Local Docker CLI; engine must see bind-mount paths. One plan per container, 1–8 solver cores; `run_batch` is sequential |
| [`DockerWorker`](remote-execution.md#docker-worker-setup) | Native computation in a distributed worker pool | Host preprocessing plus an image implementing the worker's `run_ras.sh` contract | Local daemon or remote Docker over SSH; pool configured with `cores_total` and `cores_per_plan` |
| [`RasPortableDocker`](../api/remote.md#portable-plan-execution) | Portable steady/unsteady execution requests | Complete project bundle, immutable OCI identity, and an image with the portable Python executor; Windows execution on Linux requires a prepared Wine runtime | One core per request; `execute_pool` controls concurrent requests |
| [`RasSlurm`](slurm-portable-execution.md) | Schedule portable execution requests through Apptainer | Same portable request contract, a compatible shared SIF, and `SlurmSiteConfig` | One exclusive-node allocation with bounded one-core tasks; local scheduler or SSH transport |
| [`RasApptainer`](slurm-apptainer-execution.md) | Run a Windows-preprocessed native unsteady plan (canonical HEC-RAS 6.6 profile) on Slurm | Solver-ready temporary HDF, boundary and geometry inputs; a shared SIF and JSON site profile | One plan per allocation; solver cores match the allocation; OpenSSH/scp transport |
| [`LocalWorker` / `PsexecWorker`](remote-execution.md) | Local Windows or distributed Windows execution | Installed Windows HEC-RAS and complete projects | Local processes or remote Windows hosts |

`SlurmWorker`, `SshWorker`, `WinrmWorker`, `AwsEc2Worker`, and `AzureFrWorker`
are exported stubs. `init_ras_worker("slurm", ...)` raises
`NotImplementedError`; use `RasSlurm` or `RasApptainer` for implemented Slurm
execution. The two Slurm APIs have different profiles and receipts.

## Start with the appropriate guide

- **Docker on a workstation:** follow [Container Execution](container-execution.md)
  and [notebook 512](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/512_docker_precompute_and_linux_compute.ipynb).
- **Prepared native unsteady plan on a cluster:** follow the
  [Slurm + Apptainer tutorial](slurm-apptainer-execution.md#end-to-end-example).
- **Portable request pool on a cluster:** follow
  [Portable Slurm Execution](slurm-portable-execution.md).
- **Existing distributed worker pool:** follow [Remote Execution](remote-execution.md).

## Image compatibility and qualification

The [container catalog](container-images.md) lists the published image pairs,
digests, architecture, source revisions, and qualification scope. These images
are tested through `RasDocker`. Their existence does not establish compatibility
with every executor: `DockerWorker` expects its configured shell runner, while
portable execution expects `python -m ras_commander.remote.execute_request` and
a compatible installed runtime.

The canonical HEC-RAS 6.6 SIF profile for `RasApptainer` is configured from image
layout and registry metadata; it has not been qualified by a live run through
that API. Other CLB SIF runs are operational evidence for those images only.
TACC integration and Wine preprocessing under Apptainer also require separate
qualification. See [HPC design and qualification boundaries](container-hpc-design.md).

Keep source models separate from working copies. Match the HEC-RAS version
across preparation and computation, retain receipts and logs, and inspect the
result HDF and modeled time window. A computational success receipt does not
establish that the results are acceptable engineering output.
