# Current container release record

This record tracks the matching HEC-RAS 6.5, 6.6 and 7.0.1 Wine preprocessing
and native Linux unsteady images. It describes the sources and tests for
these exact images. Model inputs, solver results, vendor software and raw
execution evidence remain outside Git.

**Qualification status:** All three matching versions passed the full 266-hour Linux sample and the one-hour Windows Docker Desktop notebook, using two CPUs per container. Linux results contained 267 output times; Windows results contained two, with 6,548 finite water-surface values at every time. Live progress, resume and sequential batch checks passed on both hosts; the six Linux Wine LF/CRLF cases also passed. The images are published on Docker Hub, and anonymous pulls verified all six matching payloads.

## Sources and build inputs

| Component | Exact source and purpose |
|---|---|
| Native image and installed library | [`604704d440c49a39d6f6e8bae262e2233d895dd0`][native-tree]; includes the [Dockerfile][dockerfile], [requirements.lock][lock], [container worker][worker], and [RasCmdr.py][cmdr]. |
| Host API and notebook packet | [`15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5`][host-tree]; contains [RasDocker.py][docker-api] and the 12 workflow code cells used in Windows qualification, with the disclosed external qualification settings and checks. |
| Wine controller | [`dc60b219091e85bcb4564eca45313475c39ce58a`][wine-tree]; includes [Dockerfile][wine-dockerfile], [prepare.py][wine-controller], [windows_worker.py][wine-worker], and [model_checks.py][wine-checks]. |
| Windows library installed in the Wine profile | Retained version 0.99.2 wheel from [`9e4217713e954236b0c16023e1815c6f2b7a5309`][windows-tree]. All 239 package files match that source: 4 match raw Git bytes, 235 differ only by CRLF/LF, and none have other differences. |
| Native runtime input | External `runtime.json`, `engine/RasUnsteady`, complete `engine/libs/`, and vendor `notices/`, exported using [bundle_runtime.py][bundler]. |
| Wine runtime input | External `runtime.json` and prepared `prefix/`, exported using [bundle_profile.py][wine-bundler]; includes matching Windows HEC-RAS, Python and the retained library wheel. |

The native OCI revision identifies its installed library source. The Wine
OCI revision identifies the controller source, while its
`io.clb.ras-commander.commit` label identifies the Windows library separately.
The Linux API qualification used host source `604704d...`; the selected
`15b7ffc...` host revision descends from it.

Follow [How to re-create the native container][readme] and the
[Wine recreation guide][wine-recreation] for the source checkout, vendor
acquisition, external contexts and build commands. The
[7.0.1 reconstruction guide][runtime-701] describes extraction of the official
combined installer through [extract_installer.py][extractor].
Rebuilding Wine currently starts with a retained prepared prefix; an
empty-prefix installation recipe and a clean-host recreation have not been
qualified. The retained wheel preserves exact packaging metadata; the
original build's working-tree cleanliness was not recorded.

The [current native inventory](https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/containers/hecras-unsteady/runtime-inventory-current.json) records 90 Debian package records, 12 Python distributions and 248 installed package files checked against embedded source. The [current Wine inventory](https://github.com/gpt-cmdr/ras2fim-2d/blob/codex/phase2-linux-wine-preprocessing/containers/hecras-prepare/runtime-inventory-current.json) records 512 Debian package records, 49 Windows Python distributions and 239 package files checked against the retained wheel in each image, with the raw-Git line-ending comparison above. Both inventories retain image identities, runtime paths and exact source links.

## Published image identities

All six images target `linux/amd64`. Docker Hub serves the exact qualified image payloads at the registry digests below. The Config and RootFS inventories also matched after Windows loading and anonymous digest pulls.

| Published tags | Registry digest SHA256 | Image Config SHA256 |
|---|---|---|
| `rascommander/hec-ras-wine-precompute_6.5:v4` / `latest` | `5de3b51455e7405ea0f85f1d9112c8232e41faaad74a4c13bd511fad8c8eda99` | `7f70141c556618cfb8d93927dacbd88489f51a293567425eed48061d607b9ac4` |
| `rascommander/hec-ras-wine-precompute_6.6:v4` / `latest` | `5fbc07a20693cb867578048be632d88cee02618780259c1c7ddc258c9fbb4318` | `4b8032eb8e2307245281f5f99fcc186c2374c7433c4d61a42604eae712877ad1` |
| `rascommander/hec-ras-wine-precompute_7.0.1:v4` / `latest` | `f53db7bd9e256f203e07fee77a624aef3fe33ba23e04f94e2e3a9afc62f4359d` | `eb2b96901cf87dbc685e732b1d0799827067fff97ee2eb2c9ae693910f5cfc6b` |
| `rascommander/hec-ras-linux-unsteady_6.5:v1` / `latest` | `944c6b4a5d2a0eca7cd8c381e614a25cb4f03a559e3a082c6de66c38fbd363c8` | `568b0a8f2854baf2ba2159e83eb4b6489e069bab996153acb3f8aa63cf39467e` |
| `rascommander/hec-ras-linux-unsteady_6.6:v1` / `latest` | `71dec03350996cfa8a0ccb18ae08075de9b9cc3d7fb6b1dddbf541c030abb95c` | `7b6ff681681ddd67a641a48953e82a23b592b28f66ec5106a4b24b23d7c4b497` |
| `rascommander/hec-ras-linux-unsteady_7.0.1:v1` / `latest` | `038475b5669ff45b2087fba0370321e89696f1c1d526123dfad24c4334ee1ed9` | `a9d2ae8f18b34f2266d0217c63bd900e3a1885190405dd0da032d3414805e684` |

The archive carrying all six qualified images was 8,376,091,614 bytes, with SHA256
`f3c93aada4453834597698e9f99eb013bcf2749b100b1d10ee40c678a0096a7a`.
Its complete image Config and RootFS inventories were verified before
transfer and after loading on Windows. This establishes image transfer
integrity, not execution success.

## Linux qualification

Fresh copies of the real ras2fim sample
`1919912_wb-2427466_wb-2427467_14-hr_50-cfs_to_11609-cfs`, plan `01`,
were processed through [RasDocker.preprocess_plan()][docker-api] and
[RasDocker.compute_plan()][docker-api]. The project was mounted read/write
at `/job`, with its complete terrain and projection dependencies mounted
read-only at `/source_terrain` and `/projection`. The source fixture and
prepared folders were preserved.

| HEC-RAS | Wine LF / CRLF cases | Prepared temporary HDF bytes | Native full 266-hour result | Water-surface values |
|---|---|---:|---|---|
| 6.5 | Pass / Pass | 2,680,668 | Pass | 267 times × 6,548 finite values |
| 6.6 | Pass / Pass | 2,681,108 | Pass | 267 times × 6,548 finite values |
| 7.0.1 | Pass / Pass | 4,676,101 | Pass | 267 times × 6,548 finite values |

The output times cover 2000-01-01 00:00 through 2000-01-12 02:00, exactly
matching the requested 266-hour window. Geometry and temporary HDFs retained
the `Perimeter 1` mesh, 6,548 coordinate rows, and populated cell-volume and
face-area tables. Collection metadata contains 6,201 cells; it was checked
separately from the coordinate and water-surface column counts. The native
producer identities were 6.5 February 2024, 6.6 September 2024, and 7.0.1 June
2026. The plan's declared version string was not used as proof of the
executing runtime.

### CPU settings and line endings

The live tests used the default `num_cores=2`. The host passed both Docker
`--cpus 2` and worker `--num-cores 2`; receipts recorded
`arguments.num_cores=2`. Observations confirmed `NanoCpus=2000000000` and
cgroup `cpu.max=200000 100000`. Wine set and read back the plan's unsteady
and default 2D core settings; its API also supports named 2D overrides. Native computation showed
`OMP_NUM_THREADS=2`, `MKL_NUM_THREADS=2`, two solver OS threads, and HDF core
attributes of two. The API accepts integers 1–8; this engine qualification
covers the default two-core case.

Wine successfully processed both LF and CRLF copies of the sample's
`.prj/.p##/.g##/.u##` text, normalizing the selected text to CRLF. Generated
`.x##` files used LF. Native scratch text used LF, and the host preparation
`.tmp.hdf/.b##/.x##` files remained byte-identical through computation.
Binary HDFs were never treated as text.

### Progress, resume and sequential batches

Callbacks received native solver log messages before computation ended.
For each version, the received native-log sequence matched the retained log
in full and in order. Successful stages were reused with `resume=True`
while a deliberately failing Docker executable proved that resume did not
launch another container. Sequential batch checks retained ordered CSV/JSON
summaries and continued from an invalid job to a valid resumed job.

The [structured execution observations][cmdr] are retained alongside the
native solver log and full result checks. A generic HDF completion attribute
alone is insufficient because it can already be present in the prepared
input. The qualified result checks require the full time window, expected
dimensions, and finite water-surface values.

### Scope of the evidence

These results cover one real 2D sample per HEC-RAS version on a Linux Docker
host. They do not establish results for other models, other core counts,
exclusive CPU affinity, or a TACC/HPC scheduler. The paired Wine-to-native
line-ending route was tested; arbitrary imported CRLF `.x` files and
standalone mixed or bare-CR text were not independently qualified.

## Windows qualification

All three matching image pairs passed the notebook workflow on Windows
Docker Desktop using host source `15b7ffc...` and paths containing spaces.
The same complete sample was limited to 2000-01-01 00:00 through 01:00
before preprocessing. This is a one-hour Windows demonstration; the
266-hour full plan was computed on Linux.

| HEC-RAS | Workflow cells and external checks | Native result | Final HDF bytes | Prepared HDF preserved |
|---|---|---|---:|---|
| 6.5 | Pass | 2 times × 6,548 finite values | 3,052,376 | Yes |
| 6.6 | Pass | 2 times × 6,548 finite values | 3,060,415 | Yes |
| 7.0.1 | Pass | 2 times × 6,548 finite values | 5,053,201 | Yes |

The retained execution contains the 12 notebook workflow cells plus one
external qualification assertion cell per version: 39 cell executions
across the three versions, including a result plot for each. Three workflow
cells in the external test copy use disclosed qualification switches,
callback instrumentation or prepared-state capture; their exact changes
are retained in `notebook-adjustments.json`. The repository notebook's
12 code-cell dictionaries and outputs remain unchanged by this documentation
update.

Live observations showed Docker `NanoCpus=2000000000` for both stages,
`--num-cores 2` in both commands, and two cores recorded in both receipts.
The project mount was writable; terrain and projection mounts were read-only.
Native `SIMTIME` events arrived before completion. Preparation and compute
resume both passed with no Docker executable available, and the sequential
batch continued from a failed row to a valid resumed row. Original fixture
and prepared temporary HDF checks passed for every version.

## Docker Hub publication

Publication completed on 2026-09-12 UTC. All twelve tags—Wine `v4` and
`latest`, native `v1` and `latest`, for each of 6.5, 6.6 and 7.0.1—resolve
to the six qualified digests in the table above. Six anonymous digest pulls
verified the public payloads and their image Config/RootFS identities.

Pull both matching images before the first run, or use `pull="always"` in
[RasDocker][docker-api]. To retain an immutable runtime selection, use the
matching `repository@sha256:<digest>` reference from the table. The
[machine-readable validation record](validation-current.json) summarizes
qualification and publication.

The final publication receipt is retained at
`C:\Users\billk_clb\codex-artifacts\container-publication-features-20260911\recovery-20260912T024349Z-a3ff08fd\publication.json`,
with SHA256
`26ae380970b48d263866636bff1008a39eefe95d8d5f5050d9f0e60a677524df`.
It records twelve published tag/config/digest entries and six public digest
pull verifications. Supporting registry inspections and pull logs remain in
the external publication evidence.

## Retained evidence and runtime provenance

The following are external evidence locations on the controlled build and
test hosts, not files embedded in the Git repository:

- Linux Wine: `/scratch/ras-container-features-20260911/wine-dc60b21/`.
  Build records are under `evidence/isolated-v2/`; `evidence/completion.json`,
  `evidence/audit-<version>.json`, and `qualification/<version>-lf/` and
  `qualification/<version>-crlf/` retain checks, receipts and logs.
- Linux native: `/scratch/ras-container-features-20260911/native-604704d/`.
  Retain `builds-v2.json`, `REPORT.md`, `qualification-summary.json` and
  each `qualification-<version>/evidence/` directory.
- Local copies: `C:\Users\billk_clb\codex-artifacts\wine-candidates-dc60b21-20260911\`
  and `C:\Users\billk_clb\codex-artifacts\native-candidates-604704d-20260911\`.
  The Wine `transfer/` directory retains Config/RootFS inventories and the
  verified archive receipt.
- Windows execution: `C:\Users\billk_clb\codex-artifacts\container-desktop-features-20260911\`.
  `desktop-v2-local-verification.json` records the local verification of
  150 evidence files and the three successful versions.
  `desktop-notebook-15b7-v2-evidence/notebook-packet/evidence-v2-source-normalized/<version>/`
  retains `qualification.json`, `prepare.json`, `compute.json`, callback
  events, executed notebook, plots and batch summaries; the packet retains
  `notebook-adjustments.json`.
- Windows archive: `C:\Users\bill\ras-container-features-20260911\transfer\ras-container-candidates-dc60b21-604704d.tar.gz`.

The retained Wine contexts are
`/scratch/ras2fim-hecras/release-bundled-20260909/profiles/wine-<version>-release`.
Each manifest declares the selected HEC-RAS version. The installed executable
is `C:\Program Files (x86)\HEC\HEC-RAS\<version>\Ras.exe`; Windows Python
is `C:\Python311\python.exe`. Read-only seed inspection confirmed saved
TCU state for 6.5, 6.6 and 7.0.1. Original installer/first-launch records remain
under the external runtime-staging evidence directories documented in the
[Wine recreation record][wine-recreation]; these qualification tests did not
repeat installer acceptance.

Native contexts for 6.5 and 6.6 are under
`/scratch/ras-commander-containers-20260911/runtimes/<version>`; 7.0.1 uses
`/scratch/ras-commander-containers-701-20260911/native-context`.
Their vendor notices accompany the selected executable and libraries.
The 7.0.1 installer TCU extraction evidence is retained separately from
Wine acceptance state. Neither installers nor runtime/model/result payloads
belong in Git.

[native-tree]: https://github.com/gpt-cmdr/ras-commander/tree/604704d440c49a39d6f6e8bae262e2233d895dd0
[host-tree]: https://github.com/gpt-cmdr/ras-commander/tree/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5
[wine-tree]: https://github.com/gpt-cmdr/ras2fim-2d/tree/dc60b219091e85bcb4564eca45313475c39ce58a
[windows-tree]: https://github.com/gpt-cmdr/ras-commander/tree/9e4217713e954236b0c16023e1815c6f2b7a5309/ras_commander
[dockerfile]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/Dockerfile
[lock]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/requirements.lock
[worker]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/ras_commander/_container_compute.py
[cmdr]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/ras_commander/RasCmdr.py
[docker-api]: https://github.com/gpt-cmdr/ras-commander/blob/15b7ffc7e1b5c6896eb5c99da0b34739d4b8b9e5/ras_commander/RasDocker.py
[wine-dockerfile]: https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/Dockerfile
[wine-controller]: https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/prepare.py
[wine-worker]: https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/windows_worker.py
[wine-checks]: https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/model_checks.py
[wine-bundler]: https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/bundle_profile.py
[bundler]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/bundle_runtime.py
[extractor]: https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/extract_installer.py
[readme]: https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/containers/hecras-unsteady/README.md
[runtime-701]: https://github.com/gpt-cmdr/ras-commander/blob/codex/container-precompute-linux/containers/hecras-unsteady/RUNTIME-7.0.1.md
[wine-recreation]: https://github.com/gpt-cmdr/ras2fim-2d/blob/codex/phase2-linux-wine-preprocessing/containers/hecras-prepare/PREPARATION.md
