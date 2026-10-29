# HEC-RAS Wine preprocessing container

This recipe builds the `hec-ras-wine-precompute_<version>` images published
on GHCR. The container provides Wine so [ras-commander][rc] can call installed
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

## Published images and provenance

The current images are published on GHCR as
`ghcr.io/gpt-cmdr/hec-ras-wine-precompute_<version>:0.106.0` for HEC-RAS
5.0.7, 6.1, 6.5, 6.6, 7.0, and 7.0.1. They include the CPU shim and the
installed Wine runtime. Select a digest with `RasContainerImages.get` as shown
in the [operating guide](../../docs/user-guide/container-execution.md).
For Slurm, use the published [Wine executor SIF](../hecras-wine-executor/README.md).

The [runtime build](../hecras-wine-runtime/README.md) creates an empty Wine base
prefix, installs its prerequisites, and installs the selected official HEC-RAS
release and ras-commander wheel. The release builder names its local preprocessing
image `v5-<commit>`; the published GHCR release tag is `0.106.0`. The
[October qualification record](../../docs/user-guide/apptainer-images.md#qualification-status)
covers the release builds and final SIFs. These records do not establish
byte-for-byte rebuilds on arbitrary clean hosts.

The older Docker Hub `rascommander/hec-ras-wine-precompute_<version>:v4`
images for 6.5, 6.6, and 7.0.1 were built from
[`ras2fim-2d@dc60b219091e85bcb4564eca45313475c39ce58a`](https://github.com/gpt-cmdr/ras2fim-2d/tree/dc60b219091e85bcb4564eca45313475c39ce58a),
with the ras-commander 0.99.2 Windows wheel. Those payloads do not contain the
CPU shim and use `RAS2FIM_*` controller environment names. Their exact digests
and September qualification remain in the
[historical catalog](../../docs/user-guide/container-images.md#historical-docker-hub-images).
The current recipe uses `RAS_COMMANDER_PREPARE_*` controller names and
`RAS_COMMANDER_WINE_CPU_SHIM`; receipts remain `ras-commander-job/v1`.

### Controller changes from Docker Hub v4

| Change | `v4` (ras2fim-2d) | Current recipe |
| --- | --- | --- |
| CPU-numbering shim | absent | `/opt/hecras-prepare/cpushim.so`, preloaded for Wine processes |
| Shim selector | n/a (`RAS2FIM_CPU_SHIM` in the ras2fim fix branch) | `RAS_COMMANDER_WINE_CPU_SHIM`, shared with the portable executor |
| Default `WINEDEBUG` | `-all` | `err+all,fixme-all`, so .NET and Wine crash reports reach `worker.stderr.log` |
| Wine debugger | prefix starts `winedbg --auto` | `winedbg.exe=d` added to `WINEDLLOVERRIDES` unless the caller names `winedbg` |
| Child-program failure | reported later as invalid hydraulic tables | `Error with program: ...` from the plan HDF reported as the job error |
| Controller environment | `RAS2FIM_JOB_ROOT`, `RAS2FIM_RUNTIME_MANIFEST`, `RAS2FIM_SCRATCH_ROOT`, `RAS2FIM_HECRAS_VERSION`, `RAS2FIM_RAS_COMMANDER_COMMIT`, `RAS2FIM_RAS_COMMANDER_WHEEL_SHA256`, `RAS2FIM_BUNDLED_RUNTIME` | the same names with the `RAS_COMMANDER_PREPARE_` prefix |
| Labels | `io.clb.hec-ras.version`, `io.clb.ras-commander.*`, `io.clb.hec-ras.runtime` | `io.ras-commander.hec-ras-version`, `io.ras-commander.commit`, `io.ras-commander.wheel-sha256`, `io.ras-commander.cpu-shim`, `io.ras-commander.hec-ras-runtime` |

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

## Runtime included in the image

Each image includes its matching installed HEC-RAS runtime. Normal jobs need
no separate HEC-RAS installation, external runtime mount, Windows machine, or
Windows VM. Wine runs the Windows programs in a task-private copy of the prefix.
Review the terms before use; HEC-RAS 6.0 and earlier require the
[per-task acceptance setting](../../docs/user-guide/apptainer-images.md#hec-ras-60-and-earlier).

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

The commands use the current GHCR release tag. For retained runs, use its
digest from the [catalog](../../docs/user-guide/container-images.md).

```bash
docker pull ghcr.io/gpt-cmdr/hec-ras-wine-precompute_6.5:0.106.0

docker run --rm --pull always --network none --read-only \
  --user 1000:1000 --cpus 2 --memory 6g --memory-swap 6g \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 \
  --mount type=bind,src=/shared/model,dst=/job \
  --mount type=bind,src=/shared/source_terrain,dst=/source_terrain,readonly \
  --mount type=bind,src=/shared/projection,dst=/projection,readonly \
  --mount type=volume,dst=/run/ras-job \
  --device /dev/ntsync \
  ghcr.io/gpt-cmdr/hec-ras-wine-precompute_6.5:0.106.0 \
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
docker run --rm --pull always --user root --cpus 2 --mount "type=bind,src=$models\$name,dst=/job" --mount "type=bind,src=$models\source_terrain,dst=/source_terrain,readonly" --mount "type=bind,src=$models\projection,dst=/projection,readonly" ghcr.io/gpt-cmdr/hec-ras-wine-precompute_6.5:0.106.0 prepare --project "/job/$name.prj" --plan 01 --num-cores 2 --timeout 900 --replace-generated
```

## CPU settings

`prepare --num-cores N` defaults to 2 and accepts integers from 1 to 8. Set
Docker's `--cpus N` to the same count. The worker writes the count into the
working plan through `RasPlan.set_num_cores()` and
`RasPlan.set_2d_flow_options(include_default=True)`, reads it back before
preprocessing, and records it as `arguments.num_cores`.

## Slurm and Apptainer

Use the published [Wine executor](../hecras-wine-executor/README.md) for
`RasApptainer.render_prepare_job` or portable requests through `RasSlurm`.
The Docker preprocessing controller is a different entry point; do not substitute
its image directly. The executor supplies the CPU shim and copies the baked
prefix into private node scratch while the SIF stays read-only. See the
[qualification record](../../docs/user-guide/apptainer-images.md#qualification-status).

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

The historical `v4` profile keeps the retained wheel at
`C:\ras2fim-runtime\ras_commander-0.99.2-py3-none-any.whl`. That path is part of
the existing profile data and `bundle_profile.py` keeps it; it is not an
environment or label name.

[rc]: https://rascommander.info/ras/
[docker-api]: ../../ras_commander/RasDocker.py
