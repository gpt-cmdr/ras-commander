# Docker container API

`RasDocker` launches the Wine preparation and native Linux computation images
through the Docker CLI. It does not use the Docker Python SDK. See
[Container Execution](../user-guide/container-execution.md) for working-copy
layout, dependencies, and a complete two-stage example, and the
[container catalog](../user-guide/container-images.md) for public images.

The host API and library embedded in an image can have different revisions.
Record both when reproducing a run. The published image pairs cover HEC-RAS
6.5, 6.6, and 7.0.1; use the same version for both stages.

## RasDocker

Call these static methods directly:

- `preprocess_plan`: run Windows HEC-RAS under Wine and retain a preparation receipt.
- `compute_plan`: run the matching native Linux unsteady solver from prepared inputs.
- `run_plan`: prepare and compute, stopping after failed preparation.
- `run_batch`: process independent working copies sequentially and retain a batch summary.

`replace_generated=True` permits replacement of generated model files; use a
working copy. Each container bind-mounts the project read/write and optional
dependencies read-only. The Docker engine must be able to access the source
paths. Remote daemons do not automatically receive uploads through this API.

`num_cores` defaults to 2 and accepts integers 1–8. CPU quota and solver thread
settings use that count. `stream_callback` receives live output and lifecycle
events; `resume=True` reuses completed stages only after their retained evidence
passes the resume checks. See the operating guide for callback and batch examples.

::: ras_commander.RasDocker.RasDocker
    options:
      show_root_heading: false
      show_source: false

## ContainerResult

Check `success` before using outputs. `receipt_path` is the expected path even
when no receipt was produced; `error`, `stdout`, `stderr`, and `returncode`
help diagnose host or container failures.

::: ras_commander.RasDocker.ContainerResult
    options:
      show_root_heading: false
      show_source: false

## ContainerBatchResult

::: ras_commander.RasDocker.ContainerBatchResult
    options:
      show_root_heading: false
      show_source: false

## Other container and scheduler APIs

[`RasPortableDocker`, `RasSlurm`, and `RasApptainer`](remote.md) have separate
execution contracts. Use the [backend comparison](../user-guide/execution-backends.md)
to select an API before selecting an image.
