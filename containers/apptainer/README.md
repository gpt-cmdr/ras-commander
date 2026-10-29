# Apptainer SIF images for ras-commander

Slurm execution through [RasApptainer](../../docs/user-guide/slurm-apptainer-execution.md)
and [RasSlurm](../../docs/user-guide/slurm-portable-execution.md) pins a SIF by
its SHA-256. This directory documents three ways to produce that SIF from an
OCI image, and provides [build_sif_from_archive.sbatch](build_sif_from_archive.sbatch)
for the archive route. A SIF hash differs from the registry digest of the image
it came from; record both.

| Route | Use when | Privilege |
|---|---|---|
| `apptainer pull docker://...@sha256:...` | the image is in a registry the build host can reach | unprivileged |
| `apptainer build x.sif docker-archive://x.tar` | you have a `docker save` archive; also works in unprivileged LXC containers | unprivileged, no fakeroot |
| `build_sif_from_archive.sbatch` | the archive route as a Slurm job, with hash checks and no-clobber publication | unprivileged Slurm job |

## Pull a published SIF

For routine jobs, use `RasContainerImages.resolve_sif()` to pull the published
ORAS artifact and verify its file SHA-256 against the packaged catalog. Native
and Wine executor SIFs are already published on GHCR; no local image build or
conversion is needed. See [Apptainer images](../../docs/user-guide/apptainer-images.md#use-a-local-or-cached-image).

The routes below cover custom builds and OCI-to-SIF conversion. A converted
SIF has its own file identity, separate from the published SIF and OCI digest.

## Pull from a registry by digest

Pull by digest, never by tag alone, so the SIF is reproducible:

```bash
export APPTAINER_TMPDIR=/scratch/$USER/apptainer-tmp APPTAINER_CACHEDIR=/scratch/$USER/apptainer-cache
mkdir -p "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"
apptainer pull hec-ras-linux-unsteady_6.6-converted.sif \
  docker://ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_6.6@sha256:219084e923d704a3209999fda7efdb42a731dcc632bd38c6fdabca00fc0a7ec0
sha256sum hec-ras-linux-unsteady_6.6-converted.sif > hec-ras-linux-unsteady_6.6-converted.sif.sha256
```

Registry digests for the published images are in the
[container catalog](../../docs/user-guide/container-images.md#immutable-registry-identities).
Put `APPTAINER_TMPDIR` on local disk with room for the unpacked image; the Wine
images are several gigabytes.

## Build from a docker-save archive

Where the build host has no registry access, or the image exists only in a
local Docker engine, save it and build from the archive:

```bash
docker save local/hec-ras-wine-executor_6.6:review -o hec-ras-wine-executor_6.6.tar
apptainer build hec-ras-wine-executor_6.6.sif docker-archive://hec-ras-wine-executor_6.6.tar
```

Building from an archive needs no root, `--fakeroot`, or user namespace
mapping, so it also works inside an unprivileged LXC container where fakeroot
is unavailable. `docker-archive://` does not read gzip: decompress a
`.tar.gz` first. If `docker-archive://` rejects an OCI-layout archive, use
`oci-archive://` with the same file.

## Convert an archive as a Slurm job

[build_sif_from_archive.sbatch](build_sif_from_archive.sbatch) wraps the archive
route. The account, partition, and log path are site choices passed to
`sbatch`; the script hardcodes none of them.

```bash
sbatch --account=<account> --partition=<partition> \
  --output=/shared/images/logs/sif-build-%j.out \
  --export=ALL,RAS_COMMANDER_SIF_NAME=hec-ras-wine-executor_6.6-20261013,RAS_COMMANDER_SIF_SRC=/shared/images/hec-ras-wine-executor_6.6-20261013.tar.gz,RAS_COMMANDER_SIF_DEST=/shared/images \
  containers/apptainer/build_sif_from_archive.sbatch
```

| Variable | Meaning |
|---|---|
| `RAS_COMMANDER_SIF_NAME` | Required. Safe basename (`[A-Za-z0-9][A-Za-z0-9._=-]*`, no `..`); the SIF is `<DEST>/<name>.sif`. |
| `RAS_COMMANDER_SIF_SRC` | Required. `docker save` archive, `.tar` or `.tar.gz`. |
| `RAS_COMMANDER_SIF_DEST` | Required. Existing, writable destination directory on shared storage. |
| `RAS_COMMANDER_SIF_SMOKE` | Optional. Command run with `/bin/sh -c` in the new SIF under `--contain --cleanenv`. Default: `python -m ras_commander.remote.execute_request --help`. |
| `RAS_COMMANDER_SIF_SCRATCH` | Optional. Node-local scratch root. Default: `/scratch/$SLURM_JOB_ID`. |

`sbatch --export` splits its argument at commas, so a smoke command passed
that way cannot contain one. The default smoke command suits a [portable Wine executor](../hecras-wine-executor/README.md).
For the [native unsteady image](../hecras-unsteady/README.md), check the engine
instead:

```bash
--export=ALL,...,RAS_COMMANDER_SIF_SMOKE='test -x /opt/hecras-runtime/engine/RasUnsteady && python -c "import ras_commander._container_compute"'
```

The job:

1. Rejects an unsafe name, a destination path that escapes `DEST`, and any
   existing `<name>.sif`, `.sif.sha256`, or `.sif.json`.
2. Hashes the archive and, when `<archive>.sha256` exists, requires a match.
3. Decompresses a `.tar.gz` into a private work directory under the scratch
   root, reads the image ID (Config digest) from the archive's `manifest.json`,
   and runs `apptainer build` from `docker-archive://`, falling back to
   `oci-archive://`. `APPTAINER_TMPDIR` and `APPTAINER_CACHEDIR` live in the
   same work directory.
4. Inspects the SIF and runs the smoke command; a failing smoke command fails
   the job (exit 7).
5. Copies the SIF to `<name>.sif.partial-<job>` in `DEST`, re-hashes the copy,
   writes the hash and record sidecars, and publishes the three files with
   no-clobber renames. The published SIF is hashed once more and checked with
   `sha256sum -c`.
6. Removes partial and already-renamed files on any failure, and always removes
   its scratch work directory.

Exit codes: 2 invalid input or refusal to overwrite, 3 scratch setup, 4 copy,
5 hash mismatch, 6 rename failure, 7 smoke failure; a failing `apptainer build`
returns its own code.

### Record sidecar

`<name>.sif.json` uses schema `ras-commander-sif-record/v1`:

| Field | Value |
|---|---|
| `sif`, `sif_sha256` | published file name and SHA-256 (the value for `apptainer_image_sha256` and `sif:sha256:<hash>` identities) |
| `image_id` | `sha256:` Config digest from the archive's `manifest.json`, or `null` when the archive has none |
| `source_archive`, `source_archive_sha256` | absolute archive path and its SHA-256 |
| `smoke_command` | the command that passed |
| `slurm_job_id`, `build_host`, `apptainer_version`, `built_at` | build provenance |

A successful conversion and smoke command are not execution evidence. Qualify
a new SIF with a real model through the API that will use it.
