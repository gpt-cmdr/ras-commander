#!/bin/bash
# Build the Wine images for one HEC-RAS release from its official installer:
#   1. runtime profile (build_runtime_profile.sh)
#   2. pre-compute image  hec-ras-wine-precompute_<version> (../hecras-wine-precompute, target bundled)
#   3. portable executor  hec-ras-wine-executor_<version>   (../hecras-wine-executor)
#   4. docker-save archives with .sha256 sidecars in <archive-dir>. The pre-compute
#      image is the executor's base; it is archived only for releases with a HEC
#      Linux engine (5.0.7, 6.1, 6.5, 6.6, 7.x), the only ones it serves.
#
# Usage: build_release_images.sh <version> <HEC-RAS_Setup.exe> <ras-commander wheel> <work-dir> <archive-dir>
# Env: RAS_COMMANDER_COMMIT (required; the commit the wheel was built from), DOCKER,
#      KEEP_IMAGES=1 to keep the local images after saving.
set -euo pipefail
VERSION=$1
INSTALLER=$(readlink -f -- "$2")
WHEEL=$(readlink -f -- "$3")
WORK=$4
ARCHIVES=$5
COMMIT=${RAS_COMMANDER_COMMIT:?set RAS_COMMANDER_COMMIT}
DOCKER=${DOCKER:-docker}
HERE=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)
CONTAINERS=$(cd -- "$HERE/.." && pwd)
SHORT=${COMMIT:0:12}
PROFILE="$WORK/profile-$VERSION"
CONTEXT="$WORK/context-$VERSION"
PRECOMPUTE_TAG="local/hec-ras-wine-precompute_$VERSION:v5-$SHORT"
EXECUTOR_TAG="local/hec-ras-wine-executor_$VERSION:$SHORT"
case "$VERSION" in
    5.0.7|6.1|6.5|6.6|7.*) SAVE_TAGS=("$PRECOMPUTE_TAG" "$EXECUTOR_TAG") ;;
    *) SAVE_TAGS=("$EXECUTOR_TAG") ;;
esac
mkdir -p "$WORK" "$ARCHIVES"
cleanup() { rm -rf -- "$PROFILE" "$PROFILE-examples" "$CONTEXT"; }
trap cleanup EXIT

echo "== [$VERSION] runtime profile"
rm -rf -- "$PROFILE"
bash "$HERE/build_runtime_profile.sh" "$VERSION" "$INSTALLER" "$WHEEL" "$PROFILE"

if [ -d "$PROFILE-examples" ]; then
    EXAMPLES="hec-ras-examples_${VERSION}_${SHORT}.tar.gz"
    tar -czf "$ARCHIVES/$EXAMPLES" -C "$PROFILE-examples" .
    (cd "$ARCHIVES" && sha256sum "$EXAMPLES" > "$EXAMPLES.sha256")
    rm -rf -- "$PROFILE-examples"
fi

echo "== [$VERSION] pre-compute image"
rm -rf -- "$CONTEXT"
mkdir -p "$CONTEXT/containers"
cp -a "$CONTAINERS/hecras-wine-precompute" "$CONTEXT/containers/"
WHEEL_SHA=$(sha256sum -- "$WHEEL" | cut -d' ' -f1)
"$DOCKER" buildx build --load --target bundled \
    --file "$CONTEXT/containers/hecras-wine-precompute/Dockerfile" \
    --build-context "hecras_runtime=$PROFILE" \
    --build-arg "HEC_RAS_VERSION=$VERSION" \
    --build-arg "RAS_COMMANDER_COMMIT=$COMMIT" \
    --build-arg "RAS_COMMANDER_WHEEL_SHA256=$WHEEL_SHA" \
    --label "io.ras-commander.installer-sha256=$(sha256sum -- "$INSTALLER" | cut -d' ' -f1)" \
    --tag "$PRECOMPUTE_TAG" "$CONTEXT"
rm -rf -- "$PROFILE"   # the image now holds the runtime
PRECOMPUTE_ID=$("$DOCKER" image inspect --format '{{.Id}}' "$PRECOMPUTE_TAG")

echo "== [$VERSION] executor image"
RAS_COMMANDER_COMMIT=$COMMIT bash "$CONTAINERS/hecras-wine-executor/build_executor_image.sh" \
    "$VERSION" "$PRECOMPUTE_ID" "$WHEEL" "$EXECUTOR_TAG"

for tag in "${SAVE_TAGS[@]}"; do
    name=$(basename "${tag%%:*}")_${tag##*:}
    echo "== [$VERSION] save $tag -> $ARCHIVES/$name.tar.gz"
    "$DOCKER" save "$tag" | gzip -1 > "$ARCHIVES/$name.tar.gz.partial"
    mv -- "$ARCHIVES/$name.tar.gz.partial" "$ARCHIVES/$name.tar.gz"
    (cd "$ARCHIVES" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")
    "$DOCKER" image inspect --format '{{.Id}}' "$tag" > "$ARCHIVES/$name.image-id"
done
if [ -z "${KEEP_IMAGES:-}" ]; then
    "$DOCKER" rmi "$EXECUTOR_TAG" "$PRECOMPUTE_TAG" >/dev/null
    # The build context (the whole runtime profile) is cached by BuildKit.
    "$DOCKER" builder prune -af >/dev/null
fi
echo "RELEASE-IMAGES-OK $VERSION"
