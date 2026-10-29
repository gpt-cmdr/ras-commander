# HEC-RAS container image catalog

Use the published images on **GitHub Container Registry (GHCR)** for current
Docker and Apptainer workflows. On a Linux x86-64 host, the supplied Wine runtime
runs Windows HEC-RAS preprocessing and computation without a Windows machine or
Windows VM. Where a matching native Linux engine is available, preprocessing can
hand off to that engine. The images contain HEC-RAS and its runtime dependencies;
users do not install Wine, .NET, or Windows Python on the host.

Wine still runs the Windows application inside the Linux container. Its prefix
contains installed programs and registry state; each job copies that prefix into
private scratch. This is distinct from installing or booting the Windows operating
system. These images cover the documented execution workflows, not every desktop
or RAS Mapper operation.

Review the applicable HEC-RAS Terms and Conditions for Use before using the
runtime; the [HEC-RAS 6.6 terms](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/terms-and-conditions-of-use)
provide a passive reference for that version. Retain the vendor notices supplied
with each image. Releases 6.0 and earlier also require the
[per-task acceptance setting](apptainer-images.md#hec-ras-60-and-earlier).

## Published images

The current image release uses tag **`0.106.0`** in `ghcr.io/gpt-cmdr`.
The [packaged catalog](https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/resources/container_images.json)
records digest-pinned OCI images and published SIFs with their SHA-256 values.
Use `RasContainerImages` to select those identities instead of a mutable tag.
The image release tag and the host Python package version are separate identities.

Anonymous registry metadata checked **October 29, 2026**: all 29 cataloged OCI
manifests and 23 SIF manifests were accessible, and each Wine image configuration
declared its CPU-shim path. This availability check did not execute HEC-RAS.

| Role | Use with | Published releases |
| --- | --- | --- |
| Wine preprocessing (`wine-precompute`) | `RasDocker.preprocess_plan` before a native solve | 5.0.7, 6.1, 6.5, 6.6, 7.0, 7.0.1 |
| Native Linux unsteady (`linux-unsteady`) | `RasDocker.compute_plan`, `RasApptainer.render_job` | 5.0.7, 6.1, 6.5, 6.6, 7.0, 7.0.1 |
| Full Windows compute under Wine (`wine-executor`) | `RasPortableDocker`, `RasSlurm`, `RasApptainer.render_prepare_job` | 5.0, 5.0.1, 5.0.3, 5.0.4, 5.0.5, 5.0.6, 5.0.7, 6.0, 6.1, 6.2, 6.3, 6.3.1, 6.4.1, 6.5, 6.6, 7.0, 7.0.1 |

For Docker, select matching preprocessing and native images:

```python
from ras_commander import RasContainerImages

version = "6.6"
preprocess_image = RasContainerImages.get("wine-precompute", version).reference
compute_image = RasContainerImages.get("linux-unsteady", version).reference
print(preprocess_image, compute_image)
```

Pass these references as `image=` to the respective
[`RasDocker` calls](container-execution.md#call-both-phases). For Apptainer,
[`resolve_sif()`](apptainer-images.md#use-a-local-or-cached-image) pulls the
published SIF and verifies its bytes against the catalog. Use the Wine executor
SIF for preprocessing on Slurm; the Docker preprocessing controller has a different
entry point. An OCI manifest digest and a SIF file SHA-256 identify different bytes.

### Current immutable registry identities

The following references match the packaged catalog. `wine-precompute` is an OCI
controller image; its Apptainer counterpart is `wine-executor`.

| HEC-RAS | Role | OCI image | Published SIF (ORAS) |
| --- | --- | --- | --- |
| `5.0` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0@sha256:0c106f34549aef4975c23a0a7840e78efad9e32a452f8de56cd59701690e4ef6` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0@sha256:18790fa5b53b8864c58b0c2345cd3f1e2a6391c29b017e471c81637451a71da9` |
| `5.0.1` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0.1@sha256:f4f7d4dd1854403dc346777f760477bfb37c9e2cd64054bae20b9f7a2ee7edb6` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0.1@sha256:6402f0e08b2793e900dc6620443ea89a97fe0d6c0bafb583e1ffbd7e59388bf7` |
| `5.0.3` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0.3@sha256:5dafe7ad96966df611287184c528c56bb32b0a943cf485c1dac8412863340676` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0.3@sha256:90b9ef319bafea4c7918ac98853c60ee143f97e80d649a638279494ccd6c78f1` |
| `5.0.4` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0.4@sha256:efcd7bb8a046b0c0581e49a334cf7d051fb200798a120a13cafced94efff3dc8` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0.4@sha256:e9b006a99d85d6c66892fe0e957c9d0ce4ba9fe9a2d1d2dcdf67510c5d409d50` |
| `5.0.5` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0.5@sha256:842aa8fa258cee9c9e42dceab57bb8de67021d071abcdfd5434ba77e0604a1ea` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0.5@sha256:5ba98db8d61982564b2f0fa61dbea74b13561bc23b0ba8bdb065fbde0e7e43dc` |
| `5.0.6` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0.6@sha256:fbeec117061eeeeb9541b7c5486ff76347b824a32b23303e17bd45c0b14b6a02` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0.6@sha256:67b22d454f6c6f6f4303bc199089c2a3882fc9a5fd94d81de432cd3aea727aca` |
| `5.0.7` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0.7@sha256:7ea5163a4777246455f36f51f7192c8f78995d9b4777db4c252dcf9aacf43863` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0.7@sha256:f563b4167ec36d7131d558d4e4aeb8cdcaab8eaaefb556d52e0c706b2d0df1de` |
| `6.0` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_6.0@sha256:fa5acad0e6108da5014b52ceaca38d098793076ae09bdc5ff4d36876bb543fd1` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_6.0@sha256:0d5e1cc73ca7953f10ff650ec2343b769bf366f82c3c17b47eb05fe6511d8114` |
| `6.1` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_6.1@sha256:0f07beb34a77d97a97cc855d2618f53b36908ba9222bb9cb95ecda59b982d28c` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_6.1@sha256:da5fbff897f87abf54769f79c4414d8d31fa5611aed02dc9f6793b9a63dff1c8` |
| `6.2` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_6.2@sha256:dd3f76a758ff9ecf1f526d30fd1e42cf149b645341cf7311b91b2c2516c07e8f` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_6.2@sha256:637464a953ef00e2760caab22cbd4a9ac5955ac24fe45aff206c4575eddcba4d` |
| `6.3` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_6.3@sha256:1d604f0823b52d55a7eadc2483400acfc9df7b72c53e0e42e93d45775505001e` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_6.3@sha256:ff78a39eab83856948cebba85490538c20b0fad445c9828a2aa451a852359b91` |
| `6.3.1` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_6.3.1@sha256:39c2d485038c521e57c90aebefe2ec1d797ab0ec6c59d8633be8d0b0e4dff1cc` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_6.3.1@sha256:6c944cf1343e34cbcb12cd18fd2061739321d9082778b326b56af7bd9107fa52` |
| `6.4.1` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_6.4.1@sha256:f84093b0df20a54c08c6fda016c3b90aa6a9864f6be561e7549b9d2a58eab652` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_6.4.1@sha256:1fff253ec0ee52828884b679d4f25fee77f5ea3c9a5e9fe57be622e4806cf713` |
| `6.5` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_6.5@sha256:d8c7216a47d6c01146ea72977d6ad1d3f6575760ea1a47320c2039058170f513` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_6.5@sha256:a9e916b3f588e799efe1ae264d4466746f75157278cb09c1091129049b78857a` |
| `6.6` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_6.6@sha256:c074ae74266c8f8f7a54e0b27abe33fabb52e729fb4395f61e5e2d101a9b8219` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_6.6@sha256:77cee520c1c0e25afe9eeb5d5a59a4fae44198ab27db55ddf3d20c62f0a02212` |
| `7.0` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_7.0@sha256:fd6dc9fd0b86456a4b58dc5f41da937b2be58d7a483659d10e7c6fefa1bf9963` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_7.0@sha256:696cf0c28a9b159416b5164f2f0e3f73d626e239c6dc1edf2e1f9e77ebb24869` |
| `7.0.1` | `wine-executor` | `ghcr.io/gpt-cmdr/hec-ras-wine-executor_7.0.1@sha256:386092006ed2653d30f9d8576ca8ea43690330aa1b73bf82e8c4b28f53c4f427` | `oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_7.0.1@sha256:24d3a879de3016971c0ffdef81523fbda27b0d15e1fd459144b022f9ab126e96` |
| `5.0.7` | `wine-precompute` | `ghcr.io/gpt-cmdr/hec-ras-wine-precompute_5.0.7@sha256:f013059b2584b2667d7b697729f034b4dc0bb27d1c2f929bfa1ac0265d1ea92f` | Use the Wine executor SIF |
| `6.1` | `wine-precompute` | `ghcr.io/gpt-cmdr/hec-ras-wine-precompute_6.1@sha256:344838ddc0aae7e834f97145dcfcfd0f9d47a96f3179fd7cc54e7a8948f699ea` | Use the Wine executor SIF |
| `6.5` | `wine-precompute` | `ghcr.io/gpt-cmdr/hec-ras-wine-precompute_6.5@sha256:95e418b8adc0541599e8c1b89f3903e027f20a81243f9362a752c93b4611f710` | Use the Wine executor SIF |
| `6.6` | `wine-precompute` | `ghcr.io/gpt-cmdr/hec-ras-wine-precompute_6.6@sha256:1eef40777dd4a1c99a18a1a6b9ce5524ea163b45133901dbe5d38895fef99c11` | Use the Wine executor SIF |
| `7.0` | `wine-precompute` | `ghcr.io/gpt-cmdr/hec-ras-wine-precompute_7.0@sha256:34f17ebb0cd6ef92ec993fd6cea8784da91556a8b83979d915cc010c264c0d12` | Use the Wine executor SIF |
| `7.0.1` | `wine-precompute` | `ghcr.io/gpt-cmdr/hec-ras-wine-precompute_7.0.1@sha256:1e87099ebcf3777f0d56e4a4cb4b6501173a7d1886bee11712866da7419fc9aa` | Use the Wine executor SIF |
| `5.0.7` | `linux-unsteady` | `ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_5.0.7@sha256:000c66b174940444fcdacac5b5a1077747f8252307d5db22f4c69545726a16ba` | `oras://ghcr.io/gpt-cmdr/hec-ras-linux-unsteady-sif_5.0.7@sha256:ed1c8f8cf670e07f6f3abc69a36e39a5bb22124c575eaab940bab0718c3c5869` |
| `6.1` | `linux-unsteady` | `ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_6.1@sha256:d756ace88649c5e39805ec2737d58c91578820f7645878bf2974baa159319eaf` | `oras://ghcr.io/gpt-cmdr/hec-ras-linux-unsteady-sif_6.1@sha256:3308a2f06f1266baf394ec6c55f68d210bf6ef0065635cf37eae37aa4222ffe1` |
| `6.5` | `linux-unsteady` | `ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_6.5@sha256:eac85cb9ca2646ff6ef43ec7c8f5036e1935b97f1a6b114d18289978b5e7ecc6` | `oras://ghcr.io/gpt-cmdr/hec-ras-linux-unsteady-sif_6.5@sha256:47e249e0ec89c16f5b0bf3626129a7b602439a742e907b951e1ca61c6f433c16` |
| `6.6` | `linux-unsteady` | `ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_6.6@sha256:219084e923d704a3209999fda7efdb42a731dcc632bd38c6fdabca00fc0a7ec0` | `oras://ghcr.io/gpt-cmdr/hec-ras-linux-unsteady-sif_6.6@sha256:b14aa2d973ca7337981ddaf0482e67d368cdc092f13a7b1a06824d26c12b3f3b` |
| `7.0` | `linux-unsteady` | `ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_7.0@sha256:990ef97924b72d2d74a5c8ea3e26a77180fb567e3d64fa68cbf68bb2fcd03ef1` | `oras://ghcr.io/gpt-cmdr/hec-ras-linux-unsteady-sif_7.0@sha256:b8ce833a4e2059cce033647f574eed45ac786506f2c3709758a59a2793c5c737` |
| `7.0.1` | `linux-unsteady` | `ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_7.0.1@sha256:9d9d12630ae8289a4a4332b5463e23acbb00973caa3c963cb3d61b2c30baf9bf` | `oras://ghcr.io/gpt-cmdr/hec-ras-linux-unsteady-sif_7.0.1@sha256:c61aa6b81912859f0dbebb8d750956439b14d8b9a323fbefed2477191a6c7721` |

## Qualification record and limits

The [October 13–15 qualification record](apptainer-images.md#qualification-status)
reports Muncie 1D/2D Wine requests, Wine preprocessing followed by native Linux
solves where available, and gridded precipitation checks. It identifies the final
published SIFs as the files used in the October 15 Slurm requalification. The
final Docker images also ran the Muncie 2D preparation/solve workflow for every
published native-engine release.

The current Wine preprocessing and executor builds include the
[CPU-numbering shim](apptainer-images.md#cpu-numbering-shim) needed when a CPU
allocation does not begin at host CPU 0. The older Docker Hub `v4` preprocessing
images do not contain it. Host AppArmor settings and cluster scratch/memory
requirements are described in the execution guides.

Qualification covers the recorded example models and settings, not every model,
core count, GUI operation, or cluster. ARM and TACC execution are outside that
record. Run a representative model on your site before a campaign. Registry
access and matching hashes establish availability and identity, not a new engine
run or engineering approval. The September Windows Docker Desktop results below
apply to the historical payloads, not automatically to the newer GHCR images.

## Build, reproduce, and maintain

Routine users pull the installed image. Maintainers can build the Wine runtime
on Linux with [`containers/hecras-wine-runtime`](https://github.com/gpt-cmdr/ras-commander/tree/main/containers/hecras-wine-runtime):
`build_base.sh` initializes an empty prefix and installs .NET 4.8, GDI+, fonts,
and Windows Python; `build_release_images.sh` installs the selected official
HEC-RAS release and the selected ras-commander wheel, writes the runtime manifest,
and builds the preprocessing and executor images with the CPU shim. See the
[build procedure](apptainer-images.md#build-wine-images-for-a-release).

The October qualification records release installations built from the official
installers on that shared base. It does not establish byte-for-byte reproducible
builds or an independent rebuild of every dependency on an unrelated clean host.
Retain installer files, hashes, source revision, dependency inventories, build logs,
and representative run receipts for a controlled rebuild. The
[native image recipe](https://github.com/gpt-cmdr/ras-commander/blob/main/containers/hecras-unsteady/README.md)
uses the matching official Linux runtime.

For a new image release, update the packaged catalog with the actual OCI/SIF
digests and SIF hashes, and document the source, host version, run conditions,
and observed results. Retain raw model/build evidence outside Git. Do not infer
qualification from a tag change or transfer.

## Historical Docker Hub images

The following September 2026 payloads remain available for retained workflows.
Their source revisions, tests, and limitations describe those exact images.
They predate the GHCR release above. In particular, their retained-prefix build
record did not qualify installation from an empty prefix and their Wine `v4`
images lack the CPU shim. Use the current build procedure for a new runtime.

### Published Docker Hub images (September 2026)

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

### Sources and host compatibility

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

### Qualification record and limits

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

Earlier `RasApptainer` and `RasSlurm` runs used site-built
SIFs (a native 6.6 engine that includes `RasGeomPreprocess`, and Wine executors
derived from the 6.6 pre-compute image). These historical Docker Hub payloads
are separate from the GHCR images and SIFs qualified in October; do not transfer
qualification between them. The historical native image does not contain
`RasGeomPreprocess`; provide completed preprocessing artifacts. See
[Apptainer images](apptainer-images.md) for current SIF selection and preparation.
