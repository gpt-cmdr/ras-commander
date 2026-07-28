# Headless Linux/Wine Setup Runbook

## 1. Route each operation

Use the official HEC-RAS Linux `RasUnsteady`, `RasSteady`, or
`RasGeomPreprocess` executable when the installed version supports the required
operation. Use Wine only for Windows-only RasProcess/RASMapper functionality.
Keep native-Windows HEC-RAS as the engineering acceptance lane.

## 2. Build a controlled image

Pin the Linux distribution, Wine build, Python, ras-commander, ras2cng, GDAL,
and HEC-RAS version. Stage the approved HEC-RAS installation in accordance with
cluster policy; do not publish vendor binaries in a public image. A read-only
Apptainer image plus a per-task writable overlay/prefix is preferred.

For Ubuntu/Debian, install the WineHQ packages for the exact distribution,
`winetricks`, `cabextract`, X11/font libraries required by the HEC-RAS payload,
and native GDAL tools used after mapping. Do not use floating `latest` tags in a
qualified runner.

## 3. Initialize a 64-bit prefix

Create a template prefix during image provisioning, not concurrently in jobs:

```bash
export WINEARCH=win64
export WINEPREFIX=/opt/hecras-prefix-template
export DISPLAY=
export WINEDEBUG=-all
export WINEDLLOVERRIDES='mscoree,mshtml='
wineboot --init
winetricks -q dotnet48 gdiplus corefonts
wineboot --shutdown
```

Copy the complete Windows HEC-RAS installation tree into `drive_c`; partial DLL
lists are fragile across versions. Preserve `GDAL`, `x64`, `bin64`, and `bin32`
when present. Record a content fingerprint and never mix binaries from versions.

## 4. Provision TCU state safely

`RasTcu.status()` is read-only. When the operator has already accepted the same
installed version and explicitly authorizes reuse, invoke `RasTcu.accept()` in
the target Wine user/prefix or initialize with `accept_tcu=True`. This copies an
existing accepted VB6 registry subtree and writes an audit record. It does not
invent acceptance. If no donor exists, stop and report `no-donor-available`.

Never let an unknown-modal watchdog click the first button. Never bake a private
user registry hive into a broadly distributed image.

## 5. Make CPU topology coherent

Wine may report the online processor count while returning raw Linux CPU IDs.
On a sparse cpuset such as `2,5-7` with a reported count of four, CPU IDs 5–7 are
invalid Windows processor indices and can produce CLR `0x80131506`, access
violations, or non-returning RASMapper calls.

Run `headless_wine_preflight.py --require-safe-topology` inside the actual job
cgroup. Prefer visible CPUs `0..N-1` and enforce throughput with a CPU quota. In
Proxmox LXC, exposing the full zero-based set with `cores` and limiting aggregate
consumption with `cpulimit` passed qualification. Do not expand beyond scheduler
authorization.

If the namespace cannot be repaired, pin the whole Wine process tree to the
reported `single_cpu_fallback`. Fail if it is null.

## 6. Isolate each task

At task start:

```bash
task_root="${TMPDIR:-/tmp}/hecras-${SLURM_JOB_ID:-$$}-${SLURM_ARRAY_TASK_ID:-0}"
export WINEPREFIX="$task_root/wine"
export RAS_INSTALL_DIR="$WINEPREFIX/drive_c/HEC-RAS/7.0"
mkdir -p "$task_root/project" "$task_root/output"
cp -a /opt/hecras-prefix-template/. "$WINEPREFIX/"
cp -a /approved/model/. "$task_root/project/"
```

Use one active helper per prefix and `--map-workers 1`. Parallelize with job
arrays, each with an isolated prefix/project/output. Never share a writable HDF.

## 7. Configure and execute

Install ras-commander and ras2cng into a pinned Python environment. Call
`RasProcess.configure_wine()` with the task prefix and HEC-RAS install directory.
Run the preflight with that environment's Python and
`--require-python-packages`; save the resolved package versions in the receipt.
For mapping:

```bash
ras2cng map "$task_root/project" "$task_root/output/maps" \
  --ras-version 7.0 --rasprocess "$RAS_INSTALL_DIR" \
  --map-workers 1 --depth --wse --velocity --cog --fail-fast
```

Run Python/GDAL extraction natively on Linux after the Wine helper returns.

For Apptainer, keep the SIF read-only and bind only the isolated task root:

```bash
apptainer exec --cleanenv --containall \
  --bind "$task_root:/work" hecras-wine-qualified.sif \
  env WINEPREFIX=/work/wine RAS_INSTALL_DIR=/work/wine/drive_c/HEC-RAS/7.0 \
  python /opt/ras-commander/.claude/skills/hecras-setup-linux-wine-ras2cng/scripts/headless_wine_preflight.py \
  --require-safe-topology --require-runtime --require-python-packages
```

Stage licensed HEC-RAS files according to site policy; do not embed them in a
publicly redistributed image.

## 8. Capture a receipt

Save the preflight JSON, package versions, HEC-RAS tree fingerprint, input model
fingerprint, command, elapsed time, output hashes, and semantic content checks.
Do not promote the image or template prefix until the qualification reference
passes.
