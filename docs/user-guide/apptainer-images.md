# Apptainer images for Slurm

Slurm execution uses Apptainer SIF files on shared storage. Three image roles
cover the HEC-RAS workflow; each is built or published as an OCI image and
converted to a SIF once, then pinned by its SHA-256.

| Role | Image | Used by | Recipe |
| --- | --- | --- | --- |
| Native Linux unsteady solver | `rascommander/hec-ras-linux-unsteady_<version>:v1` | [`RasApptainer.render_job`](slurm-apptainer-execution.md) | [`containers/hecras-unsteady`][native] |
| Wine preprocessing (Docker workflow) | `rascommander/hec-ras-wine-precompute_<version>:v4` | [`RasDocker.preprocess_plan`](container-execution.md) | [`containers/hecras-wine-precompute`][precompute] |
| Wine portable executor | Derived from the pre-compute image | [`RasSlurm`](slurm-portable-execution.md), [`RasApptainer.render_prepare_job`](slurm-apptainer-execution.md#wine-preparation-on-the-cluster), `RasPortableDocker` | [`containers/hecras-wine-executor`][executor] |

The pre-compute image is a Docker controller with its own entry point; under
Apptainer, use the executor derived from it. The [container catalog](container-images.md)
lists published registry digests. A registry digest and a SIF SHA-256 are
different identities: jobs verify the SIF bytes.

## Which images apply to which HEC-RAS release

| HEC-RAS | Full Windows compute under Wine (`wine-executor`; `RasSlurm`) | Wine preprocessing → native Linux solve (`wine-precompute` + `linux-unsteady`; `RasDocker`, `RasApptainer`) |
| --- | --- | --- |
| 4.0, 4.1, 5.0–5.0.6, 6.0 | Applies | Not applicable: HEC published no Linux engine |
| 5.0.7 | Applies | Applies: Linux engine uses the `bin_ras` layout (`rasUnsteady64` plus the `.c##` computed geometry); supported by `RasCmdr.compute_plan_linux` and `RasApptainer` (see [HEC-RAS 5.0.7](slurm-apptainer-execution.md#hec-ras-507-bin_ras-layout)); no published native image yet |
| 6.1 – 7.x | Applies | Applies |

`RasContainerImages.applicable_roles(version)` returns the same answer in code.
An applicable role still needs an image built for that release: the recipes
take any install-folder version (`4.1.0`, `5.0.7`, `6.3.1`, `6.6`, `7.0.1`, …),
but a Wine image needs a prepared Windows HEC-RAS profile of that release (see
the [pre-compute preparation guide][precompute]). Published images are listed
in the packaged catalog (`RasContainerImages.catalog()`) and in the
[container catalog](container-images.md).

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
    "wine-executor", "4.1", sif_path="/shared/ras-images/hec-ras-wine-executor_4.1.0.sif",
)
site = SlurmSiteConfig(
    site_name="example", apptainer_image=str(executor.path),
    apptainer_image_sha256=executor.sha256, container_identity=executor.container_identity,
)
```

When you submit from a workstation over SSH, fill the cluster's shared cache
from its login host instead. `ensure_sif_command` returns an idempotent bash
snippet that reuses a verified copy or pulls one, and prints `<sha256>  <path>`:

```python
from ras_commander import RasApptainer, RasContainerImages, SshApptainerTransport

command = RasContainerImages.ensure_sif_command("linux-unsteady", "6.6", "/shared/ras-images")
result = SshApptainerTransport(profile).run(["bash", "-c", command])
sha256, path = result.stdout.split()
```

Point the cache at storage that compute nodes can read so one copy serves every
job. Cache entries are never overwritten in place; a new release has a new
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

## Wine executor image

[`build_executor_image.sh`][executor] derives the executor from a
digest-pinned `rascommander/hec-ras-wine-precompute_<version>` image (6.5, 6.6,
or 7.0.1). It installs one ras-commander wheel into both the Linux Python
(with the `compute` extra) and the Windows `C:\Python311` in the Wine prefix,
adds the GDAL bridge `C:\Python311\GDAL` → `HEC-RAS\<version>\GDAL` that
RasMapper calls need, installs the [CPU shim](#cpu-numbering-shim), and sets
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
build compiles it when the base lacks it. The successor pre-compute recipe
(`v5`) bakes it in and must be rebuilt and requalified before publication.

## Qualification status

Live qualification on October 13, 2026 (ras-commander PR #525, Apptainer 1.5.4, partition `clb`): an executor built from this recipe on `rascommander/hec-ras-wine-precompute_6.6@sha256:5fbc07a2…` (7.37 GB image, SIF `98c88cee…`) and the published native 6.6 `v1` SIF (`428385b9…`), both converted with `build_sif_from_archive.sbatch`:

| Run | Result |
| --- | --- |
| `RasSlurm` pool, 2 slots, Muncie plans 01 (1D) and 03 (2D) under Wine | Both steps `COMPLETED 0:0` on one node, receipts validated, collection succeeded |
| `RasSlurm` job array, throttle 2, same requests | Two array tasks, each one `rc-###` step, `COMPLETED 0:0`; results identical to the pool run |
| `RasApptainer.render_prepare_job` → `collect_prepare`, plan 03 | Wine preprocessing in 34 s with the CPU shim; prepared project verified |
| `RasApptainer.render_job` → `collect` on the prepared project, published native SIF | 2 cores, 33 s; results populated to the planned end time |
| Wine (1 core) vs native (2 cores) water surface, plan 03 | Max difference 0.0031 ft at any time step; maximum-WSE map within 0.0001 ft |

Each Wine step's memory peak reached about 6 GiB (cgroup accounting, including
the private prefix copy and file cache); budget `slurm_memory` at 6–8 GiB per
Wine request and measure on your models. The 6.5 and 7.0.1 executors, the
shim-bearing pre-compute `v5`, and TACC were not run. Build and convert the
images, then run one representative model end to end on your cluster before a
campaign. A successful job is computational evidence, not engineering
approval.

[native]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-unsteady/README.md
[precompute]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-precompute/README.md
[executor]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-executor/README.md
[sifbuilder]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/apptainer/README.md
[shim]: https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-wine-precompute/cpushim.c
