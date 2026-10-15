# HEC-RAS Wine preprocessing container

This recipe builds the `rascommander/hec-ras-wine-precompute_{6.5,6.6,7.0.1}`
images. The container provides Wine so [ras-commander][rc] can call installed
Windows HEC-RAS on Linux. It prepares geometry and plan inputs for the matching
[native Linux unsteady image](../hecras-unsteady/README.md). Call both stages
from Windows or Linux with [RasDocker.preprocess_plan()][docker-api] and
[RasDocker.compute_plan()][docker-api]; the
[operating guide](../../docs/user-guide/container-execution.md) and
[notebook](../../examples/512_docker_precompute_and_linux_compute.ipynb) show
the full sequence.

[What happens inside](OPERATION.md) explains Wine, the installed prefix, host
mounts, and the exact ras-commander call sequence.
[How to re-create this container](PREPARATION.md) is the build guide.

## Provenance: v4 and the v5 successor

**The published `v4` images were built from ras2fim-2d, not from this
directory.** Their Wine controller source is
[`gpt-cmdr/ras2fim-2d@dc60b219091e85bcb4564eca45313475c39ce58a`](https://github.com/gpt-cmdr/ras2fim-2d/tree/dc60b219091e85bcb4564eca45313475c39ce58a),
as recorded in the [container catalog](../../docs/user-guide/container-images.md#sources-and-host-compatibility).
The Windows library in their Wine profile is the ras-commander 0.99.2 wheel from
[`9e4217713e954236b0c16023e1815c6f2b7a5309`](https://github.com/gpt-cmdr/ras-commander/tree/9e4217713e954236b0c16023e1815c6f2b7a5309).
**The `v4` images do not contain the CPU shim.**

| Repository and tag | Registry digest |
| --- | --- |
| `rascommander/hec-ras-wine-precompute_6.5:v4` | `sha256:5de3b51455e7405ea0f85f1d9112c8232e41faaad74a4c13bd511fad8c8eda99` |
| `rascommander/hec-ras-wine-precompute_6.6:v4` | `sha256:5fbc07a20693cb867578048be632d88cee02618780259c1c7ddc258c9fbb4318` |
| `rascommander/hec-ras-wine-precompute_7.0.1:v4` | `sha256:f53db7bd9e256f203e07fee77a624aef3fe33ba23e04f94e2e3a9afc62f4359d` |

This directory is the successor recipe. Its next tag is **`v5`**. It is ported
from ras2fim-2d commits `691454a` and `e0786ec`, which add `cpushim.c` on top of
the `v4` controller. Other changes from `v4`:

| Change | `v4` (ras2fim-2d) | This recipe (`v5`) |
| --- | --- | --- |
| CPU-numbering shim | absent | `/opt/hecras-prepare/cpushim.so`, preloaded for Wine processes |
| Shim selector | n/a (`RAS2FIM_CPU_SHIM` in the ras2fim fix branch) | `RAS_COMMANDER_WINE_CPU_SHIM`, shared with the portable executor |
| Default `WINEDEBUG` | `-all` | `err+all,fixme-all`, so .NET and Wine crash reports reach `worker.stderr.log` |
| Wine debugger | prefix starts `winedbg --auto` | `winedbg.exe=d` added to `WINEDLLOVERRIDES` unless the caller names `winedbg` |
| Child-program failure | reported later as invalid hydraulic tables | `Error with program: ...` from the plan HDF reported as the job error |
| Controller environment | `RAS2FIM_JOB_ROOT`, `RAS2FIM_RUNTIME_MANIFEST`, `RAS2FIM_SCRATCH_ROOT`, `RAS2FIM_HECRAS_VERSION`, `RAS2FIM_RAS_COMMANDER_COMMIT`, `RAS2FIM_RAS_COMMANDER_WHEEL_SHA256`, `RAS2FIM_BUNDLED_RUNTIME` | the same names with the `RAS_COMMANDER_PREPARE_` prefix |
| Labels | `io.clb.hec-ras.version`, `io.clb.ras-commander.*`, `io.clb.hec-ras.runtime` | `io.ras-commander.hec-ras-version`, `io.ras-commander.commit`, `io.ras-commander.wheel-sha256`, `io.ras-commander.cpu-shim`, `io.ras-commander.hec-ras-runtime` |

Job behavior, receipts (`ras-commander-job/v1`), runtime manifests
(`ras-commander-runtime/v1`), defaults, and exit codes are otherwise unchanged.
The `RasDocker` host API does not set any of the renamed variables.

**`v5` must be rebuilt and requalified before the tag is published.** No `v5`
payload exists yet. Until one is built from this recipe, qualified, and
published with its digest in the [container catalog](../../docs/user-guide/container-images.md),
`v4` remains the published image and the qualification statements in this
directory describe `v4` only. Qualification must repeat the `v4` sample runs
and add the CPU-set case below.

## Why the CPU shim exists

In a Slurm or cgroup CPU set that does not start at CPU 0 (for example a
two-CPU job on host CPUs 4-5), Wine 11 reports two processors but returns the
host CPU numbers 4 and 5 from `GetCurrentProcessorNumber()`. Windows guarantees
`0..N-1`. The .NET 4.8 runtime in `RasProcess.exe` indexes per-processor state
with that number, and 2D property-table preprocessing fails intermittently with
`0xC0000005` in `clr.dll`. `Ras.exe` records
`Error with program: RasProcess.exe ... Exit Code = -1073741819` and exits 0.

[cpushim.c](cpushim.c) is an `LD_PRELOAD` library that returns each CPU's index
within the process affinity mask (host CPUs 4,5 become 0,1). In paired ras2fim-2d
runs on the same CPUs, preprocessing crashed in 6 of 12 attempts without the
shim and 0 of 24 with it. The map is built once, thread-safely, on first use.

The image sets `RAS_COMMANDER_WINE_CPU_SHIM=/opt/hecras-prepare/cpushim.so`.
`prepare.py` adds it to `LD_PRELOAD` for the Wine processes only and records its
path and SHA-256 under `wine_environment.cpu_shim` in the receipt. Set the
variable to `0` or an empty value to disable the shim, or to another file path
to test a different build.

With a `v4` image, avoid the crash condition by giving each container a CPU set
that starts at CPU 0, or by running without a CPU set.

## Images

| HEC-RAS | Published image | Successor |
|---|---|---|
| 6.5 | `rascommander/hec-ras-wine-precompute_6.5:v4` | `v5` from this recipe, not yet built |
| 6.6 | `rascommander/hec-ras-wine-precompute_6.6:v4` | `v5` from this recipe, not yet built |
| 7.0.1 | `rascommander/hec-ras-wine-precompute_7.0.1:v4` | `v5` from this recipe, not yet built |

Each image includes its matching installed runtime and saved TCU acceptance.
Normal jobs require no separate HEC-RAS installation or external runtime mount.
The Docker Hub descriptions document `v4`; ras2fim-2d retains description
sources at the controller commit: [6.5](https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/dockerhub/6.5.md),
[6.6](https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/dockerhub/6.6.md),
[7.0.1](https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/dockerhub/7.0.1.md).
See [DOCKERHUB.md](../DOCKERHUB.md) for description maintenance. Write `v5`
descriptions after `v5` is qualified.

## Models created on Windows or Linux

Use a disposable model copy and mount its referenced terrain and projection
folders. Relative paths are resolved inside the container: `..\source_terrain`
and `..\projection` must lead to mounted folders. Mounting a model folder alone
does not expose its siblings. The terrain HDF must also have access to its
referenced TIFF files.

Before HEC-RAS starts, [model_checks.py](model_checks.py) reads the selected
plan, geometry and unsteady flow inputs, checks the existing 2D geometry HDF,
and verifies the projection, terrain HDF and referenced raster files. Missing
dependencies fail before any model file is modified. The worker then
normalizes the selected `.prj`, `.p##`, `.g##` and `.u##` text files to Windows
CRLF line endings. The generated `.x##` output is converted to Linux LF for the
separate Linux calculation stage.

Before reporting success, the worker opens both the geometry HDF and temporary
plan HDF. They must retain the input's 2D area names and cell counts and contain
valid cell-volume and face-area elevation tables. A file's size, `File Type`
attribute, or a `/Results` group is not proof of valid preprocessing.

## Run on a Linux filesystem

The commands use the published `v4` image; substitute a qualified `v5`
reference when one exists.

```bash
docker pull rascommander/hec-ras-wine-precompute_6.5:v4

docker run --rm --pull always --network none --read-only \
  --user 1000:1000 --cpus 2 --memory 6g --memory-swap 6g \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 \
  --mount type=bind,src=/shared/model,dst=/job \
  --mount type=bind,src=/shared/source_terrain,dst=/source_terrain,readonly \
  --mount type=bind,src=/shared/projection,dst=/projection,readonly \
  --mount type=volume,dst=/run/ras-job \
  --device /dev/ntsync \
  rascommander/hec-ras-wine-precompute_6.5:v4 \
  prepare --project /job/model.prj --plan 01 \
          --num-cores 2 --timeout 900 --run-id example-001 --replace-generated
```

`/shared/model` is a disposable folder on the Docker host, writable by UID 1000.
Use a unique run ID. `--replace-generated` can remove an existing final plan
HDF, so preserve wanted results elsewhere. Omit `--device /dev/ntsync` when the
host does not supply it. Read and agree to the
[HEC-RAS terms](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/terms-and-conditions-of-use)
before use.

For project `model`, plan 01 and geometry 01, the required outputs are
`model.p01.tmp.hdf`, `model.b01`, and `model.x01`. The receipt is
`.ras-commander/runs/<run-id>/prepare.json` under the model folder. Exit codes
are 0 for success, 1 for a recorded failure, and 2 for configuration/I/O errors.

## Run on a Windows drive

Use `--user root` for Windows Docker Desktop bind mounts. Set `$models` to the
parent folder containing the model and both dependency folders.

```powershell
$models = 'D:\models\02_model_copies'
$name = 'model'
docker run --rm --pull always --user root --cpus 2 --mount "type=bind,src=$models\$name,dst=/job" --mount "type=bind,src=$models\source_terrain,dst=/source_terrain,readonly" --mount "type=bind,src=$models\projection,dst=/projection,readonly" rascommander/hec-ras-wine-precompute_6.5:v4 prepare --project "/job/$name.prj" --plan 01 --num-cores 2 --timeout 900 --replace-generated
```

## CPU settings

`prepare --num-cores N` defaults to 2 and accepts integers from 1 to 8. Set
Docker's `--cpus N` to the same count. The worker writes the count into the
working plan through `RasPlan.set_num_cores()` and
`RasPlan.set_2d_flow_options(include_default=True)`, reads it back before
preprocessing, and records it as `arguments.num_cores`.

## Slurm and Apptainer

The preprocessing image is not qualified through Apptainer. A SIF is read-only,
so `/run/ras-job` is not writable: set `RAS_COMMANDER_PREPARE_SCRATCH_ROOT` to a
node-local writable directory and bind the model at `/job`. The CPU shim exists
for this route, because Slurm CPU sets often do not start at CPU 0. For portable
plan execution through Slurm, use the
[Wine executor derivative](../hecras-wine-executor/README.md) and the
[SIF builder](../apptainer/README.md).

## Optional runtime override

Advanced users can mount a matching controlled profile at `/runtime/wine-seed`
read-only. It must declare the selected HEC-RAS version and matching
ras-commander build in its [runtime manifest](runtime-manifest.example.json).
The default job uses the installation already included in the image.

## Files

| File | Purpose |
|---|---|
| [Dockerfile](Dockerfile) | Pinned Debian/Python base, WineHQ, Xvfb, `cpushim` build stage, controller files, bundled runtime stage. |
| [cpushim.c](cpushim.c) | `LD_PRELOAD` `sched_getcpu` remap for CPU sets that do not start at 0. |
| [prepare.py](prepare.py) | Linux controller: runtime verification, private prefix copy, Wine environment, worker launch, output checks, receipt. |
| [windows_worker.py](windows_worker.py) | Windows Python worker calling the ras-commander preprocessing APIs under Wine. |
| [model_checks.py](model_checks.py) | Dependency preflight, CRLF normalization, and 2D HDF validation. |
| [bundle_profile.py](bundle_profile.py) | Exports a finalized Wine profile into an external `hecras_runtime` build context. |
| [verify_bundled_runtime.sh](verify_bundled_runtime.sh) | Fresh-copy runtime and saved-TCU verification of a built image. |
| [verify_windows_runtime.py](verify_windows_runtime.py) | Windows-side installed-version and saved-TCU check, launched by the script above. |
| [runtime-manifest.example.json](runtime-manifest.example.json) | Manifest structure only; zero fingerprints are placeholders. |
| [ras-commander-call-sequence.mmd](ras-commander-call-sequence.mmd) | Editable Mermaid source for the API sequence in [OPERATION.md](OPERATION.md). |

The prepared profile keeps the retained wheel at
`C:\ras2fim-runtime\ras_commander-0.99.2-py3-none-any.whl`. That path is part of
the existing profile data and `bundle_profile.py` keeps it; it is not an
environment or label name.

[rc]: https://rascommander.info/ras/
[docker-api]: ../../ras_commander/RasDocker.py
