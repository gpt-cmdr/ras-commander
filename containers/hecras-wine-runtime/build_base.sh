#!/bin/bash
# Build the shared Wine base for HEC-RAS runtime profiles, from an empty prefix:
# .NET Framework 4.8, gdiplus, core fonts, Windows 10 mode, and Windows Python
# 3.11.9 with ras-commander's compute dependencies. Every HEC-RAS version is
# then installed on top of this one base (build_runtime_profile.sh).
#
# Usage: build_base.sh [tag]   (default local/hecras-wine-base:py311-dotnet48)
# Needs a Linux Docker host that can run Wine (apparmor=unconfined) and network
# access to winetricks downloads, python.org and PyPI.
set -euo pipefail
TAG=${1:-local/hecras-wine-base:py311-dotnet48}
DOCKER=${DOCKER:-docker}
HERE=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)
TOOLCHAIN=local/hecras-wine-toolchain:trixie-wine11
PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
PYTHON_SHA256=5ee42c4eee1e6b4464bb23722f90b45303f79442df63083f05322f1785f5fdde
PIP_PINS="h5py==3.16.0 numpy==2.4.6 pandas==3.0.6 psutil==7.2.2 python-dateutil==2.9.0.post0"
BUILDER=hecras-wine-base-build-$$
trap '"$DOCKER" rm -f "$BUILDER" >/dev/null 2>&1 || true' EXIT

"$DOCKER" build -t "$TOOLCHAIN" -f "$HERE/Dockerfile.toolchain" "$HERE"
"$DOCKER" run -d --name "$BUILDER" --security-opt apparmor=unconfined \
    -e WINEARCH=win64 -e WINEPREFIX=/build/prefix -e WINEDEBUG=-all \
    -e "WINEDLLOVERRIDES=mscoree,mshtml,winemenubuilder.exe,winedbg.exe=" \
    "$TOOLCHAIN" sleep infinity >/dev/null
"$DOCKER" exec "$BUILDER" bash -euo pipefail -c "
mkdir -p /build/prefix /build/payload
xvfb-run -a wineboot --init; wineserver -w
xvfb-run -a winetricks -q dotnet48; wineserver -w
xvfb-run -a winetricks -q gdiplus corefonts; wineserver -w
xvfb-run -a winecfg -v win10; wineserver -w
wget -qO /build/payload/python.exe '$PYTHON_URL'
echo '$PYTHON_SHA256  /build/payload/python.exe' | sha256sum -c -
# .NET must load for HEC-RAS; mscoree was disabled only for wineboot.
export WINEDLLOVERRIDES='winemenubuilder.exe,winedbg.exe='
xvfb-run -a wine /build/payload/python.exe /quiet InstallAllUsers=1 PrependPath=0 \
    AssociateFiles=0 Shortcuts=0 Include_test=0 Include_launcher=0 Include_doc=0 \
    Include_tcltk=0 Include_dev=0 Include_tools=0 'TargetDir=C:\\Python311'
wineserver -w
test -f /build/prefix/drive_c/Python311/python.exe
xvfb-run -a wine 'C:\\Python311\\python.exe' -m pip install -q --disable-pip-version-check $PIP_PINS
xvfb-run -a wine 'C:\\Python311\\python.exe' -m pip freeze --all > /build/windows-python-packages.txt
wineserver -k || true; wineserver -w || true
rm -rf /build/payload /root/.cache/winetricks
echo BASE-OK
"
"$DOCKER" commit \
    --change 'ENV WINEDLLOVERRIDES=winemenubuilder.exe,winedbg.exe=' \
    --change 'LABEL io.ras-commander.role=hecras-wine-base' \
    --change "LABEL io.ras-commander.windows-python=3.11.9" \
    --change "LABEL io.ras-commander.base-recipe-sha256=$(sha256sum -- "$0" | cut -d' ' -f1)" \
    "$BUILDER" "$TAG" >/dev/null
echo "base: $TAG $("$DOCKER" image inspect --format '{{.Id}}' "$TAG")"
