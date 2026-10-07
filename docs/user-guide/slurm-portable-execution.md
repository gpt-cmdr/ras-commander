# Portable execution requests on Slurm

`RasSlurm` renders, stages, submits, monitors, cancels, and collects portable
execution requests in one exclusive-node Slurm allocation. Each request runs
with one core through Apptainer. This differs from
[`RasApptainer`](slurm-apptainer-execution.md), which stages native solver-ready
artifacts for one unsteady plan per allocation.

## Prerequisites

- A complete, immutable project copy per request, with unique execution IDs.
- A site-qualified SIF on shared storage visible to compute nodes, its SHA-256,
  and an immutable `container_identity` shared by the site and requests.
- An image with Python, the portable executor
  (`ras_commander.remote.execute_request`), and the requested HEC-RAS runtime.
  Windows execution on Linux needs the Wine seed/Python settings described in
  [Portable Plan Execution](../api/remote.md#portable-plan-execution).
- Slurm commands and Apptainer on the cluster. The allocation launcher needs
  host Python 3; the container needs its own Python executor.
- For SSH mode, verified SSH access and rsync or scp on the transfer hosts.
  Remote scratch and the SIF must be visible to login and compute nodes.

The [published Wine/native pairs](container-images.md) are qualified for
`RasDocker`; they are not a qualified portable-executor image. Supply a
compatible image rather than substituting one by name. No live Slurm run is
claimed by this tutorial.

## Create a portable bundle

Run this from an installed version exposing the portable APIs, or from a
checkout installed with `CI=1 uv pip install -e ".[compute]"` in an activated
isolated environment. Create a new bundle directory containing a complete
working project at `input/Model.prj`, with all its referenced files. Keep
`results/` outside `input/`; do not change the input after creating the request.
Use [RasExamples](../examples/example-projects.md) for a public example project
and inspect its plan table before selecting a plan.

```python
from pathlib import Path
from ras_commander.remote import RasExecutionRequest
from ras_commander.RasSlurm import (
    RasSlurm, SlurmSiteConfig, SlurmTransportConfig, SlurmSubmission,
)

bundle = Path("bundles/reach-001").resolve()
# Replace with the actual sha256sum of the site's qualified SIF.
sif_sha256 = "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS"
identity = f"sif:sha256:{sif_sha256}"

request = RasExecutionRequest.create(
    execution_id="reach-001",
    request_directory=bundle,
    source_project_path="input/Model.prj",
    plan_number="01",  # Select an existing supported plan in the project.
    output_directory="results",
    ras_executable=r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe",
    container_identity=identity,
    timeout_seconds=3600,
)
request_path = request.write(bundle / "request.json")
```

The executable is the path **inside the image's Windows runtime**, not on the
workstation. The request binds the project file and tree hashes. A SIF identity
works for Slurm; `RasPortableDocker` requires an immutable OCI reference instead.

## Render without submitting

```python
site = SlurmSiteConfig(
    site_name="example",
    apptainer_image="/shared/images/portable-hecras.sif",
    apptainer_image_sha256=sif_sha256,
    container_identity=identity,
    slots_per_node=2,
    slurm_memory="3G",  # Per-task step limit; allocation reserves this times slots.
    time_limit="02:00:00",
    # Add account, partition, qos, and modules required by your site.
)
submission = RasSlurm.render_submission(
    [request_path], "submissions/reach-001", site=site,
)
print(submission.submission_directory)
```

Rendering creates self-contained `bundles/`, `slurm_batch.json`,
`portable_slurm_launcher.py`, `submit.sbatch`, and `slurm_submission.json`.
The destination must be absent or empty. Review the generated allocation
before staging; rendering makes no scheduler call.

`slots_per_node` bounds concurrent one-core tasks. When `slurm_memory` is set,
the allocation requests `slurm_memory × slots_per_node` and each task step
uses `slurm_memory` as its memory limit. The example requests `--mem=6G` for
two slots and `--mem=3G` for each step. When it is omitted, this API emits no
memory directive; the site's Slurm defaults determine available memory.
`memory_per_task` is accepted by the configuration but currently does not
set allocation or step memory. Use `slurm_memory` for an explicit reservation.
Choose the wall time for the whole pool, including staging and executor
margins; it is not automatically checked against each request's timeout.

## Stage and submit

```python
transport = SlurmTransportConfig(
    mode="ssh", hostname="login.cluster.example", username="your-user",
    remote_scratch="/shared/jobs/ras-commander", transfer_mode="scp",
    identity_file=str(Path("~/.ssh/cluster_ed25519").expanduser()),
)
submission = RasSlurm.stage(submission, transport)
submission = RasSlurm.submit(submission)
print(submission.job_id)
```

Use `SlurmTransportConfig(mode="local")` when running on the cluster's login
host with shared paths. Staging verifies rendered-file identities and SSH mode
copies the full submission. Submission calls `sbatch` and persists the job ID.
The real submission consumes the selected site's allocation.

For several independent requests, pass their paths to `render_submission`.
The convenience method `submit_batch(request_paths, directory, site=site,
transport=transport)` performs rendering, staging, and submission immediately.
Use separate bundles and unique IDs/output paths; this is a bounded task pool,
not a Slurm job array or chained-model workflow.

## Reload, inspect, and collect

```python
submission = SlurmSubmission.read("submissions/reach-001/slurm_submission.json")
status = RasSlurm.status(submission)
print(status.allocation_state)

# After scheduler accounting reports the allocation has ended:
collection = RasSlurm.collect(submission)
print(collection.success, collection.errors)
for execution_id, receipt in collection.receipts.items():
    if receipt is not None:
        print(execution_id, receipt.success, receipt.result_hdf_path)
```

SSH collection retrieves each request's output directory into the rendered
local bundle. It checks receipts against frozen requests, the SIF identity,
result HDF digests, and scheduler step accounting. One failed request remains
in `errors`; do not treat successful neighboring requests as a successful pool.
Keep the final HDF selected by the receipt and inspect its results through the
[HDF APIs](../api/hdf.md). Retain receipts and logs for failed requests too.

`RasSlurm.cancel(submission)` cancels the recorded allocation. If a submission
command fails without a trustworthy job ID, reconcile the allocation on the
cluster before submitting again. Do not treat a transport error as proof that
Slurm never accepted the job.

## Troubleshooting

| Symptom | Check and next action |
| --- | --- |
| Render rejects identity or paths | Use a real SIF SHA-256, matching request/site identities, distinct bundles, and an empty submission directory |
| Remote staging fails | Check SSH, transfer tools, shared-path permissions, and whether that exact submission directory already exists |
| Job remains pending | Inspect Slurm's resource/account/partition reason; reduce requests or correct the site settings |
| Executor cannot import or launch | Verify Python, installed portable executor, executable path, and Wine environment in the selected SIF |
| Receipt or scheduler step fails | Read `collection.errors`, retained solver logs, and accounting; a final HDF filename alone is insufficient |
| Allocation expires before the pool ends | Increase allocation wall time or reduce pool size; account for queued tasks and executor overhead |

See the [rendered API reference](../api/remote.md#rasslurm-source-reference)
for configuration fields and return records.
