#!/bin/bash
# Build a portable ras-commander Wine executor image from a pinned
# rascommander/hec-ras-wine-precompute_<version> base image.
#
# The derivative:
#  - installs one ras-commander wheel into BOTH the Linux Python (with its
#    "compute" dependencies) and the Wine Windows Python C:\Python311
#    (--no-deps; the base profile already holds the Windows dependencies);
#  - adds the RasMapperLib GDAL bridge C:\Python311\GDAL ->
#    ../Program Files (x86)/HEC/HEC-RAS/<version>/GDAL (a relative link, so it
#    survives the per-task copy of the seed prefix);
#  - installs the CPU-numbering shim at /opt/ras-commander-executor/cpushim.so,
#    copied from the base (/opt/hecras-prepare/cpushim.so, v5 and later) or
#    compiled from ../hecras-wine-precompute/cpushim.c in the Dockerfile's
#    throwaway "cpushim" stage when the base has none (v4);
#  - sets the portable executor contract read by
#    ras_commander.remote.execute_request: RAS_COMMANDER_WINE_PREFIX_SEED,
#    RAS_COMMANDER_WINE_PYTHON, RAS_COMMANDER_WINE_ARCH and
#    RAS_COMMANDER_WINE_CPU_SHIM.
#
# BuildKit cannot run Wine here, so the layer is made by run-and-commit. The
# image is then verified: both Pythons import ras_commander from a fresh
# task-private copy of the seed prefix.
#
# Usage:
#   RAS_COMMANDER_COMMIT=<40-hex commit of the wheel source> \
#     build_executor_image.sh <hec-ras-version> <base-image@sha256:...> \
#       <ras_commander-*-py3-none-any.whl> <tag> [<pip-constraints-file>]
#
# Optional environment: DOCKER (default docker), BUILD_CPUS (default 2),
# WINE_SECURITY_OPT (default apparmor=unconfined; empty to omit).
set -euo pipefail

usage() {
    sed -n '/^# Usage:/,/^# WINE_SECURITY_OPT/p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
}
[ "$#" -eq 4 ] || [ "$#" -eq 5 ] || usage

VERSION=$1
BASE=$2
WHEEL_PATH=$(readlink -f -- "$3")
TAG=$4
CONSTRAINTS=${5:+$(readlink -f -- "$5")}
COMMIT=${RAS_COMMANDER_COMMIT:?set RAS_COMMANDER_COMMIT to the full commit the wheel was built from}
DOCKER=${DOCKER:-docker}
BUILD_CPUS=${BUILD_CPUS:-2}
WINE_SECURITY_OPT=${WINE_SECURITY_OPT-apparmor=unconfined}

case "$VERSION" in 6.5|6.6|7.0.1) ;; *) echo "error: HEC-RAS version must be 6.5, 6.6 or 7.0.1" >&2; exit 2 ;; esac
[[ "$BASE" =~ ^[a-z0-9][a-z0-9._/:-]*@sha256:[0-9a-f]{64}$ ]] \
    || { echo "error: base image must be pinned by digest (name@sha256:<64 hex>)" >&2; exit 2; }
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "error: RAS_COMMANDER_COMMIT must be a full 40-hex commit" >&2; exit 2; }
[[ "$TAG" =~ ^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]] \
    || { echo "error: tag must be <repository>:<tag>" >&2; exit 2; }
[ -f "$WHEEL_PATH" ] || { echo "error: wheel not found: $3" >&2; exit 2; }
WHEEL=$(basename -- "$WHEEL_PATH")
[[ "$WHEEL" =~ ^ras_commander-([0-9][A-Za-z0-9.+]*)-py3-none-any\.whl$ ]] \
    || { echo "error: expected a pure-Python ras_commander-<version>-py3-none-any.whl" >&2; exit 2; }
WHEEL_VERSION=${BASH_REMATCH[1]}
if [ -n "$CONSTRAINTS" ] && [ ! -f "$CONSTRAINTS" ]; then
    echo "error: constraints file not found: $5" >&2; exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)
PRECOMPUTE_DIR=$(cd -- "$SCRIPT_DIR/../hecras-wine-precompute" && pwd)
WHEEL_SHA=$(sha256sum -- "$WHEEL_PATH" | cut -d' ' -f1)
RECIPE_SHA=$(sha256sum -- "$0" | cut -d' ' -f1)
SEED=/runtime/wine-seed/prefix
SHIM=/opt/ras-commander-executor/cpushim.so
SECURITY=()
[ -n "$WINE_SECURITY_OPT" ] && SECURITY=(--security-opt "$WINE_SECURITY_OPT")

WORK=$(mktemp -d)
BUILDER=ras-commander-executor-build-$$
cleanup() {
    "$DOCKER" rm -f "$BUILDER" >/dev/null 2>&1 || true
    rm -rf -- "$WORK"
}
trap cleanup EXIT

"$DOCKER" image inspect "$BASE" >/dev/null 2>&1 || "$DOCKER" pull "$BASE"
BASE_ID=$("$DOCKER" image inspect --format '{{.Id}}' "$BASE")

# The base must be the Wine image for the requested HEC-RAS version
# (RAS_COMMANDER_PREPARE_* from this recipe, RAS2FIM_* in the published v4).
BASE_VERSION=$("$DOCKER" image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$BASE" \
    | sed -n -e 's/^RAS_COMMANDER_PREPARE_HECRAS_VERSION=//p' -e 's/^RAS2FIM_HECRAS_VERSION=//p' | head -n1)
[ "$BASE_VERSION" = "$VERSION" ] \
    || { echo "error: base image declares HEC-RAS '${BASE_VERSION:-none}', not $VERSION" >&2; exit 2; }

# Prefer the base image's own shim; otherwise compile one in the pinned,
# throwaway Dockerfile stage. The compiler never enters the executor image.
if "$DOCKER" run --rm --entrypoint /bin/sh "$BASE" -c 'test -f /opt/hecras-prepare/cpushim.so'; then
    SHIM_SOURCE=base
    SHIM_MOUNT=()
else
    SHIM_SOURCE=built
    mkdir -p "$WORK/context/containers/hecras-wine-precompute" "$WORK/shim"
    cp -- "$PRECOMPUTE_DIR/cpushim.c" "$WORK/context/containers/hecras-wine-precompute/cpushim.c"
    "$DOCKER" buildx build --platform linux/amd64 --target cpushim-artifact \
        --file "$PRECOMPUTE_DIR/Dockerfile" --output "type=local,dest=$WORK/shim" "$WORK/context"
    [ -f "$WORK/shim/cpushim.so" ] || { echo "error: cpushim build produced no library" >&2; exit 1; }
    SHIM_MOUNT=(-v "$WORK/shim/cpushim.so:/tmp/build-shim/cpushim.so:ro")
fi
CONSTRAINT_MOUNT=()
CONSTRAINT_ARG=""
if [ -n "$CONSTRAINTS" ]; then
    CONSTRAINT_MOUNT=(-v "$CONSTRAINTS:/tmp/build-constraints.txt:ro")
    CONSTRAINT_ARG="-c /tmp/build-constraints.txt"
fi

echo "== build layer from $BASE ($BASE_ID), cpushim: $SHIM_SOURCE"
"$DOCKER" run --name "$BUILDER" --user root "${SECURITY[@]}" --cpus "$BUILD_CPUS" \
    -v "$WHEEL_PATH:/tmp/build-wheel/$WHEEL:ro" "${SHIM_MOUNT[@]}" "${CONSTRAINT_MOUNT[@]}" \
    --env "WHEEL=$WHEEL" --env "VERSION=$VERSION" --env "SEED=$SEED" --env "SHIM=$SHIM" \
    --env "CONSTRAINT_ARG=$CONSTRAINT_ARG" \
    --entrypoint /bin/bash "$BASE" -c '
set -euo pipefail
python -m pip install --no-cache-dir --disable-pip-version-check $CONSTRAINT_ARG "/tmp/build-wheel/$WHEEL[compute]"
python -m pip check

export WINEPREFIX=$SEED WINEARCH=win64 WINEDEBUG=-all HOME=/tmp/build-home
mkdir -p "$HOME"
windows_wheel=$(winepath -w "/tmp/build-wheel/$WHEEL")
xvfb-run -a wine "C:\\Python311\\python.exe" -m pip install \
    --no-index --no-deps --no-cache-dir --disable-pip-version-check \
    --force-reinstall --no-compile "$windows_wheel"
wineserver -k || true
wineserver -w || true

cd "$SEED/drive_c/Python311"
target="../Program Files (x86)/HEC/HEC-RAS/$VERSION/GDAL"
[ -d "$target" ] || { echo "error: HEC-RAS $VERSION GDAL directory missing: $target" >&2; exit 1; }
if [ -L GDAL ] || [ -e GDAL ]; then
    [ "$(readlink GDAL)" = "$target" ] || { echo "error: C:\\Python311\\GDAL exists and is not the bridge" >&2; exit 1; }
else
    ln -s "$target" GDAL
fi

if [ -f /tmp/build-shim/cpushim.so ]; then shim_src=/tmp/build-shim/cpushim.so; else shim_src=/opt/hecras-prepare/cpushim.so; fi
install -D -m 0644 "$shim_src" "$SHIM"
python - "$SHIM" <<"PY"
import sys
with open(sys.argv[1], "rb") as handle:
    header = handle.read(20)
assert header[:4] == b"\x7fELF" and header[4] == 2 and header[18] == 0x3E, "cpushim.so is not an x86-64 ELF"
PY

# Root-owned, world-readable seed: every task copies it into private scratch.
# Touch only entries that differ: overlayfs copies every file chown/chmod
# touches into the new layer, so a blanket recursive change duplicates the
# whole multi-GB prefix (observed: a 4.9 GB layer).
find "$SEED" \( ! -user root -o ! -group root \) -exec chown -h root:root {} +
find "$SEED" -type d ! -perm 755 -exec chmod 755 {} +
find "$SEED" -type f \( ! -perm -u=rw -o ! -perm -g=r -o ! -perm -o=r -o -perm /go=w \) -exec chmod u+rw,go+r,go-w {} +
rm -rf /tmp/build-home
echo LAYER-OK
'

"$DOCKER" commit \
    --change "ENV RAS_COMMANDER_WINE_PREFIX_SEED=$SEED" \
    --change 'ENV RAS_COMMANDER_WINE_PYTHON=C:\\Python311\\python.exe' \
    --change 'ENV RAS_COMMANDER_WINE_ARCH=win64' \
    --change "ENV RAS_COMMANDER_WINE_CPU_SHIM=$SHIM" \
    --change "LABEL org.opencontainers.image.title=\"HEC-RAS $VERSION portable Wine executor through ras-commander\"" \
    --change 'LABEL org.opencontainers.image.source=https://github.com/gpt-cmdr/ras-commander' \
    --change "LABEL org.opencontainers.image.revision=$COMMIT" \
    --change "LABEL org.opencontainers.image.base.name=$BASE" \
    --change "LABEL org.opencontainers.image.base.digest=${BASE##*@}" \
    --change 'LABEL io.ras-commander.role=portable-wine-executor' \
    --change "LABEL io.ras-commander.hec-ras-version=$VERSION" \
    --change "LABEL io.ras-commander.commit=$COMMIT" \
    --change "LABEL io.ras-commander.wheel=$WHEEL" \
    --change "LABEL io.ras-commander.wheel-sha256=$WHEEL_SHA" \
    --change "LABEL io.ras-commander.parent-image=$BASE" \
    --change "LABEL io.ras-commander.parent-image-id=$BASE_ID" \
    --change 'LABEL io.ras-commander.gdal-bridge=C:/Python311/GDAL' \
    --change "LABEL io.ras-commander.cpu-shim=$SHIM" \
    --change "LABEL io.ras-commander.cpu-shim-source=$SHIM_SOURCE" \
    --change "LABEL io.ras-commander.executor-recipe-sha256=$RECIPE_SHA" \
    --change 'ENTRYPOINT ["/usr/bin/tini", "--"]' \
    --change 'CMD ["python", "-m", "ras_commander.remote.execute_request", "--help"]' \
    --change 'WORKDIR /job' \
    --change 'USER rasworker' \
    "$BUILDER" "$TAG" >/dev/null
"$DOCKER" rm "$BUILDER" >/dev/null

echo "== verify $TAG"
"$DOCKER" run --rm "${SECURITY[@]}" --cpus "$BUILD_CPUS" --network none \
    --env "EXPECTED_VERSION=$WHEEL_VERSION" --env "EXPECTED_SEED=$SEED" --env "EXPECTED_SHIM=$SHIM" \
    --entrypoint /bin/bash "$TAG" -c '
set -euo pipefail
python - <<"PY"
import os
from pathlib import Path
import ras_commander
expected = {
    "RAS_COMMANDER_WINE_PREFIX_SEED": os.environ["EXPECTED_SEED"],
    "RAS_COMMANDER_WINE_PYTHON": "C:\\Python311\\python.exe",
    "RAS_COMMANDER_WINE_ARCH": "win64",
    "RAS_COMMANDER_WINE_CPU_SHIM": os.environ["EXPECTED_SHIM"],
}
for name, value in expected.items():
    assert os.environ.get(name) == value, (name, os.environ.get(name), value)
seed = Path(expected["RAS_COMMANDER_WINE_PREFIX_SEED"])
assert seed.is_dir() and not seed.is_symlink(), seed
shim = Path(expected["RAS_COMMANDER_WINE_CPU_SHIM"])
assert shim.is_file() and not shim.is_symlink(), shim
assert ras_commander.__version__ == os.environ["EXPECTED_VERSION"], ras_commander.__version__
print("linux ras_commander", ras_commander.__version__)
PY
python -m ras_commander.remote.execute_request --help >/dev/null
private=$(mktemp -d)/prefix
cp -a "$RAS_COMMANDER_WINE_PREFIX_SEED" "$private"
ls -ld "$private/drive_c/Python311/GDAL/"
export WINEPREFIX=$private WINEARCH=$RAS_COMMANDER_WINE_ARCH WINEDEBUG=-all \
    WINEDLLOVERRIDES=winedbg.exe=d LD_PRELOAD=$RAS_COMMANDER_WINE_CPU_SHIM
version=$(xvfb-run -a wine "$RAS_COMMANDER_WINE_PYTHON" -c "import ras_commander, ras_commander.remote.execute_request; print(ras_commander.__version__)" 2>/dev/null | tr -d "\r" | tail -n1)
wineserver -w || true
echo "windows ras_commander $version"
[ "$version" = "$EXPECTED_VERSION" ] || { echo "error: Windows Python imported ras_commander ${version:-none}" >&2; exit 1; }
echo VERIFY-OK
'
echo "image: $TAG $("$DOCKER" image inspect --format '{{.Id}}' "$TAG")"
echo "wheel: $WHEEL sha256 $WHEEL_SHA commit $COMMIT"
echo "parent: $BASE"
echo "cpushim: $SHIM ($SHIM_SOURCE)"
