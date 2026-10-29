# Portable HEC-RAS Wine executor image

This recipe derives a portable-executor image from a
[Wine preprocessing image](../hecras-wine-precompute/README.md). The derivative
runs [portable execution requests](../../docs/api/remote.md#portable-plan-execution)
through `python -m ras_commander.remote.execute_request execute-request
/job/request.json`: Linux Python reads the request, copies the baked Wine prefix
into task-private scratch, and runs the same command in Windows Python under
Wine, where ras-commander drives the installed Windows HEC-RAS.

[RasSlurm](../../docs/user-guide/slurm-portable-execution.md) launches this
contract under Slurm and Apptainer; `RasPortableDocker` uses it with Docker.
Published executors and ready-made SIFs are available on GHCR with tag
`0.106.0` for the releases in the
[container catalog](../../docs/user-guide/container-images.md). Each includes
the installed Wine prefix, Windows Python, HEC-RAS, and the CPU shim. Running
the image on Linux needs no Windows machine or VM. Use
`RasContainerImages.resolve_sif("wine-executor", "6.6")` to pull and verify the
published SIF, or `RasContainerImages.get("wine-executor", "6.6").reference`
for Docker.

The [October qualification record](../../docs/user-guide/apptainer-images.md#qualification-status)
documents Muncie 1D/2D Wine execution, preparation/native handoff, and final SIF
requalification. Run a representative model at your site before a campaign.
The build steps below are for a custom image or a controlled rebuild.

## What the derivative adds

[build_executor_image.sh](build_executor_image.sh) starts from a
preprocessing image pinned by digest (GHCR for the current release). It
installs one ras-commander wheel into both Pythons and commits the result:

| Item | Inside the image |
|---|---|
| Linux Python | the wheel with its `compute` extra (`h5py`, `numpy`, `pandas`, `psutil`); resolved from the package index at build time, optionally constrained |
| Windows Python `C:\Python311` | the same wheel, `--no-deps`; the base profile already holds the Windows dependencies |
| GDAL bridge | `C:\Python311\GDAL` -> `../Program Files (x86)/HEC/HEC-RAS/<version>/GDAL`, a relative link that survives the per-task prefix copy, so RasMapperLib calls through pythonnet find HEC-RAS GDAL |
| CPU shim | `/opt/ras-commander-executor/cpushim.so`; see [Why the CPU shim exists](../hecras-wine-precompute/README.md#why-the-cpu-shim-exists) |
| Entry point | `tini --`; the default command prints `execute_request --help` |
| Default user and directory | `rasworker` (UID 1000), `/job` |

The image environment is the executor contract read by
[execute_request.py](../../ras_commander/remote/execute_request.py):

| Variable | Value |
|---|---|
| `RAS_COMMANDER_WINE_PREFIX_SEED` | `/runtime/wine-seed/prefix` |
| `RAS_COMMANDER_WINE_PYTHON` | `C:\Python311\python.exe` |
| `RAS_COMMANDER_WINE_ARCH` | `win64` |
| `RAS_COMMANDER_WINE_CPU_SHIM` | `/opt/ras-commander-executor/cpushim.so`; `0` or empty disables it |

Labels record provenance: `org.opencontainers.image.revision` and
`io.ras-commander.commit` (wheel source commit), `io.ras-commander.wheel` and
`io.ras-commander.wheel-sha256`, `org.opencontainers.image.base.name` /
`io.ras-commander.parent-image` (the pinned base reference),
`io.ras-commander.parent-image-id`, `io.ras-commander.cpu-shim-source` (`base`
or `built`), and `io.ras-commander.executor-recipe-sha256` (the build script).

The Wine pip install updates the seed prefix, so the base image's
`/runtime/wine-seed/runtime.json` hashes no longer describe it. The
`prepare.py` controller inherited from the base is not supported in the
executor image; use the preprocessing image for `RasDocker.preprocess_plan()`.

## Build

The build needs a Linux Docker host with BuildKit, network access to the Python
package index for the Linux dependencies, and a pure-Python wheel built from a
known commit:

```bash
CI=1 python -m pip wheel --no-deps --wheel-dir /tmp/rc-wheel .
RAS_COMMANDER_COMMIT=$(git rev-parse HEAD) \
bash containers/hecras-wine-executor/build_executor_image.sh 6.6 \
  ghcr.io/gpt-cmdr/hec-ras-wine-precompute_6.6@sha256:1eef40777dd4a1c99a18a1a6b9ce5524ea163b45133901dbe5d38895fef99c11 \
  /tmp/rc-wheel/ras_commander-<version>-py3-none-any.whl \
  local/hec-ras-wine-executor_6.6:review
```

`CI=1` skips the knowledge-base generation step in `setup.py`. Build from a
clean checkout so the commit identifies the wheel. Pass a pip constraints file
as the optional fifth argument to pin the Linux dependency versions. Current base
digests are in the
[container catalog](../../docs/user-guide/container-images.md#current-immutable-registry-identities).

Steps performed by the script:

1. Validate arguments: version 6.5, 6.6 or 7.0.1; a digest-pinned base whose
   environment declares the same HEC-RAS version; a `py3-none-any` wheel; a
   40-hex commit.
2. Take the CPU shim from the base when `/opt/hecras-prepare/cpushim.so` exists
   (successor `v5` images). Otherwise (published `v4` images) compile
   [cpushim.c](../hecras-wine-precompute/cpushim.c) with
   `docker buildx build --target cpushim-artifact`, using the pinned
   compiler stage of the [preprocessing Dockerfile](../hecras-wine-precompute/Dockerfile)
   and a build context holding only `cpushim.c`. Only the `.so` is exported;
   the compiler does not enter the image.
3. Run one root container from the base with `--security-opt
   apparmor=unconfined` (BuildKit cannot run Wine on this host type; set
   `WINE_SECURITY_OPT=` to omit the option). Install both wheels, add the GDAL
   bridge, install the shim and check that it is an x86-64 ELF, stop
   `wineserver`, and make the seed root-owned and world-readable.
4. `docker commit` the container with the environment, labels, entry point,
   working directory, and user above.
5. Verify the image with networking disabled: the four variables have their
   exact values, the seed and shim are regular paths, Linux `ras_commander`
   matches the wheel version, `execute_request --help` runs, and Windows Python
   imports `ras_commander.remote.execute_request` with the same version from a
   fresh private copy of the prefix with the shim preloaded.

The script prints the image ID, wheel hash, parent reference, and shim source.
Verification is an import and environment check, not execution evidence.

## Archive and convert to a SIF

Save the verified image as an archive with a hash sidecar on storage visible to
the Slurm nodes:

```bash
docker save local/hec-ras-wine-executor_6.6:review | gzip -1 \
  > /shared/images/hec-ras-wine-executor_6.6-review.tar.gz
(cd /shared/images && sha256sum hec-ras-wine-executor_6.6-review.tar.gz \
  > hec-ras-wine-executor_6.6-review.tar.gz.sha256)
```

Convert it with [build_sif_from_archive.sbatch](../apptainer/README.md) as an
unprivileged Slurm job. It checks the sidecar, builds the SIF in job scratch,
runs the default smoke command `python -m ras_commander.remote.execute_request
--help`, and publishes the SIF with `.sha256` and `.json` record sidecars
without overwriting anything. Use the published SIF SHA-256 in
`apptainer_image_sha256` and the request `container_identity`
(`sif:sha256:<hash>`).

## Apptainer runtime contract

- **Read-only SIF.** Run the SIF as published. The seed prefix inside it stays
  read-only; no `--writable`, `--writable-tmpfs`, or overlay is needed.
- **Private prefix per task.** `execute_request` copies the whole seed into a
  new `.ras-wine-runtime-<execution-id>-*` directory under the temporary
  directory (`TMPDIR`, else `/tmp`) and points `WINEPREFIX` at it. That directory
  must be node-local disk, outside the request bundle, with room for one full
  prefix per concurrent task; measure the prefix once with `du -sh`. Wine's
  registry and temporary writes go there, and the directory is removed when
  the task ends.
- **Virtual display.** The Windows step runs under `xvfb-run -n <display>`, so no
  display or X server is needed on the node. The executor probes Xvfb's abstract
  socket for a free display number, because contained steps have private `/tmp`
  directories and cannot see each other's lock files, while the abstract socket
  is shared through the host network namespace.
- **wineserver shutdown.** After Windows Python exits, the executor waits for
  the task-private `wineserver` (`wineserver -w`) and kills it if it does not
  exit within 30 seconds, before removing the prefix.
- **CPU sets.** The image preloads the CPU shim for Wine processes, so Slurm CPU
  sets that do not start at CPU 0 do not crash `RasProcess.exe`.
- **`--contain --cleanenv`.** `--cleanenv` drops the host environment; the
  image's `RAS_COMMANDER_WINE_*` variables still apply. Pass anything else with
  `--env`. With `--contain`, `/tmp` is no longer the host `/tmp`: bind a
  task-private node-scratch directory as `/tmp` (or pass `--workdir` on node
  scratch) so the prefix copy lands on disk, not in a small session
  directory.

A single task, outside `RasSlurm`, looks like this:

```bash
TASK_TMP=/scratch/$SLURM_JOB_ID/reach-001-tmp
mkdir -p "$TASK_TMP"
apptainer exec --contain --cleanenv --bind "$TASK_TMP:/tmp:rw" \
  --env "RAS_COMMANDER_RUNTIME_CONTAINER_IDENTITY=sif:sha256:$SIF_SHA256" \
  --bind "$BUNDLE:/job:ro" --bind "$BUNDLE/results:/job/results:rw" \
  hec-ras-wine-executor_6.6-review.sif \
  python -m ras_commander.remote.execute_request execute-request /job/request.json
```

`RasSlurm` renders the equivalent `srun ... apptainer exec --contain
--cleanenv` command, with the request bundle read-only, its output directory
writable, and a step-private node-scratch directory bound as `/tmp`.

## Docker

The same image runs requests under Docker:

```bash
docker run --rm --security-opt apparmor=unconfined \
  --mount type=bind,src="$BUNDLE",dst=/job,readonly \
  --mount type=bind,src="$BUNDLE/results",dst=/job/results \
  local/hec-ras-wine-executor_6.6:review \
  python -m ras_commander.remote.execute_request execute-request /job/request.json
```

The bundle must be readable and `results/` writable by UID 1000, or pass
`--user`. Omit the security option where the host allows Wine without it.

## Future work: daemon-free derivative build

A Docker daemon is not always available where SIFs are built. A derivative can
instead be built inside an existing executor SIF as a Slurm job: read the parent
`docker save` archive, write a new layer that replaces `ras_commander` in both
site-packages trees (OCI whiteouts for the old `dist-info` and an opaque
`ras_commander/` directory), append it to the archive's manifest and image
config, and publish the new archive with hash and record sidecars for
[build_sif_from_archive.sbatch](../apptainer/README.md). fim-commander uses this
pattern for its own images.

It is not provided here. Without network access or Wine at build time, the
layer can only unpack a pure-Python wheel into both trees. That suits only a
wheel refresh over an existing executor whose dependencies already match. It
cannot derive the first executor from a preprocessing image, whose Linux Python
has no ras-commander dependencies. A generic version also needs offline tests
of the layer and manifest rewriting against a real archive.
