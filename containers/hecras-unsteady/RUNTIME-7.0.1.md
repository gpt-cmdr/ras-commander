# Re-create the HEC-RAS 7.0.1 native runtime inputs

This recipe extracts the official HEC-RAS 7.0.1 Linux solver and libraries,
retains the vendor notices, and creates the external input used by
[Dockerfile](https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/Dockerfile). Run it on a Linux build machine. The extraction
steps read archive contents; they do not install or run HEC-RAS, require
Wine, or create a Wine profile. Keep the download, extracted files, and
runtime context outside the Git checkout.

The actual native `RasUnsteady` file contains the version banner
**HEC-RAS 7.0.1 June 2026**. Its identity was verified independently of the
installer filename. This is the native engine distributed with 7.0.1.
Image qualification and publication are recorded separately in the
[current release record](RELEASE-CURRENT.md).

## 1. Gather the source and extraction tools

Use the native image's source checkout at
`604704d440c49a39d6f6e8bae262e2233d895dd0`, which contains
[bundle_runtime.py](https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/bundle_runtime.py). The [extractor](https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/extract_installer.py)
is a source-side reconstruction utility. The command below downloads it from
that exact source revision into the external work directory. Use Python 3.11
or later for this recipe.

| Tool | Use and source | Tested version and license |
|---|---|---|
| [extract_installer.py](https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/extract_installer.py) | Bounded Python reader for the official installer's ISSetupStream v4 archive. Uses only the Python standard library. | Archive decoding follows [ISx source at `098e866`](https://github.com/Coldblackice/InstallShield-installer-extractor-ISx/blob/098e866fa5341db4424d3831d40943c01b88aefe/ISx.c); its [MIT license](https://github.com/Coldblackice/InstallShield-installer-extractor-ISx/blob/098e866fa5341db4424d3831d40943c01b88aefe/LICENSE) is retained in the Python file. |
| [7-Zip](https://www.7-zip.org/) | Inspects the MSI's embedded CAB and verifies its checksum. | 25.01; Debian package `25.01+dfsg-1~deb13u2`. See the [upstream license](https://www.7-zip.org/license.txt). |
| [msitools](https://github.com/GNOME/msitools) | `msiextract` restores filenames and directories from MSI tables; `msiinfo` exports identity and TCU records. | [Debian `0.106+repack-1`](https://packages.debian.org/trixie/msitools). The [source copyright file](https://github.com/GNOME/msitools/blob/master/copyright) identifies LGPL-2.1+ components and GPL-2+ tools, including `msiinfo`. |

On a Debian 13 builder, install the build-time tools, or use retained copies
of these package versions. They are not dependencies of the final image:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends \
  python3 curl ca-certificates \
  '7zip=25.01+dfsg-1~deb13u2' 'msitools=0.106+repack-1'
```

The original acquisition used `apt-get download` and `dpkg-deb -x` to retain
these tools outside the host package installation. Installing the same
versions on a dedicated builder supplies the same command-line tools and
their dependencies.

From the source checkout, select a new external directory with several
gigabytes free. Replace the example path before running the commands:

```bash
set -euo pipefail
export HEC701_WORK=/path/to/external/hecras-701-rebuild
test ! -e "$HEC701_WORK"
mkdir -p "$HEC701_WORK/downloads" "$HEC701_WORK/notices" "$HEC701_WORK/evidence"
git rev-parse HEAD > "$HEC701_WORK/evidence/reconstruction-source-commit.txt"
curl --fail --location \
  'https://raw.githubusercontent.com/gpt-cmdr/ras-commander/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/extract_installer.py' \
  --output "$HEC701_WORK/extract_installer.py"
```

## 2. Download the official combined installer

The [USACE downloads page](https://www.hec.usace.army.mil/software/hec-ras/download.aspx)
links the [7.0.1 Windows + Linux installer](https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/1.0.46/HEC-RAS_701_with_Linux_Setup.exe).
The [official GitHub release metadata](https://api.github.com/repos/HydrologicEngineeringCenter/hec-downloads/releases/tags/1.0.46)
also supplies its SHA256 digest.

```bash
curl --fail --location \
  'https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/1.0.46/HEC-RAS_701_with_Linux_Setup.exe' \
  --output "$HEC701_WORK/downloads/HEC-RAS_701_with_Linux_Setup.exe"
curl --fail --location \
  'https://api.github.com/repos/HydrologicEngineeringCenter/hec-downloads/releases/tags/1.0.46' \
  --output "$HEC701_WORK/evidence/official-release.json"
```

The following identities were verified during acquisition. The extractor
requires the exact installer digest and checks the extracted MSI digest.
These checks make the reconstruction refer to specific vendor bytes.

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `HEC-RAS_701_with_Linux_Setup.exe` | 327,742,168 | `f3d28695bd98cbc7a1bcb5bdaea073c5c512a071a22a9d3bfd90a3309f405003` |
| `HEC-RAS 7.0.1.msi` | 290,636,800 | `0aad915440bb8826386dfaa93b026c662ab6d5a0a73399a6efb90b452fb65e43` |
| MSI stream `Data1.cab` | 284,046,655 | `197ff46572c39d67ba159098b98dfe7b56134f9d3ce32bfbe7252cf5ba10324a` |
| Native `RasUnsteady` | 72,179,496 | `caae44088b52fb66cbfd7eeca92d0ec8a3f5d7abff2c03eea05e7fca344c250f` |

## 3. Extract the MSI and restore the vendor paths

[extract_installer.py](https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/extract_installer.py) locates the archive after the
PE sections, validates member boundaries and flat filenames, decodes the
ISSetupStream blocks, and checks each zlib stream. It writes all ten
installer members plus `extraction.json` through a temporary directory,
then makes the completed directory available. Existing output directories
are rejected.

```bash
python3 "$HEC701_WORK/extract_installer.py" \
  --installer "$HEC701_WORK/downloads/HEC-RAS_701_with_Linux_Setup.exe" \
  --output "$HEC701_WORK/setup"

export HEC701_MSI="$HEC701_WORK/setup/HEC-RAS 7.0.1.msi"
msiextract --list "$HEC701_MSI" > "$HEC701_WORK/evidence/msi-files.txt"
```

Check that the listed paths remain relative to the extraction directory,
then let `msiextract` apply the MSI's File, Component, and Directory tables:

```bash
python3 - <<'PY'
import os
from pathlib import Path, PurePosixPath
root = Path(os.environ["HEC701_WORK"])
for name in (root / "evidence/msi-files.txt").read_text().splitlines():
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"Unsafe MSI output path: {name}")
PY
mkdir "$HEC701_WORK/installed"
msiextract --directory "$HEC701_WORK/installed" "$HEC701_MSI" \
  > "$HEC701_WORK/evidence/msiextract.log"
for table in File Component Directory Property Control; do
  msiinfo export "$HEC701_MSI" "$table" \
    > "$HEC701_WORK/evidence/msi-$table.idt"
done

7z e -y "-o$HEC701_WORK/cab-audit" "$HEC701_MSI" Data1.cab \
  > "$HEC701_WORK/evidence/cab-extraction.log"
```

The MSI declares `ProductName=HEC-RAS 7.0.1`, `ProductVersion=7.0.1.0`, and
`ISReleaseFlags=LINUX`. Its native installed paths are:

```text
Program Files/HEC/HEC-RAS/7.0.1/Linux/Linux/
  RasUnsteady
  RasSteady
  RasGeomPreprocess
  run_helper.sh
  libs/
    libifcore.so.5, libifcoremt.so.5, libifport.so.5, ...
    mkl/
      libmkl_core.so.1, libmkl_intel_thread.so.1, ...
    rhel_8/
      libgfortran.so.5
      libquadmath.so.0
```

The repeated `Linux/Linux` directory is present in the vendor MSI. The
native tree contains 29 files totaling 770,000,899 bytes: three executables,
the vendor helper script, and 25 shared libraries. The clean compute context
selects only `RasUnsteady`, the complete `libs` tree, and notices.

## 4. Retain the notices and verify the selected input

Retain the official [release notes](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/latest),
[resolved issues](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/latest/resolved-issues),
[Linux engine documentation](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/7.0/working-with-hec-ras/linux-computation-engines),
[TCU](https://www.hec.usace.army.mil/software/terms_and_conditions.aspx), and
[distribution policy](https://www.hec.usace.army.mil/software/distribution_policy.aspx).
The manual's Linux page is under version `7.0`; the current release notes
identify the 7.0.1 release. The commands below save these pages and record
their acquisition hashes because live web pages can change.

Also retain the exact RTF text stored in the official MSI's
`Control` table at `LicenseAgreement` / `Memo`. This preserves the vendor
TCU supplied with this installer. Extraction does not change any acceptance
state in a separately prepared Wine profile.

```bash
export HEC701_NATIVE="$HEC701_WORK/installed/Program Files/HEC/HEC-RAS/7.0.1/Linux/Linux"
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen

root = Path(os.environ["HEC701_WORK"])
native = Path(os.environ["HEC701_NATIVE"])
expected = {
    root / "cab-audit/Data1.cab": "197ff46572c39d67ba159098b98dfe7b56134f9d3ce32bfbe7252cf5ba10324a",
    native / "RasUnsteady": "caae44088b52fb66cbfd7eeca92d0ec8a3f5d7abff2c03eea05e7fca344c250f",
}
for path, digest in expected.items():
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path
solver = (native / "RasUnsteady").read_bytes()
assert solver[:5] == b"\x7fELF\x02"
assert b"HEC-RAS 7.0.1 June 2026" in solver
files = sorted(path for path in native.rglob("*") if path.is_file())
assert len(files) == 29 and sum(path.stat().st_size for path in files) == 770000899
inventory = [{"path": path.relative_to(native).as_posix(),
              "size_bytes": path.stat().st_size,
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in files]
(root / "evidence/native-files.json").write_text(json.dumps(inventory, indent=2) + "\n")

pages = {
    "HEC-RAS-downloads.html": "https://www.hec.usace.army.mil/software/hec-ras/download.aspx",
    "HEC-RAS-7.0.1-release-notes.html": "https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/latest",
    "HEC-RAS-7.0.1-resolved-issues.html": "https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/latest/resolved-issues",
    "HEC-RAS-linux-computation-engines.html": "https://www.hec.usace.army.mil/confluence/rasdocs/rasum/7.0/working-with-hec-ras/linux-computation-engines",
    "USACE-Terms-and-Conditions.html": "https://www.hec.usace.army.mil/software/terms_and_conditions.aspx",
    "USACE-Distribution-Policy.html": "https://www.hec.usace.army.mil/software/distribution_policy.aspx",
}
acquired = []
for name, url in pages.items():
    with urlopen(url, timeout=60) as response:
        data = response.read()
    (root / "notices" / name).write_bytes(data)
    acquired.append({"file": name, "url": url, "sha256": hashlib.sha256(data).hexdigest()})
(root / "evidence/notice-sources.json").write_text(json.dumps(acquired, indent=2) + "\n")

control = (root / "evidence/msi-Control.idt").read_text()
start = control.index("{\\rtf1", control.index("LicenseAgreement\tMemo\t"))
depth, escaped, end = 0, False, None
for index in range(start, len(control)):
    char = control[index]
    if escaped:
        escaped = False
        continue
    if char == "\\":
        escaped = True
    elif char == "{":
        depth += 1
    elif char == "}":
        depth -= 1
        if depth == 0:
            end = index + 1
            break
assert end is not None
tcu = control[start:end].encode("utf-8")
assert hashlib.sha256(tcu).hexdigest() == "cbfaefaae3fb7ca96fbfa76fa86c85f2b7bfcbe11a2c237f68a6c3c42b50d6bf"
(root / "notices/HEC-RAS-7.0.1-Installer-TCU.rtf").write_bytes(tcu)
PY
```

## 5. Export the clean runtime context

Use [bundle_runtime.py](https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/containers/hecras-unsteady/bundle_runtime.py) from the source checkout:

```bash
python3 containers/hecras-unsteady/bundle_runtime.py \
  --engine-source "$HEC701_NATIVE" \
  --libraries-source "$HEC701_NATIVE/libs" \
  --notices-source "$HEC701_WORK/notices" \
  --hec-ras-version 7.0.1 \
  --output "$HEC701_WORK/runtime-context"
```

The output contains `runtime.json`, `engine/RasUnsteady`, `engine/libs/`,
and `notices/`. The manifest declares `"kind": "native"` and
`"hec_ras_version": "7.0.1"`. The bundler restores executable permissions,
inventories the selected files, and excludes the installer, MSI, CAB,
Windows application files, and model data from the image context.

Continue with the [container build and qualification steps](README.md#3-build-from-source-and-the-named-runtime-context),
using this directory for `hecras_runtime` and setting `HEC_RAS_VERSION=7.0.1`.
The image calls [RasCmdr.compute_plan_linux()](https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/ras_commander/RasCmdr.py)
through the [container worker](https://github.com/gpt-cmdr/ras-commander/blob/604704d440c49a39d6f6e8bae262e2233d895dd0/ras_commander/_container_compute.py).
Its library search path includes `libs`, `libs/mkl`, and `libs/rhel_8`,
matching the supplied vendor helper. `RasUnsteady` is an x86-64 ELF binary
with no embedded RPATH; its referenced glibc symbol versions reach
`GLIBC_2.17`.

## Reconstruction checks performed

The repository extractor was run against the retained official installer in
a fresh external directory. All ten resulting members matched the first
extraction by filename, byte count, and SHA256. MSI and CAB identities
matched the table above. The `msiextract` command reproduced all 29 native
files byte-for-byte, including the complete library directory structure.
No installer or solver was launched during those checks. These are runtime
input reconstruction checks; the separate release record covers actual
container and model execution.
