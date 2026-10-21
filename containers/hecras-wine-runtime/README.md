# HEC-RAS Wine runtime build

These scripts build the Wine images for one Windows HEC-RAS release (5.0 through 7.x) from
HEC's official installer, on a Linux Docker host that can run Wine.

| File | Purpose |
| --- | --- |
| `Dockerfile.toolchain` | Debian trixie with WineHQ 11, winetricks, Xvfb, cabextract, 7-Zip, and msitools. |
| `build_base.sh` | Shared base prefix: .NET Framework 4.8, gdiplus, core fonts, Windows 10 mode, Windows Python 3.11.9 with pinned compute dependencies. Built once. |
| `build_runtime_profile.sh` | Installs one release into a copy of the base, installs the ras-commander wheel into Windows Python, accepts the HEC-RAS terms through HEC-RAS's own dialog (`accept_tcu.py`), and writes `runtime.json` with SHA-256 records. |
| `build_release_images.sh` | Profile → `hec-ras-wine-precompute_<version>:v5-<commit>` → `hec-ras-wine-executor_<version>:<commit>` → `docker save` archives with `.sha256` and `.image-id` sidecars, plus the release's example projects as test data. |
| `accept_tcu.py` | Accepts the Terms and Conditions for Use dialog of one installed `Ras.exe` and verifies it by relaunching. |

```bash
CI=1 python -m pip wheel --no-deps --wheel-dir /tmp/rc-wheel .
bash containers/hecras-wine-runtime/build_base.sh
RAS_COMMANDER_COMMIT=$(git rev-parse HEAD) \
bash containers/hecras-wine-runtime/build_release_images.sh 6.6 HEC-RAS_66_Setup.exe \
  /tmp/rc-wheel/ras_commander-<version>-py3-none-any.whl work/ archives/
```

For 7.x combined installers, extract the MSI with
[`../hecras-unsteady/extract_installer.py`](../hecras-unsteady/extract_installer.py) and pass
`HECRAS_MSI=<file.msi>`. HEC-RAS 6.0 and earlier record their terms acceptance per machine;
their images need `RAS_COMMANDER_WINE_ACCEPT_TCU=1` in each task.

Building an image accepts HEC's terms on behalf of its users. See
[Apptainer images](../../docs/user-guide/apptainer-images.md) for the release matrix, the terms
policy, SIF conversion, and qualification results.
