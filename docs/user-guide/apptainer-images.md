# Apptainer images for Slurm

Slurm execution uses Apptainer SIF files on shared storage. Three image roles
cover the HEC-RAS workflow; each is built or published as an OCI image and
converted to a SIF once, then pinned by its SHA-256.

| Role | Image | Used by | Recipe |
| --- | --- | --- | --- |
| Native Linux unsteady solver | `rascommander/hec-ras-linux-unsteady_<version>:v1` | [`RasApptainer.render_job`](slurm-apptainer-execution.md) | [`containers/hecras-unsteady`][native] |
| Wine preprocessing (Docker workflow) | `rascommander/hec-ras-wine-precompute_<version>:v4` | [`RasDocker.preprocess_plan`](container-execution.md) | [`containers/hecras-wine-precompute`][precompute] |
| Wine portable executor | Derived from the pre-compute image | [`RasSlurm`](slurm-portable-execution.md), [`RasApptainer.render_prepare_job`](slurm-apptainer-execution.md#wine-preparation-on-the-cluster), `RasPortableDocker` | [`containers/hecras-wine-executor`][executor] |

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
| 5.0–5.0.6, 6.0 | Applies; accept the terms [in each task](#hec-ras-terms-and-conditions) | Not applicable: HEC published no Linux engine |
| 5.0.7 | Applies; accept the terms in each task | Applies: Linux engine uses the `bin_ras` layout (`rasUnsteady64` plus the `.c##` computed geometry; see [HEC-RAS 5.0.7](slurm-apptainer-execution.md#hec-ras-507-bin_ras-layout)) |
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

**Pull by digest.** On a node with registry access, pull once to shared storage
and record the SIF hash:

```bash
apptainer pull /shared/images/hec-ras-linux-unsteady_6.6-v1.sif \
  docker://rascommander/hec-ras-linux-unsteady_6.6@sha256:71dec03350996cfa8a0ccb18ae08075de9b9cc3d7fb6b1dddbf541c030abb95c
sha256sum /shared/images/hec-ras-linux-unsteady_6.6-v1.sif
```

**Convert a `docker save` archive.** For locally built images (such as the
executor) or clusters without registry access, save the image with a hash
sidecar and convert it with [`build_sif_from_archive.sbatch`][sifbuilder] as an
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
   shared base prefix, installs the wheel into Windows Python, accepts the
   [terms](#hec-ras-terms-and-conditions) through HEC-RAS's own dialog, and writes
   `runtime.json` with SHA-256 records for Python, the wheel, `Ras.exe`, the terms record, and the
   installer. 7.x combined installers install nothing silently; extract their MSI first with
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

## HEC-RAS terms and conditions

HEC-RAS asks the user to accept its Terms and Conditions for Use (TCU) before it computes; under
Wine an unanswered dialog would hold a job until its time limit. Acceptance is always given
through HEC-RAS's own dialog, by the operator who runs the build or sets the option below, and is
verified by relaunching HEC-RAS; ras-commander never writes acceptance state itself.

- **6.1 and later** record acceptance in the Wine prefix. The profile build accepts once
  (`accept_tcu.py`) and every task's private copy of the prefix inherits it. Building the image
  means accepting HEC's terms for its users; publish such an image only if that is acceptable.
- **6.0 and earlier** (including 5.0.7) record acceptance per machine, so a copied prefix does
  not carry it. Set `RAS_COMMANDER_WINE_ACCEPT_TCU=1` to have each task accept the terms in its
  own prefix before computing; under Apptainer pass it as
  `APPTAINERENV_RAS_COMMANDER_WINE_ACCEPT_TCU=1` in the site or profile `environment`. Setting it
  is your acceptance of the [HEC-RAS terms](https://www.hec.usace.army.mil/software/hec-ras/).
  Without it the executor and prepare job refuse to start HEC-RAS and say why.

## Wine executor image

[`build_executor_image.sh`][executor] derives the executor from a pre-compute image:
a digest-pinned `rascommander/hec-ras-wine-precompute_<version>` (6.5, 6.6, or 7.0.1) or a
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
  rascommander/hec-ras-wine-precompute_6.6@sha256:5fbc07a20693cb867578048be632d88cee02618780259c1c7ddc258c9fbb4318 \
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

The published pre-compute `v4` images do not contain the shim; the executor
build compiles it when the base lacks it. The `v5` pre-compute images built by
`build_release_images.sh` bake it in.

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
| 6.0 | Passed (terms accepted per task) | No Linux engine | — | — |
| 5.0.7 | Passed (terms accepted per task) | Passed, 74 s | 0.012 ft | 0.0001 ft |
| 5.0.6, 5.0.5, 5.0.4, 5.0.3, 5.0.1, 5.0 | Passed (terms accepted per task) | No Linux engine | — | — |

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

That is one example project per release. Build and convert the images, then run one
representative model end to end on your cluster before a campaign. A successful job is
computational evidence, not engineering approval.

[native]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-unsteady/README.md
[precompute]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-precompute/README.md
[executor]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-executor/README.md
[sifbuilder]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/apptainer/README.md
[shim]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-precompute/cpushim.c
[runtime]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-runtime
