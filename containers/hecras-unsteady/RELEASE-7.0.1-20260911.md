# HEC-RAS 7.0.1 container release — 11 September 2026

The matching Wine preprocessing and native Linux unsteady images are published
and ready to run the qualified 2D workflow from Linux or Windows Docker Desktop.
Both images contain their HEC-RAS runtime. The host uses
[RasDocker.preprocess_plan()][api], followed by [RasDocker.compute_plan()][api],
or [RasDocker.run_plan()][api] to perform both stages in order.

## Published images

Both repositories are public and target `linux/amd64`. The versioned tag and
`latest` select the same tested image within each repository.

| Stage | Docker Hub image | Published digest |
|---|---|---|
| Wine preprocessing | [rascommander/hec-ras-wine-precompute_7.0.1:v4][wine] | `sha256:05bd9a0a272381857e0267734fa8ff287659535181ed4ce0c8e259642b65840d` |
| Native unsteady compute | [rascommander/hec-ras-linux-unsteady_7.0.1:v1][native] | `sha256:8c74c0b7450a13830d3424a599670d5cedf0309afc3f08e1515489a20f2ed964` |

```bash
docker pull rascommander/hec-ras-wine-precompute_7.0.1:v4
docker pull rascommander/hec-ras-linux-unsteady_7.0.1:v1
```

Anonymous Docker Hub reads confirmed public visibility and matching tags.
Both versioned images were pulled back successfully after publication.

Install the host API revision in the [operating guide][guide], then set
`RAS_DOCKER_VERSION=7.0.1` for the [example notebook][notebook], or pass
`version="7.0.1"` to each API call. Both phases require the same version.

## Source and installed runtimes

The native image installs [ras-commander at commit aa003b1][source], including
the [native worker][worker]. The host installation uses this same revision.
The distribution version remains `0.99.2`; the commit identifies this build.

The Wine controller uses the published
[ras2fim source snapshot 3c5011d][wine-source]. Windows Python contains the retained
[ras-commander wheel build 9e42177][wine-library]. The Wine and native images
therefore have distinct recorded library builds; they share the host API.

The Wine image contains Windows HEC-RAS 7.0.1 at
`C:\Program Files (x86)\HEC\HEC-RAS\7.0.1\Ras.exe` inside
`/runtime/wine-seed/prefix`. A fresh private copy passed the runtime audit:
the expected executable, version-specific registry state, and saved TCU acceptance
for version `701` were present. Its Windows file-version resource reports
`7.0.0.1`; the installed application is HEC-RAS 7.0.1. No new acceptance was
needed during this audit. The user authorized publication on 11 September 2026.

The native runtime came from the official
[HEC-RAS 7.0.1 combined installer with Linux engines][installer].
Its actual `RasUnsteady` executable and result HDF both identify
**HEC-RAS 7.0.1 June 2026**. The image contains only the selected native
unsteady engine, its library tree, and vendor notices from those external inputs.
The exact installer TCU is retained with the notices.

- Official installer SHA256:
  `f3d28695bd98cbc7a1bcb5bdaea073c5c512a071a22a9d3bfd90a3309f405003`.
- Native `RasUnsteady` SHA256:
  `caae44088b52fb66cbfd7eeca92d0ec8a3f5d7abff2c03eea05e7fca344c250f`.
- Native image package and artifact inventory:
  [runtime-inventory-7.0.1-20260911.json](runtime-inventory-7.0.1-20260911.json).

See the [runtime extraction recipe](RUNTIME-7.0.1.md), the
[image reconstruction guide](README.md#how-to-re-create-this-container),
and the separate [Wine reconstruction guide][wine-rebuild].
The Wine build starts with a retained prepared profile; an independently
reproducible installation from an empty Wine prefix remains outside this
release's demonstrated reconstruction steps.

## Executed qualification

The fixture is the public [ras2fim sample][sample], under
`sample_output/02_model_copies/`:

```text
1919912_wb-2427466_wb-2427467_14-hr_50-cfs_to_11609-cfs
```

Both hosts used fresh working copies with populated original geometry HDFs.
The project was mounted read/write at `/job`; its terrain and projection
siblings were mounted read-only at `/source_terrain` and `/projection`.
Both stages ran as root for consistent Windows bind-mount access.

| Check | Linux full plan | Windows Docker Desktop notebook |
|---|---|---|
| Simulation window | 1 January 2000 00:00 to 12 January 2000 02:00; 266 hours | 1 January 2000 00:00 to 01:00; explicit one-hour demo |
| Water-surface array | 267 times × 6,548 columns; all finite | 2 times × 6,548 columns; all finite |
| Prepared temporary HDF | 4,676,123 bytes; preserved after compute | 4,674,075 bytes; preserved after compute |
| Final result HDF | 9,404,306 bytes | 5,053,201 bytes |
| Native solver cores | 4 | 2 |
| Notebook | Independent final-HDF inspection | All 10 code cells passed, including inspection and plotting |

Linux native computation completed in approximately 76 seconds. The final
HDF was independently opened and checked for the actual 7.0.1 file-version
attribute, full timestamp range, array shape, and finite values.

Windows used Docker Server 29.7.2 in Docker Desktop's WSL2 Linux engine and
Python 3.14 on the host. Its working folder contained spaces. Image layers,
architecture, entrypoint, environment and source labels were checked against
the Linux build before execution. This is a one-hour Windows qualification;
the 266-hour execution was performed on Linux.

Both preprocessing runs retained all 6,548 mesh coordinates and populated
cell-volume and face-area elevation tables. The sample's collection metadata
reports 6,201 cells; the coordinate and water-surface arrays contain 6,548
columns, which the notebook checks separately.

The focused API, worker and Linux execution regression suite passed
**130 tests, with 2 skipped**. It includes strict 7.0.1 version matching and
mismatch rejection. The [machine-readable validation record][validation]
contains image identities and observed output checks. Model files, results,
executed notebooks and complete runtime evidence remain outside Git.

## Observed limits and recovery

An initial Linux preprocessing attempt exhausted the Docker host's available
space while copying the private Wine prefix, before HEC-RAS launched.
Two superseded local candidate images were removed; the published 6.5/6.6
images and retained runtime profiles were preserved. A fresh attempt then
passed. Capacity planning must include installed image layers and a private
Wine prefix for each concurrent preprocessing job.

The native solver logged a warning that the optional
`/Results/Summary/Compute Processes` dataset was absent. Required unsteady
water-surface data and full time coverage passed validation.

Qualification covers this supplied 2D sample and execution workflow. It
does not establish numerical equivalence between HEC-RAS releases or qualify
every model type. Use a complete working model with its referenced data and
retain the receipts when testing other projects.

[api]: https://github.com/gpt-cmdr/ras-commander/blob/aa003b179e9d0f89ba23da0607ffab9bfee74a60/ras_commander/RasDocker.py
[source]: https://github.com/gpt-cmdr/ras-commander/tree/aa003b179e9d0f89ba23da0607ffab9bfee74a60
[worker]: https://github.com/gpt-cmdr/ras-commander/blob/aa003b179e9d0f89ba23da0607ffab9bfee74a60/ras_commander/_container_compute.py
[wine]: https://hub.docker.com/r/rascommander/hec-ras-wine-precompute_7.0.1
[native]: https://hub.docker.com/r/rascommander/hec-ras-linux-unsteady_7.0.1
[guide]: https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/docs/user-guide/container-execution.md
[notebook]: https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/examples/512_docker_precompute_and_linux_compute.ipynb
[wine-source]: https://github.com/gpt-cmdr/ras2fim-2d/tree/3c5011dbe150d8311e45598401b16645c6e61932/containers/hecras-prepare
[wine-library]: https://github.com/gpt-cmdr/ras-commander/tree/9e4217713e954236b0c16023e1815c6f2b7a5309
[wine-rebuild]: https://github.com/gpt-cmdr/ras2fim-2d/blob/codex/phase2-linux-wine-preprocessing/containers/hecras-prepare/dockerhub/7.0.1.md#how-to-re-create-this-container
[installer]: https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/1.0.46/HEC-RAS_701_with_Linux_Setup.exe
[sample]: https://rasfim-2d-sample.s3.amazonaws.com/index.html
[validation]: validation-7.0.1-20260911.json
