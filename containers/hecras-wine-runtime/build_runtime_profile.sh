#!/bin/bash
# Build a HEC-RAS Wine runtime profile (prefix/ + runtime.json) for one release
# on top of the shared base from build_base.sh, from the official installer.
#
# Usage: build_runtime_profile.sh <version> <HEC-RAS_Setup.exe> <ras-commander wheel> <out-dir>
#   version  install-folder name: 4.1.0, 5.0.7, 6.3.1, 6.6, 7.0.1, ...
#   RAS_COMMANDER_COMMIT (env) must name the commit the wheel was built from.
#   BASE (env) defaults to local/hecras-wine-base:py311-dotnet48.
#
# Steps: run the InstallShield launcher silently (it unpacks the HEC-RAS MSI),
# install that MSI with msiexec /qn, install the wheel into Windows Python,
# accept the HEC-RAS Terms and Conditions for Use through HEC-RAS's own dialog
# (accept_tcu.py; only for releases whose terms the operator has accepted) and
# verify by relaunch, then export the prefix and write runtime.json with
# SHA-256 records. The out-dir is the `hecras_runtime` build context of
# ../hecras-wine-precompute/Dockerfile (target `bundled`).
set -euo pipefail
VERSION=$1
INSTALLER=$(readlink -f -- "$2")
WHEEL_PATH=$(readlink -f -- "$3")
OUT=$4
COMMIT=${RAS_COMMANDER_COMMIT:?set RAS_COMMANDER_COMMIT}
BASE=${BASE:-local/hecras-wine-base:py311-dotnet48}
# HECRAS_MSI (env): an MSI already extracted from the installer (7.x combined
# installers: ../hecras-unsteady/extract_installer.py); skips the launcher.
MSI_MOUNT=()
if [ -n "${HECRAS_MSI:-}" ]; then
    MSI_MOUNT=(-v "$(readlink -f -- "$HECRAS_MSI"):/payload/hecras.msi:ro")
fi
DOCKER=${DOCKER:-docker}
HERE=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)

[[ "$VERSION" =~ ^[4-7]\.[0-9]+(\.[0-9]+)?$ ]] || { echo "error: version must be an install folder name" >&2; exit 2; }
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "error: RAS_COMMANDER_COMMIT must be a full commit" >&2; exit 2; }
[ -f "$INSTALLER" ] || { echo "error: installer not found: $2" >&2; exit 2; }
WHEEL=$(basename -- "$WHEEL_PATH")
[[ "$WHEEL" =~ ^ras_commander-[0-9][A-Za-z0-9.+]*-py3-none-any\.whl$ ]] || { echo "error: expected a ras_commander py3-none-any wheel" >&2; exit 2; }
[ ! -e "$OUT" ] || [ -z "$(ls -A "$OUT")" ] || { echo "error: out-dir must be absent or empty: $OUT" >&2; exit 2; }
mkdir -p "$OUT"
OUT=$(readlink -f -- "$OUT")

BUILDER=hecras-runtime-$(echo "$VERSION" | tr . -)-$$
trap '"$DOCKER" rm -f "$BUILDER" >/dev/null 2>&1 || true' EXIT
"$DOCKER" run -d --name "$BUILDER" --security-opt apparmor=unconfined \
    -v "$INSTALLER:/payload/setup.exe:ro" -v "$WHEEL_PATH:/payload/$WHEEL:ro" \
    -v "$HERE/accept_tcu.py:/payload/accept_tcu.py:ro" \
    "${MSI_MOUNT[@]}" \
    "$BASE" sleep infinity >/dev/null

"$DOCKER" exec -e VERSION="$VERSION" -e WHEEL="$WHEEL" "$BUILDER" bash -euo pipefail -c '
ras_dir="/build/prefix/drive_c/Program Files (x86)/HEC/HEC-RAS/$VERSION"
ras_win="C:\\Program Files (x86)\\HEC\\HEC-RAS\\$VERSION\\Ras.exe"
py="C:\\Python311\\python.exe"
runtime=/build/prefix/drive_c/ras-commander-runtime
mkdir -p "$runtime"
cp /payload/setup.exe /tmp/setup.exe
if [ -f /payload/hecras.msi ]; then
    echo "== msiexec (pre-extracted MSI)"
    cp /payload/hecras.msi /tmp/hecras.msi
    timeout 2400 xvfb-run -a wine msiexec /i "Z:\\tmp\\hecras.msi" /qn /norestart "/l*v" "Z:\\tmp\\msi.log"
    wineserver -w || true
fi
[ -f "$ras_dir/Ras.exe" ] || {
echo "== launcher"
# Launchers normally install through msiexec themselves. Some instead unpack
# the MSI and then wait on a prerequisite download with no installer running.
# Stop a launcher only in that state (MSI unpacked, no msiexec for 60 s, after
# five minutes); interrupting an install in progress leaves a broken one.
xvfb-run -a wine /tmp/setup.exe /s /v"/qn /norestart" > /tmp/launcher.log 2>&1 &
launcher=$!
idle=0
for second in $(seq 1 3600); do
    kill -0 "$launcher" 2>/dev/null || break
    if pgrep -fi "msiexec" >/dev/null; then idle=0; else idle=$((idle + 1)); fi
    if [ ! -f "$ras_dir/Ras.exe" ] && [ "$second" -ge 300 ] && [ "$idle" -ge 60 ] \
        && find /build/prefix/drive_c/users -iname "HEC-RAS*.msi" -newer /tmp/setup.exe | grep -q .; then
        echo "launcher idle after ${second}s with its MSI unpacked and no installer running; stopping it"
        break
    fi
    sleep 1
done
kill "$launcher" 2>/dev/null || true
wineserver -k || true
wineserver -w || true
}
if [ ! -f "$ras_dir/Ras.exe" ]; then
    msi=$(find /build/prefix/drive_c/users -iname "HEC-RAS*.msi" -newer /tmp/setup.exe | head -n1)
    [ -n "$msi" ] || { echo "error: launcher installed nothing and unpacked no HEC-RAS MSI" >&2; exit 3; }
    cp "$msi" /tmp/hecras.msi
    echo "== msiexec $(basename "$msi")"
    timeout 2400 xvfb-run -a wine msiexec /i "Z:\\tmp\\hecras.msi" /qn /norestart "/l*v" "Z:\\tmp\\msi.log"
    wineserver -w || true
fi
if [ ! -f "$ras_dir/Ras.exe" ]; then
    echo "error: Ras.exe not installed at $ras_dir; found:" >&2
    find "/build/prefix/drive_c/Program Files (x86)/HEC" -iname ras.exe >&2 || true
    exit 4
fi
# Example projects are test data, not runtime: export them beside the profile.
if [ -d "$ras_dir/Example Projects" ]; then
    mkdir -p /build/examples
    mv "$ras_dir/Example Projects" /build/examples/raw
    find /build/examples/raw -maxdepth 1 -iname "Example_Projects*.exe" -print0 \
        | while IFS= read -r -d "" archive; do 7z x -y -o/build/examples/projects "$archive" >/dev/null; rm -f "$archive"; done
    [ -d /build/examples/projects ] || mv /build/examples/raw /build/examples/projects
    rm -rf /build/examples/raw
fi
echo "== ras-commander"
cp "/payload/$WHEEL" "$runtime/$WHEEL"
xvfb-run -a wine "$py" -m pip install -q --disable-pip-version-check --no-index --no-deps \
    --force-reinstall --no-compile "C:\\ras-commander-runtime\\$WHEEL"
xvfb-run -a wine "$py" -c "import ras_commander, sys; print(\"windows ras_commander\", ras_commander.__version__)"
echo "== terms and conditions"
cp /payload/accept_tcu.py "$runtime/accept_tcu.py"
xvfb-run -a wine "$py" "C:\\ras-commander-runtime\\accept_tcu.py" "$ras_win" \
    "C:\\ras-commander-runtime\\tcu-probe.json" \
    || { cat "$runtime/tcu-probe.json" >&2 || true; echo "error: TCU acceptance was not verified" >&2; exit 5; }
RAS_COMMANDER_TCU_PROBE="C:\\ras-commander-runtime\\tcu-probe.json" xvfb-run -a wine "$py" -c \
    "from ras_commander import RasTcu; s = RasTcu.status(ras_version=r\"$ras_win\"); print(s); assert s.accepted is True"
wineserver -k || true; wineserver -w || true
rm -rf /build/prefix/drive_c/users/root/AppData/Local/Temp/* /build/prefix/drive_c/windows/temp/* /tmp/setup.exe
echo PROFILE-OK
'
echo "== export prefix"
"$DOCKER" cp "$BUILDER:/build/prefix" "$OUT/prefix"
if "$DOCKER" exec "$BUILDER" test -d /build/examples/projects; then
    "$DOCKER" cp "$BUILDER:/build/examples/projects" "$OUT-examples"
fi
python3 - "$OUT" "$VERSION" "$COMMIT" "$WHEEL" <<'PY'
import hashlib, json, sys
from pathlib import Path
out, version, commit, wheel = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
paths = [
    "prefix/drive_c/Python311/python.exe",
    f"prefix/drive_c/ras-commander-runtime/{wheel}",
    f"prefix/drive_c/Program Files (x86)/HEC/HEC-RAS/{version}/Ras.exe",
    "prefix/drive_c/ras-commander-runtime/tcu-probe.json",
]
artifacts = [{"path": p, "sha256": sha(out / p)} for p in paths]
manifest = {
    "schema": "ras-commander-runtime/v1",
    "kind": "wine",
    "hec_ras_version": version,
    "ras_commander": {"commit": commit, "wheel_sha256": artifacts[1]["sha256"]},
    "artifacts": artifacts,
    "wine": {
        "prefix_seed": "prefix",
        "windows_python": "C:\\Python311\\python.exe",
        "ras_executable": f"C:\\Program Files (x86)\\HEC\\HEC-RAS\\{version}\\Ras.exe",
        "ras_commander_wheel": f"C:\\ras-commander-runtime\\{wheel}",
        "tcu_probe": "C:\\ras-commander-runtime\\tcu-probe.json",
    },
    "source": {"installer_sha256": None},
}
(out / "runtime.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print("runtime.json", out / "runtime.json")
PY
python3 - "$OUT/runtime.json" "$(sha256sum -- "$INSTALLER" | cut -d' ' -f1)" "$(basename -- "$INSTALLER")" <<'PY'
import json, sys
path, digest, name = sys.argv[1:]
data = json.load(open(path))
data["source"] = {"installer": name, "installer_sha256": digest}
open(path, "w").write(json.dumps(data, indent=2) + "\n")
PY
du -sh "$OUT/prefix"
