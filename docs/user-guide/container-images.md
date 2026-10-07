# Docker Hub container catalog

The public `rascommander` images supply two matching stages: Windows HEC-RAS
preprocessing under Wine, followed by native Linux unsteady computation.
Use them through [RasDocker](container-execution.md). The images include their
runtime; the host does not need a separate HEC-RAS or Wine installation.

## Published images

Registry metadata checked **October 7, 2026**. All six repositories are public
and list `linux/amd64` payloads. Wine `v4` and native `v1` have matching `latest`
tags at this check. Use an explicit version pair for ordinary runs and a digest
for a retained reproducible runtime selection. Tags may change.

| HEC-RAS | Wine preprocessing | Native Linux unsteady |
| --- | --- | --- |
| 6.5 | [`rascommander/hec-ras-wine-precompute_6.5:v4`](https://hub.docker.com/r/rascommander/hec-ras-wine-precompute_6.5) | [`rascommander/hec-ras-linux-unsteady_6.5:v1`](https://hub.docker.com/r/rascommander/hec-ras-linux-unsteady_6.5) |
| 6.6 | [`rascommander/hec-ras-wine-precompute_6.6:v4`](https://hub.docker.com/r/rascommander/hec-ras-wine-precompute_6.6) | [`rascommander/hec-ras-linux-unsteady_6.6:v1`](https://hub.docker.com/r/rascommander/hec-ras-linux-unsteady_6.6) |
| 7.0.1 | [`rascommander/hec-ras-wine-precompute_7.0.1:v4`](https://hub.docker.com/r/rascommander/hec-ras-wine-precompute_7.0.1) | [`rascommander/hec-ras-linux-unsteady_7.0.1:v1`](https://hub.docker.com/r/rascommander/hec-ras-linux-unsteady_7.0.1) |

### Immutable registry identities

These registry digests agree with the retained September 12 publication record.
They identify OCI payloads, not the SHA-256 of an Apptainer SIF produced from them.

| Repository and tag | Registry digest |
| --- | --- |
| `rascommander/hec-ras-wine-precompute_6.5:v4` | `sha256:5de3b51455e7405ea0f85f1d9112c8232e41faaad74a4c13bd511fad8c8eda99` |
| `rascommander/hec-ras-wine-precompute_6.6:v4` | `sha256:5fbc07a20693cb867578048be632d88cee02618780259c1c7ddc258c9fbb4318` |
| `rascommander/hec-ras-wine-precompute_7.0.1:v4` | `sha256:f53db7bd9e256f203e07fee77a624aef3fe33ba23e04f94e2e3a9afc62f4359d` |
| `rascommander/hec-ras-linux-unsteady_6.5:v1` | `sha256:944c6b4a5d2a0eca7cd8c381e614a25cb4f03a559e3a082c6de66c38fbd363c8` |
| `rascommander/hec-ras-linux-unsteady_6.6:v1` | `sha256:71dec03350996cfa8a0ccb18ae08075de9b9cc3d7fb6b1dddbf541c030abb95c` |
| `rascommander/hec-ras-linux-unsteady_7.0.1:v1` | `sha256:038475b5669ff45b2087fba0370321e89696f1c1d526123dfad24c4334ee1ed9` |

For example, retain the HEC-RAS 6.6 native payload by digest:

```bash
docker pull rascommander/hec-ras-linux-unsteady_6.6@sha256:71dec03350996cfa8a0ccb18ae08075de9b9cc3d7fb6b1dddbf541c030abb95c
```

Pass that full reference as `image=` to `RasDocker.compute_plan`, together with
`version="6.6"` and the matching preparation receipt. For Apptainer, prepend
`docker://` when pulling, then compute the resulting SIF's SHA-256 separately.
Use that SIF hash in `apptainer_image_sha256`. See the
[Slurm image setup](slurm-apptainer-execution.md#canonical-image-and-pulling-it-once).
The images contain x86-64 binaries; ARM execution is outside the qualified scope.

## Sources and host compatibility

| Component | Embedded or qualified source |
| --- | --- |
| Native image and installed library | [`604704d440c49a39d6f6e8bae262e2233d895dd0`](https://github.com/gpt-cmdr/ras-commander/tree/604704d440c49a39d6f6e8bae262e2233d895dd0) |
| Wine controller | [`dc60b219091e85bcb4564eca45313475c39ce58a`](https://github.com/gpt-cmdr/ras2fim-2d/tree/dc60b219091e85bcb4564eca45313475c39ce58a) |
| Windows library in the Wine profile | Version 0.99.2 wheel, source [`9e4217713e954236b0c16023e1815c6f2b7a5309`](https://github.com/gpt-cmdr/ras-commander/tree/9e4217713e954236b0c16023e1815c6f2b7a5309) |
| Linux qualification host API | `604704d440c49a39d6f6e8bae262e2233d895dd0` |
| Windows qualification host API and notebook | [`15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5`](https://github.com/gpt-cmdr/ras-commander/tree/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5) |

The host library launches containers; each image runs its own installed library.
Use a host release exposing the documented `RasDocker` methods, or install this
repository checkout in an isolated environment. The exact host revisions above
identify the live qualification; they are not a claim that every newer host
release has been tested with these payloads. Record the host package version
alongside the image digest and receipt.

```python
from importlib.metadata import version
from ras_commander import RasDocker

print(version("ras-commander"))
print(RasDocker.preprocess_plan, RasDocker.compute_plan)
```

## Qualification record and limits

The [retained release record](https://github.com/gpt-cmdr/ras-commander/blob/49d796f39f7ba2a3c136ee8129a22457743a32f3/containers/hecras-unsteady/RELEASE-CURRENT.md)
reports the September 2026 tests and publication of these exact payloads. This
summary brings their scope into the main documentation; it does not report new
engine runs from the October metadata check.

| Environment | Reported evidence for all three version pairs |
| --- | --- |
| Linux Docker | Real ras2fim sample, plan `01`, full 266-hour window; 267 output times, each with 6,548 finite water-surface values |
| Windows Docker Desktop, Linux containers | Same sample limited to one hour; two output times, each with 6,548 finite water-surface values; paths containing spaces |
| Resource and lifecycle checks | Two CPUs per container; matched solver settings; live progress, resume, sequential batch behavior, and retained preparation inputs |
| Line endings and publication | Linux Wine LF/CRLF cases; six anonymous digest pulls and matching image Config/RootFS identities |

These tests cover one real 2D sample per version at two cores. They do not qualify
other models, all 1–8 supported core settings, steady execution, a remote worker
image contract, TACC, or these payloads through `RasApptainer`/`RasSlurm`.
A successful transfer or hash check is not execution evidence. A successful
computation is not engineering approval.

`RasApptainer` has offline rendering, transport, and receipt tests. Its canonical
6.6 profile is derived from this native image's layout and metadata and still
requires a live qualification. Earlier CLB runs with a different SIF that included
`RasGeomPreprocess` do not qualify this default image. The published native image
does not contain `RasGeomPreprocess`; provide completed preprocessing artifacts.

## Build, reproduce, and maintain

The [native container source README](https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-unsteady/README.md)
describes external vendor runtime inputs, package inventories, the Dockerfile,
and controlled rebuilds. The
[Wine operating guide](https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/OPERATION.md)
describes the installed prefix, mounts, preprocessing checks, and runtime setup.
Wine recreation from an empty prefix was not qualified by the release record.

For a new image release, update this catalog with the actual digest, embedded
source, compatible host revision, model/run conditions, and observed results.
Retain model data and raw evidence outside Git. Update Docker Hub descriptions
to link to this catalog and the operating guide; use commit-pinned links for
historical release evidence. Do not infer a new qualification from a tag change.
