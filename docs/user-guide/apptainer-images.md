# Apptainer images for Slurm

Slurm execution uses Apptainer SIF files on shared storage. Three image roles
cover the HEC-RAS workflow; each is built or published as an OCI image and
converted to a SIF once, then pinned by its SHA-256.

| Role | Image | Used by | Recipe |
| --- | --- | --- | --- |
| Native Linux unsteady solver | `ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_<version>:0.106.0` | [`RasApptainer.render_job`](slurm-apptainer-execution.md) | [`containers/hecras-unsteady`][native] |
| Wine preprocessing (Docker workflow) | `ghcr.io/gpt-cmdr/hec-ras-wine-precompute_<version>:0.106.0` | [`RasDocker.preprocess_plan`](container-execution.md) | [`containers/hecras-wine-precompute`][precompute] |
| Wine portable executor | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_<version>:0.106.0` | [`RasSlurm`](slurm-portable-execution.md), [`RasApptainer.render_prepare_job`](slurm-apptainer-execution.md#wine-preparation-on-the-cluster), `RasPortableDocker` | [`containers/hecras-wine-executor`][executor] |

Qualified images for every supported release are published at `ghcr.io/gpt-cmdr`: OCI images
as `hec-ras-<role>_<version>` and byte-identical SIFs (ORAS) as `hec-ras-<role>-sif_<version>`,
tag `0.106.0`. The packaged catalog pins each by digest and records the SIF's SHA-256, so
`resolve_sif()` and `ensure_sif_command()` pull the published SIF and verify it.

The pre-compute image is a Docker controller with its own entry point; under
Apptainer, use the executor derived from it. The [container catalog](container-images.md)
lists published registry digests. A registry digest and a SIF SHA-256 are
different identities: jobs verify the SIF bytes.

## Which images apply to which HEC-RAS release

| HEC-RAS | Full Windows compute under Wine (`wine-executor`; `RasSlurm`) | Wine preprocessing → native Linux solve (`wine-precompute` + `linux-unsteady`; `RasDocker`, `RasApptainer`) |
| --- | --- | --- |
| 5.0–5.0.6, 6.0 | Applies ([one setting](#hec-ras-60-and-earlier)) | Not applicable: HEC published no Linux engine |
| 5.0.7 | Applies ([one setting](#hec-ras-60-and-earlier)) | Applies: Linux engine uses the `bin_ras` layout (`rasUnsteady64` plus the `.c##` computed geometry; see [HEC-RAS 5.0.7](slurm-apptainer-execution.md#hec-ras-507-bin_ras-layout)) |
| 6.1 | Applies | Applies: canonical `RasUnsteady` + `libs/` layout with the pre-6.3.1 solver arguments (`RasUnsteady <project>.c## b##`; see [solver argument conventions](slurm-apptainer-execution.md#solver-argument-conventions-by-release)) |
| 6.2, 6.3, 6.3.1, 6.4.1 | Applies | Not applicable: HEC published no Linux engine |
| 6.5, 6.6, 7.x | Applies | Applies |

HEC-RAS 4.x is not supported in containers: it has no command-line compute and runs only
through its COM interface on Windows (see the [legacy COM interface](legacy-com-interface.md)).

`RasContainerImages.applicable_roles(version)` returns the same answer in code.
An applicable role still needs an image built for that release:
[`build_release_images.sh`](#build-wine-images-for-a-release) builds the Wine images for any
install-folder version (`5.0`, `5.0.7`, `6.3.1`, `6.6`, `7.0.1`, …) from HEC's official
installer, and the [native recipe][native] builds the Linux engine image from HEC's Linux
distribution. Published images are listed in the packaged catalog
(`RasContainerImages.catalog()`) and in the [container catalog](container-images.md).

## Use a local or cached image

Jobs always run a SIF on shared storage that is verified by its SHA-256.
`RasContainerImages.resolve_sif` picks it, in this order:

1. **Your own image** — `sif_path=` (a site-built or locally cached SIF), used
   as-is after hashing; pass `expected_sha256=` to pin it.
2. **The cache** — `cache_dir=`, else `$RAS_COMMANDER_IMAGE_CACHE`, else
   `~/.cache/ras-commander/images`. Files are named by registry digest and
   re-verified on every use (against the published SIF hash, or the `.sha256`
   sidecar recorded when the file was pulled).
3. **The registry** — pulled into the cache only if `pull` allows: `"never"`
   (offline; fail if not cached), `"missing"` (default), or `"always"`.

```python
from ras_commander import RasContainerImages
from ras_commander.RasSlurm import SlurmSiteConfig

native = RasContainerImages.resolve_sif(
    "linux-unsteady", "6.6", cache_dir="/shared/ras-images", pull="never",
)
executor = RasContainerImages.resolve_sif(
    "wine-executor", "5.0.6", sif_path="/shared/ras-images/hec-ras-wine-executor_5.0.6.sif",
)
site = SlurmSiteConfig(
    site_name="example", apptainer_image=str(executor.path),
    apptainer_image_sha256=executor.sha256, container_identity=executor.container_identity,
)
```

When you submit from a workstation over SSH, fill the cluster's shared cache
from its login host, or from a short job, instead. `ensure_sif_command` returns an idempotent bash
snippet that reuses a verified copy or pulls one, and prints `<sha256>  <path>`:

```python
from ras_commander import RasApptainer, RasContainerImages, SshApptainerTransport

command = RasContainerImages.ensure_sif_command("linux-unsteady", "6.6", "/shared/ras-images")
result = SshApptainerTransport(profile).run(["bash", "-c", command])
sha256, path = result.stdout.split()
```

Pass `work_dir=` (for example `/scratch/$SLURM_JOB_ID/apptainer-work`) to unpack
image layers on node-local disk when the cache is on network storage; it defaults
to `<cache>/.apptainer-work`. Point the cache at storage that compute nodes can
read so one copy serves every job. Cache entries are never overwritten in place; a new release has a new
digest and a new file.

## Get a SIF manually

For routine use, prefer `resolve_sif()` above: it pulls the published ORAS SIF
and checks its recorded file hash. For example, the published 6.6 executor is:

```bash
apptainer pull /shared/images/hec-ras-wine-executor_6.6.sif \
  oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_6.6@sha256:77cee520c1c0e25afe9eeb5d5a59a4fae44198ab27db55ddf3d20c62f0a02212
echo '7d5eaf7f2b1512dab7547430ed3ef20025f7ac9c247a5c3776f3fbb88aed1481  /shared/images/hec-ras-wine-executor_6.6.sif' | sha256sum -c -
```

The conversion routes below are for OCI images or local builds when a published
SIF is not being used. Conversion creates a new SIF identity; do not substitute
its hash for the published file hash.

**Convert an OCI image by digest.** On a node with registry access, pull once to shared storage
and record the SIF hash:

```bash
apptainer pull /shared/images/hec-ras-linux-unsteady_6.6-converted.sif \
  docker://ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_6.6@sha256:219084e923d704a3209999fda7efdb42a731dcc632bd38c6fdabca00fc0a7ec0
sha256sum /shared/images/hec-ras-linux-unsteady_6.6-converted.sif
```

**Convert a `docker save` archive.** For locally built images or clusters without
registry access, save the image with a hash sidecar and convert it with
[`build_sif_from_archive.sbatch`][sifbuilder] as an
ordinary unprivileged Slurm job:

```bash
sbatch --account=<account> --partition=<partition> \
  --export=ALL,RAS_COMMANDER_SIF_NAME=hec-ras-wine-executor_6.6-r1,RAS_COMMANDER_SIF_SRC=/shared/images/hec-ras-wine-executor_6.6-r1.tar.gz,RAS_COMMANDER_SIF_DEST=/shared/images \
  containers/apptainer/build_sif_from_archive.sbatch
```

The job checks the archive against its `.sha256` sidecar, decompresses it
(Apptainer's `docker-archive://` reader cannot read gzip), builds in job
scratch with `docker-archive://` and falls back to `oci-archive://`, runs a
smoke command inside the new SIF, and publishes `<name>.sif`,
`<name>.sif.sha256`, and a `<name>.sif.json` record (`ras-commander-sif-record/v1`,
binding the SIF digest to the OCI image ID and source archive). It never
overwrites a file and removes partial output on failure. It needs no Docker
daemon, `--fakeroot`, or privileged container, which also suits unprivileged
LXC compute nodes.

Put the SIF hash in the site configuration (`apptainer_image_sha256`,
`prepare_image_sha256`) and `sif:sha256:<hash>` in `container_identity`.
Never pull or convert per job.

## Build Wine images for a release

[`containers/hecras-wine-runtime/build_release_images.sh`][runtime] builds the Wine images for
one HEC-RAS release from its official installer on a Linux Docker host:

```bash
CI=1 python -m pip wheel --no-deps --wheel-dir /tmp/rc-wheel .
bash containers/hecras-wine-runtime/build_base.sh            # once: Wine 11, .NET 4.8, Windows Python 3.11
RAS_COMMANDER_COMMIT=$(git rev-parse HEAD) \
bash containers/hecras-wine-runtime/build_release_images.sh 5.0.7 HEC-RAS_507_Setup.exe \
  /tmp/rc-wheel/ras_commander-<version>-py3-none-any.whl work/ archives/
```

1. **Runtime profile** (`build_runtime_profile.sh`): installs the release into a copy of the
   shared base prefix, installs the wheel into Windows Python, and writes `runtime.json` with
   SHA-256 records for Python, the wheel, `Ras.exe`, and the installer. 7.x combined installers install nothing silently; extract their MSI first with
   [`extract_installer.py`][native] and pass it as `HECRAS_MSI=<file.msi>`.
2. **Pre-compute image** (`hec-ras-wine-precompute_<version>:v5-<commit>`): the bundled runtime,
   the [CPU shim](#cpu-numbering-shim), and the `RasDocker` controller.
3. **Executor image** (`hec-ras-wine-executor_<version>:<commit>`), derived from step 2 as
   described [below](#wine-executor-image).
4. `docker save` archives with `.sha256` and `.image-id` sidecars for
   [conversion to SIF](#get-a-sif-manually). The pre-compute archive is kept only for releases
   with a Linux engine. The release's example projects are exported beside them as
   `hec-ras-examples_<version>_<commit>.tar.gz` (test data, not part of any image).

Each release needs about 20 GB free on the Docker host while it builds; the script removes its
images and BuildKit cache when done unless `KEEP_IMAGES=1`.

## HEC-RAS 6.0 and earlier

For 6.0 and earlier (including 5.0.7), set `RAS_COMMANDER_WINE_ACCEPT_TCU=1` in each task;
under Apptainer pass it as `APPTAINERENV_RAS_COMMANDER_WINE_ACCEPT_TCU=1` in the site or
profile `environment`. Without it the executor and prepare job stop with an explanation.

## Wine executor image

[`build_executor_image.sh`][executor] derives the executor from a pre-compute image:
a digest-pinned GHCR preprocessing image or a
locally built one passed by image ID, as `build_release_images.sh` does. It installs one ras-commander wheel into both the Linux Python
(with the `compute` extra) and the Windows `C:\Python311` in the Wine prefix,
adds the GDAL bridge `C:\Python311\GDAL` → `HEC-RAS\<version>\GDAL` that
RasMapper calls need (when the release ships that folder), installs the [CPU shim](#cpu-numbering-shim), and sets
the executor environment:

| Variable | Value |
| --- | --- |
| `RAS_COMMANDER_WINE_PREFIX_SEED` | `/runtime/wine-seed/prefix` |
| `RAS_COMMANDER_WINE_PYTHON` | `C:\Python311\python.exe` |
| `RAS_COMMANDER_WINE_ARCH` | `win64` |
| `RAS_COMMANDER_WINE_CPU_SHIM` | `/opt/ras-commander-executor/cpushim.so` |

```bash
CI=1 python -m pip wheel --no-deps --wheel-dir /tmp/rc-wheel .
RAS_COMMANDER_COMMIT=$(git rev-parse HEAD) \
bash containers/hecras-wine-executor/build_executor_image.sh 6.6 \
  ghcr.io/gpt-cmdr/hec-ras-wine-precompute_6.6@sha256:1eef40777dd4a1c99a18a1a6b9ce5524ea163b45133901dbe5d38895fef99c11 \
  /tmp/rc-wheel/ras_commander-<version>-py3-none-any.whl \
  local/hec-ras-wine-executor_6.6:r1
docker save local/hec-ras-wine-executor_6.6:r1 | gzip -1 > /shared/images/hec-ras-wine-executor_6.6-r1.tar.gz
```

The build runs on a Linux Docker host (BuildKit cannot run Wine, so the script
runs and commits one container). It labels the image with the wheel hash,
source commit, and parent digest, then verifies both Pythons import the same
ras-commander version from a fresh prefix copy with networking disabled.
That verification is an import check, not execution evidence. The script runs
on a build host, not a compute node; convert the archive as above.

### Runtime contract under Apptainer

- The SIF stays **read-only**. No `--writable`, `--writable-tmpfs`, or overlay.
- Each task copies the baked prefix into its own directory under `/tmp`, which
  must be a **node-scratch bind** because `--contain` replaces the host `/tmp`
  with a small session directory. `RasSlurm` and `render_prepare_job` bind a
  per-step node-scratch directory as `/tmp` automatically.
- Windows steps run under `xvfb-run -n <display>` with a display number
  probed free on the node, because contained steps cannot see each other's
  `/tmp` lock files; no display is needed.
- The task-private `wineserver` is awaited (and killed if it does not exit)
  before the prefix is removed.
- `--cleanenv` drops the host environment; the image's `RAS_COMMANDER_WINE_*`
  variables still apply.

## CPU-numbering shim

In a Slurm or cgroup CPU set that does not start at CPU 0 (for example CPUs
4–5), Wine reports two processors but returns the raw host CPU ids as the
Windows processor number. The .NET runtime used by `RasProcess.exe` indexes
per-processor state with that number, and HEC-RAS preprocessing fails
intermittently with `0xC0000005` in `clr.dll`. In CLB testing, 6 of 12 runs
crashed without a fix and 0 of 24 with it.

[`cpushim.c`][shim] is an `LD_PRELOAD` library that maps `sched_getcpu()` to
the CPU's index within the process affinity mask. The executor and
`apptainer_prepare` preload it for the Wine launch (`xvfb-run`, Xvfb,
`wineserver`, and the Wine processes; CPUs outside the mask pass through
unchanged) when `RAS_COMMANDER_WINE_CPU_SHIM` names it; an empty or `0` value disables it, and
a value that is not a regular absolute file fails before any Wine state is
created. Both also disable the Wine debugger so a crash exits instead of
waiting for input.

The historical Docker Hub pre-compute `v4` images do not contain the shim; the executor
build compiles it when the base lacks it. The `v5` pre-compute images built by
`build_release_images.sh` bake it in, including the published GHCR `0.106.0` images.

The executor and prepare job also set `KMP_AFFINITY=disabled` unless it is already set:
HEC-RAS 7.0's OpenMP runtime otherwise aborts under Wine with `OMP: Error #179`.

## Qualification status

Live qualification on October 13–14, 2026 (ras-commander PRs #525/#528, Apptainer 1.5.4, Slurm
partition `clb`). For every release, the executor was built by `build_release_images.sh` from
HEC's official installer, converted with `build_sif_from_archive.sbatch`, and run as a `RasSlurm`
job array computing the release's own Muncie example, plans 01 (1D) and 03 (2D), under Wine with
validated receipts (solver verified, volume accounting and inflow reconciliation passed). Where a
Linux engine exists, `render_prepare_job` prepared plan 03 under Wine in the executor SIF and
`render_job` solved it with the native SIF on 2 cores; the table compares the native water surface
with the Wine result over computational cells.

| HEC-RAS | Wine compute, plans 01 + 03 | Native solve, plan 03 | Max WSE difference, any time step | Max-WSE map difference |
| --- | --- | --- | --- | --- |
| 7.0.1 | Passed | Passed, 30 s | 0.010 ft | 0.0001 ft |
| 7.0 | Passed | Passed, 32 s | 0.008 ft | 0.0005 ft |
| 6.6 | Passed | Passed, 24 s | 0.010 ft | 0.0001 ft |
| 6.5 | Passed | Passed, 25 s | 0.011 ft | 0.0001 ft |
| 6.4.1, 6.3.1, 6.3, 6.2 | Passed | No Linux engine | — | — |
| 6.1 | Passed | Passed, 40 s | 0.009 ft | 0.0001 ft |
| 6.0 | Passed | No Linux engine | — | — |
| 5.0.7 | Passed | Passed, 74 s | 0.012 ft | 0.0001 ft |
| 5.0.6, 5.0.5, 5.0.4, 5.0.3, 5.0.1, 5.0 | Passed | No Linux engine | — | — |

### Gridded precipitation

BaldEagleCrkMulti2D plan 06 ("Gridded Precip - Infiltration", HEC's example from 6.0 on) was
run with two precipitation sources: the bundled NEXRAD DSS grid (run window 2018-09-09
18:00-19:20), and three synthetic hourly GeoTIFF frames imported with
`RasUnsteady.set_gridded_precipitation_geotiff` (ras-commander writes the NetCDF and the
"Imported Raster Data" payload HEC-RAS's GUI import would write). The check is the cumulative
precipitation depth that reached the mesh.

| HEC-RAS | DSS grid, Wine | DSS grid, native | GeoTIFF, Wine | GeoTIFF, native |
| --- | --- | --- | --- | --- |
| 7.0.1, 7.0, 6.6, 6.5 | Passed, 0.11454 in | Passed, identical | Passed, 0.11575 in | Passed, identical |
| 6.4.1, 6.3.1, 6.3, 6.2 | Passed, 0.11454 in | No Linux engine | Passed, 0.11575 in | No Linux engine |
| 6.1 | Passed, 0.11454 in | Passed, identical | Passed, 0.10978 in | Passed, identical |
| 6.0 | Passed, 0.11454 in | No Linux engine | Passed, 0.10978 in | No Linux engine |

The DSS results match the Windows reference for this window; the GeoTIFF results for 6.2 and
later match the Windows/Wine 6.6 reference. 6.0 and 6.1 map the same raster to the mesh
differently (identically under Wine and natively), so compare raster results within a release.
A plan whose `.u##` names a GDAL raster without the imported payload fails in every release
(`Expected precip dataset ... Imported Raster Data/Values does not exist`): HEC-RAS reads GDAL
rasters only in its GUI import, so import them with ras-commander. HEC-RAS 5.x has no gridded
meteorology.

`RasDocker` with the final images ran Muncie plan 03 end to end (Wine preparation, native
solve) for 7.0.1, 7.0, 6.6, 6.5, 6.1, and 5.0.7, and the DSS case for 7.0.1, 7.0, 6.6, 6.5,
and 6.1, with the same cumulative precipitation. The SIFs in the packaged catalog are the
exact files of the final Slurm requalification (2026-10-15): for every Linux-engine release,
Muncie plans 01/03 under Wine and natively, and the DSS case under Wine and natively. Hosts whose Docker AppArmor profile denies Wine's sockets need
`apparmor_profile="unconfined"`.

Notes:

- The differences are between engines (Windows under Wine on 1 core, Linux on 2 cores), not
  run-to-run noise. 7.x writes engine-specific placeholder values in trailing boundary cells, so
  compare computational cells only (`Geometry/2D Flow Areas/Attributes` `Cell Count`).
- HEC-RAS 5.x writes volume accounting as `Vol Accounting …` attributes on
  `Results/Unsteady/Summary` rather than a `Volume Accounting` group; receipts validate either.
- The 6.6 executor was also run in pool mode with identical results, and 436 steady 6.6 requests
  ran earlier through `RasSlurm` (see [Portable execution on Slurm](slurm-portable-execution.md)).
- Each Wine step's memory peak reached about 6 GiB (cgroup accounting, including the private
  prefix copy and file cache); budget `slurm_memory` at 6–8 GiB per Wine request and measure on
  your models. TACC was not run.

The Muncie checks cover one example project per release; the precipitation checks
add the BaldEagle example. Pull the published SIFs (or build and qualify custom
images), then run one representative model end to end on your cluster before a
campaign. A successful job is computational evidence, not engineering approval.

[native]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-unsteady/README.md
[precompute]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-precompute/README.md
[executor]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-executor/README.md
[sifbuilder]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/apptainer/README.md
[shim]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-precompute/cpushim.c
[runtime]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-runtime
