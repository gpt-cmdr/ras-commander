# Build the HEC-RAS preprocessing container

## Current build from an empty Wine prefix

Routine users pull the installed [GHCR image](../../docs/user-guide/container-images.md).
On Linux, it runs the documented preprocessing workflow without a Windows machine
or VM and without installing Wine or .NET on the host.

For a new build, follow [hecras-wine-runtime](../hecras-wine-runtime/README.md)
and the [release build procedure](../../docs/user-guide/apptainer-images.md#build-wine-images-for-a-release).
`build_base.sh` initializes an empty prefix and installs Wine prerequisites,
.NET 4.8, GDI+, core fonts, and Windows Python 3.11.9 with compute dependencies.
`build_release_images.sh` installs the selected official HEC-RAS release into a
copy of that base, installs the selected ras-commander wheel, writes `runtime.json`,
and builds the preprocessing image with its CPU shim and the executor derivative.
The scripts take official installer and wheel paths; retain their hashes and
build logs. For 7.x, extract the MSI as described in the release build procedure.

The October qualification used release profiles installed from official
installers on the shared base and recorded end-to-end Docker/Slurm runs. It does
not establish byte-for-byte reproducibility or an independent rebuild of the
whole dependency chain on another clean host. Qualify a rebuilt image with a
representative model and retain its receipts before using it for a campaign.

## Historical v4 retained-profile reconstruction

The remainder of this page preserves the September `v4` inputs, inventory,
and reconstruction limitations. Its old wheel, source hashes, and missing
empty-prefix qualification describe `v4` only. They are not prerequisites or
publication status for the current GHCR release. Use the current build above
for a new runtime; use this historical record when inspecting the old payloads.

Companion to [the operating guide](OPERATION.md) and the [v4 release verification](https://github.com/gpt-cmdr/ras-commander/blob/49d796f39f7ba2a3c136ee8129a22457743a32f3/containers/hecras-unsteady/RELEASE-CURRENT.md).
Ported from the ras2fim-2d rebuild guide ([source](https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/PREPARATION.md)). The
[v4 installed-code record](https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/INSTALLED-CODE.md) lists the scripts and library
source installed in the published `v4` images.


This section is for rebuilding the image. Routine users can start with the
installed image and the [run command](README.md#run-on-a-linux-filesystem).

**The historical `v4` build started with a retained, prepared Wine profile.**
Its release record did not demonstrate installation from an empty Wine prefix.
The steps below identify the inputs, build procedure, and remaining work needed
for that fully independent reconstruction.

### 1. Gather the build inputs

Use one reviewed ras-commander checkout containing these files under
`containers/hecras-wine-precompute/`. Record its commit for the image revision
label. The published `v4` images were built from the equivalent files at
ras2fim-2d commit `dc60b219091e85bcb4564eca45313475c39ce58a`, without
`cpushim.c`. External inputs link to their example or layout documentation.

| Input | Purpose |
|---|---|
| [Dockerfile](Dockerfile) | Linux tools, CPU shim build stage, user 1000, bundled Wine profile, and entrypoint. |
| [cpushim.c](cpushim.c) | `sched_getcpu` remap compiled in the `cpushim` stage and installed at `/opt/hecras-prepare/cpushim.so`. |
| [model_checks.py](model_checks.py) | Checks dependencies, normalizes input line endings and validates HDF content. |
| [prepare.py](prepare.py) | Linux job controller, private runtime setup, worker launch, and receipts. |
| [windows_worker.py](windows_worker.py) | Calls the linked [ras-commander][rc] APIs under Wine. |
| [bundle_profile.py](bundle_profile.py) | Exports a prepared runtime into the external build context. |
| External [runtime.json](runtime-manifest.example.json) and `prefix/` | Installed HEC-RAS 6.5 and dependencies. Links show the manifest example and layout; actual runtime contents stay outside Git. |
| Retained [ras_commander-0.99.2-py3-none-any.whl][installed-package] | External wheel from build `9e4217713e954236b0c16023e1815c6f2b7a5309`; the link opens its exact package source, not a wheel download. |

The base is `python:3.13.15-slim-trixie` pinned by its Dockerfile digest. The
Dockerfile also pins Wine, Xvfb, xauth, procps and tini. Windows package versions
are recorded in the inventory below. API links identify the exact installed
[package source](https://github.com/gpt-cmdr/ras-commander/tree/9e4217713e954236b0c16023e1815c6f2b7a5309/ras_commander). All 239 wheel package files match commit
`9e4217713e954236b0c16023e1815c6f2b7a5309` after normalizing line endings. Retain the exact
wheel to reproduce its packaging metadata. The original build did not record
working-tree cleanliness; this does not change the verified package-source match.

### 2. Prepare or recover the installed Wine profile

The retained profiles contain Windows Python 3.11.9, .NET 4.8, Visual C++
runtimes, GDI+, fonts, HEC-RAS, and accepted TCU state. Preserve the original;
work on a separate copy. Preserve `dosdevices/c: -> ../drive_c` and
`dosdevices/z: -> /` as links without following them during copies.

To create a replacement from an empty prefix, install those prerequisites,
the selected official HEC-RAS release, and the retained
[ras-commander][rc-github] wheel. Complete any installer and first-launch TCU
prompts, then close Wine cleanly and verify the saved state with
[RasTcu.status()][tcu-status]. The retained profile's dependency list is an
inventory; it does not yet supply all prerequisite download URLs or a tested
installer sequence.

Preparation details recorded for the historical runtime:

- The retained installation wheel is
  `C:\ras2fim-runtime\ras_commander-0.99.2-py3-none-any.whl`. It was installed
  using Windows Python with `pip install --no-index --no-deps --no-cache-dir
  --disable-pip-version-check --force-reinstall --no-compile`. Its dependencies
  were already present. `--no-deps` does not install them in an empty prefix.
- Wine initialization used
  `WINEDLLOVERRIDES="mscoree,mshtml,winemenubuilder.exe,winedbg.exe="` for
  `wineboot`, followed by Winetricks prerequisites. This initialization setting
  must not disable `mscoree` during normal HEC-RAS 7.0.1 startup, which needs .NET.
- HEC-RAS 7.0.1's outer installer stalled on its .NET 4.8.1 web prerequisite.
  Its extracted official MSI was installed directly. The resulting .NET 4.8
  profile passed the retained sample. This is a recorded installation workaround.
- The 6.5 profile already held accepted TCU state. The 6.6 installer and first
  launch were accepted. The 7.0.1 application's first-launch terms were accepted.
  [RasTcu.accept()][tcu-accept] persisted acceptance where needed. Wine was
  stopped with `wineserver -k` followed by `wineserver -w` while the surrounding
  container process remained alive, allowing registry writes to finish.
- Saved TCU values are `650`, `660`, and `701` for the respective releases,
  scoped to the Windows user and full installed executable path. Fresh-copy
  checks verified them without invoking [RasTcu.accept()][tcu-accept] again.

Finalize `runtime.json` after installation: schema `ras-commander-runtime/v1`,
`kind: wine`, `hec_ras_version: "6.5"`, selected executable/Python/wheel
paths, build identity, and actual artifact records. A retained finalized profile
already supplies this manifest. If installed files change, regenerate the
manifest before export. A portable manifest-generation command remains part
of the reconstruction work; the example manifest's zero values are placeholders.

### 3. Export the profile and build the image

Run from the repository root on Linux. The source is the finalized profile
from step 2. The destination must be a new directory outside Git. Export removes
temporary installers, caches, files covered by the personal-file filters, and
unrelated HEC-RAS program directories while retaining vendor notices. Review the
exported contents before publishing.

```bash
python containers/hecras-wine-precompute/bundle_profile.py \
  --source /controlled/hecras-6.5-wine \
  --destination /controlled/releases/hecras-6.5 \
  --version 6.5

docker buildx build --load --platform linux/amd64 \
  --build-context hecras_runtime=/controlled/releases/hecras-6.5 \
  --build-arg HEC_RAS_VERSION=6.5 \
  --build-arg RAS_COMMANDER_COMMIT=9e4217713e954236b0c16023e1815c6f2b7a5309 \
  --build-arg RAS_COMMANDER_WHEEL_SHA256=dc0c2f9baa9db66afee01e34eb00d7a04f53e7b82c3340c786b2e9aef1795932 \
  --label org.opencontainers.image.revision="$(git rev-parse HEAD)" \
  --tag local/hec-ras-wine-precompute_6.5:v5-review \
  --file containers/hecras-wine-precompute/Dockerfile .
```

The external `hecras_runtime` context supplies the installed files; the Dockerfile
places them at `/runtime/wine-seed`, owned by root and readable by the worker.
The `cpushim` stage compiles [cpushim.c](cpushim.c) with pinned `gcc` and
`libc6-dev` and checks that the library exports `sched_getcpu`; only the
compiled `cpushim.so` enters the image, at `/opt/hecras-prepare/cpushim.so`,
and `RAS_COMMANDER_WINE_CPU_SHIM` names it.
The entrypoint is `tini -- python /opt/hecras-prepare/prepare.py`. A normal job
uses its own writable prefix and runs without downloads or installation.

### 4. Validate the reconstructed image

The repository's `verify_bundled_runtime.sh` and `verify_windows_runtime.py`
check the selected installation and saved TCU state from a fresh runtime copy.
Use a Linux Docker host with `/dev/ntsync`; run as host UID 1000 or root. The
audit directory must be new and outside Git:

```bash
bash containers/hecras-wine-precompute/verify_bundled_runtime.sh \
  local/hec-ras-wine-precompute_6.5:v5-review 6.5 /scratch/hecras-audit-6.5-001
```

Then use the [run command](README.md#run-on-a-linux-filesystem) with `local/hec-ras-wine-precompute_6.5:v5-review`, `--pull never`, and a
disposable validation model. Require the expected three output files, a successful
receipt, no timeout, and no copied full-simulation result. Test with networking
disabled and no external runtime mount. Confirm that the receipt's
`wine_environment.cpu_shim` records `/opt/hecras-prepare/cpushim.so` and its
SHA-256. Repeat the sample in a CPU set that does not start at CPU 0 (for
example `docker run --cpuset-cpus 4,5 --cpus 2` or a two-CPU Slurm allocation
on CPUs other than 0-1): this is the condition that crashed `RasProcess.exe`
without the shim. Retain the build log, installed-software
inventory, TCU check, image identity, and sample-run evidence outside Git.

### Integrity checks recorded by the implementation

The runtime manifest contains SHA-256 file fingerprints. `prepare.py` reads the
declared runtime files at job startup and compares them with that inventory;
the Windows worker checks that its installed wheel matches the retained wheel.
The receipt also records fingerprints of the three generated output files,
which the host controller checks before staging them. These checks detect
changed runtime files or changed handoff files. They add file-reading work and
are an implementation choice for release traceability; HEC-RAS and Wine do not
need file hashing to perform preprocessing. They do not check hydraulic accuracy.

### Historical v4 reconstruction gaps

Independent reconstruction of the exact `v4` environment would need a tested
empty-prefix installation sequence, retrievable official installers and Python dependencies, locked
Winetricks/prerequisite versions, portable manifest creation, a distributable
validation fixture, and a clean-host rebuild test. The original HEC-RAS 6.5 setup
EXE identity is unavailable; a retained MSI-cache identity is recorded instead.
The prepared images are usable for the tested workflow while this reconstruction
work remains incomplete.

Use the corresponding HEC-RAS version and finalized profile to build 6.6 or 7.0.1.

### Installed software for reconstruction

The recorded inventory is common to the three tested bundled images except for the selected HEC-RAS installation. It contains 512 Linux packages, Linux Python and pip, 49 Windows Python distributions, and 24 Windows component registration records. This describes what is installed, not a minimal dependency list or an installer download lock file. Windows registration records can retain installation history.

| Component | Observed version or preparation |
|---|---|
| Linux base | Debian Trixie; Python base image pinned by digest in the Dockerfile. |
| Linux Python / pip | 3.13.15 / 26.2.1. |
| WineHQ stable | `11.0.0.0~trixie-1`, with 32-bit and 64-bit support. |
| Virtual display | Xvfb `2:21.1.16-1.3+deb13u4`, with xauth. |
| Process support | procps and tini, pinned in the Dockerfile. |
| Windows Python | 3.11.9, 64-bit, installed at `C:\Python311`. |
| Microsoft .NET | Framework 4.8, registered version `4.8.03761`; history includes the .NET 4.0 prerequisite. |
| Microsoft Visual C++ | 2010 x86/x64 `10.0.40219`; 2013 redistributables `12.0.30501.0` with `12.0.21005` components; 2015-2019 redistributables `14.24.28127.4` with `14.24.28127` components. |
| Windows drawing and fonts | Native GDI+ and core fonts installed through Winetricks; exact bootstrap installer revisions were not retained in this recipe. |
| Windows compatibility setting | Initialization history switches through Windows XP for prerequisite installation and ends at Windows 10. |
| [ras-commander][rc] | 0.99.2, installed from the retained installation wheel. |
| Windows Python dependencies | 49 distributions, including numpy, pandas, h5py, psutil, pywin32, pythonnet, and geospatial libraries. Every observed distribution version is listed below. |
| HEC-RAS | Only the selected 6.5, 6.6, or 7.0.1 program directory is retained in each release profile. |

Installed auxiliary packages such as `hms-commander` and `pathlib` were inherited
from the source environment. Their presence is recorded; this work does not
claim they are necessary for preprocessing or remove them without qualification.

### Windows Python distributions

These 49 distribution versions were the same in all three tested bundled runtimes.

| Package | Version |
|---|---|
| affine | `3.0.0` |
| attrs | `26.1.0` |
| certifi | `2026.7.22` |
| cffi | `2.1.1` |
| charset-normalizer | `3.5.1` |
| click | `8.4.2` |
| click-plugins | `1.1.1.2` |
| cligj | `0.7.2` |
| clr_loader | `0.2.10` |
| colorama | `0.4.6` |
| contourpy | `1.3.3` |
| cycler | `0.12.1` |
| fonttools | `4.63.0` |
| fsspec | `2026.7.0` |
| geopandas | `1.1.4` |
| h5py | `3.16.0` |
| hms-commander | `0.3.1` |
| idna | `3.19` |
| kiwisolver | `1.5.0` |
| matplotlib | `3.11.1` |
| numpy | `2.4.6` |
| packaging | `26.3` |
| pandas | `3.0.5` |
| pathlib | `1.0.1` |
| pefile | `2024.8.26` |
| pillow | `12.3.0` |
| pip | `24.0` |
| psutil | `7.2.2` |
| pycparser | `3.0` |
| pyogrio | `0.13.0` |
| pyparsing | `3.3.2` |
| pyproj | `3.7.2` |
| python-dateutil | `2.9.0.post0` |
| pythonnet | `3.0.5` |
| pywin32 | `312` |
| [ras-commander][rc] | `0.99.2` |
| rasterio | `1.4.4` |
| rasterstats | `0.21.0` |
| requests | `2.34.2` |
| rtree | `1.4.1` |
| scipy | `1.17.1` |
| setuptools | `65.5.0` |
| shapely | `2.1.2` |
| simplejson | `4.1.1` |
| six | `1.17.0` |
| tqdm | `4.70.0` |
| tzdata | `2026.3` |
| urllib3 | `2.7.0` |
| xarray | `2026.7.0` |

### Windows component registrations

These registration records describe the prepared profiles and can include installation history.

| Registered component | Version |
|---|---|
| Microsoft .NET Framework 4.8 | `4.8.03761` |
| Microsoft Visual C++ 2010  x64 Redistributable - 10.0.40219 | `10.0.40219` |
| Microsoft Visual C++ 2010  x86 Redistributable - 10.0.40219 | `10.0.40219` |
| Microsoft Visual C++ 2013 Redistributable (x64) - 12.0.30501 | `12.0.30501.0` |
| Microsoft Visual C++ 2013 Redistributable (x86) - 12.0.30501 | `12.0.30501.0` |
| Microsoft Visual C++ 2013 x64 Additional Runtime - 12.0.21005 | `12.0.21005` |
| Microsoft Visual C++ 2013 x64 Minimum Runtime - 12.0.21005 | `12.0.21005` |
| Microsoft Visual C++ 2013 x86 Additional Runtime - 12.0.21005 | `12.0.21005` |
| Microsoft Visual C++ 2013 x86 Minimum Runtime - 12.0.21005 | `12.0.21005` |
| Microsoft Visual C++ 2015-2019 Redistributable (x64) - 14.24.28127 | `14.24.28127.4` |
| Microsoft Visual C++ 2015-2019 Redistributable (x86) - 14.24.28127 | `14.24.28127.4` |
| Microsoft Visual C++ 2019 X64 Additional Runtime - 14.24.28127 | `14.24.28127` |
| Microsoft Visual C++ 2019 X64 Minimum Runtime - 14.24.28127 | `14.24.28127` |
| Microsoft Visual C++ 2019 X86 Additional Runtime - 14.24.28127 | `14.24.28127` |
| Microsoft Visual C++ 2019 X86 Minimum Runtime - 14.24.28127 | `14.24.28127` |
| Python 3.11.9 (64-bit) | `3.11.9150.0` |
| Python 3.11.9 Add to Path (64-bit) | `3.11.9150.0` |
| Python 3.11.9 Core Interpreter (64-bit) | `3.11.9150.0` |
| Python 3.11.9 Development Libraries (64-bit) | `3.11.9150.0` |
| Python 3.11.9 Executables (64-bit) | `3.11.9150.0` |
| Python 3.11.9 Standard Library (64-bit) | `3.11.9150.0` |
| Python 3.11.9 Tcl/Tk Support (64-bit) | `3.11.9150.0` |
| Python 3.11.9 Utility Scripts (64-bit) | `3.11.9150.0` |
| Python 3.11.9 pip Bootstrap (64-bit) | `3.11.9150.0` |

The [complete recorded inventory](https://github.com/gpt-cmdr/ras2fim-2d/blob/codex/phase2-linux-wine-preprocessing/containers/hecras-prepare/runtime-inventory-current.json) includes all
Linux packages and Windows dependencies, custom code identities, and runtime settings, for the published `v4` images.

### Custom code retained in the runtime

`prepare.py` and `windows_worker.py` are installed at `/opt/hecras-prepare/`.
An unused preparation helper remains at
`C:\ras2fim-runtime\verify_windows_runtime.py`; its exact source is
[profile_provenance_check_legacy.py](https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/profile_provenance_check_legacy.py).
It assumes HEC-RAS 6.5 and is not called by normal jobs. Use the repository's
[verify_windows_runtime.py](verify_windows_runtime.py), launched by
[verify_bundled_runtime.sh](verify_bundled_runtime.sh), for current three-version
qualification. Installer and run evidence locations are in
[v4 release verification](https://github.com/gpt-cmdr/ras-commander/blob/49d796f39f7ba2a3c136ee8129a22457743a32f3/containers/hecras-unsteady/RELEASE-CURRENT.md).

[rc]: https://rascommander.info/ras/
[rc-github]: https://github.com/gpt-cmdr/ras-commander
[tcu-status]: https://github.com/gpt-cmdr/ras-commander/blob/9e4217713e954236b0c16023e1815c6f2b7a5309/ras_commander/RasTcu.py
[tcu-accept]: https://github.com/gpt-cmdr/ras-commander/blob/9e4217713e954236b0c16023e1815c6f2b7a5309/ras_commander/RasTcu.py


## Reproduce the input-format regression checks

The input-format regression runner remains in ras2fim-2d at the pinned
commit; it is not part of this recipe. Run
[test_preprocessing_inputs.py](https://github.com/gpt-cmdr/ras2fim-2d/blob/dc60b219091e85bcb4564eca45313475c39ce58a/containers/hecras-prepare/test_preprocessing_inputs.py) from a ras2fim-2d checkout on a
Windows or Linux Docker host with a fresh external evidence directory. It makes separate disposable copies for LF,
CRLF, mixed line endings and missing dependencies. The first three must retain
the mesh and hydraulic tables; the missing-dependency case must fail without
changing the model files. The source sample is never modified.

```text
python containers/hecras-prepare/test_preprocessing_inputs.py --image rascommander/hec-ras-wine-precompute_6.5:v4 --source-project <absolute-spawned-sample.prj> --work-dir <new-external-evidence-directory>
```

The source project must have sibling `source_terrain` and `projection` folders
in its parent directory, as in `sample_data/sample_output/02_model_copies`.
The image Dockerfile includes [model_checks.py](model_checks.py) beside `windows_worker.py`;
both are required build inputs. Run the same checks for each released runtime.

[installed-package]: https://github.com/gpt-cmdr/ras-commander/tree/9e4217713e954236b0c16023e1815c6f2b7a5309/ras_commander
