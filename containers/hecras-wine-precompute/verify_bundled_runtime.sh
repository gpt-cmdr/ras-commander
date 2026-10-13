#!/bin/bash
# Verify an existing bundled image; retain the fresh prefix and evidence outside Git.
set -euo pipefail
if [ "$#" -ne 3 ]; then
    echo "Usage: bash verify_bundled_runtime.sh IMAGE VERSION NEW_EXTERNAL_AUDIT_DIR" >&2
    exit 2
fi
image=$1
version=$2
case "$version" in 6.5|6.6|7.0.1) ;; *) echo "Unsupported HEC-RAS version" >&2; exit 2 ;; esac
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(realpath "$script_dir/../..")
audit_dir=$(realpath -m -- "$3")
case "$audit_dir/" in "$repo_dir/"*) echo "Keep runtime copies outside the repository" >&2; exit 2 ;; esac
if [ -e "$audit_dir" ] || [ -L "$audit_dir" ]; then
    echo "Audit directory must be new: $audit_dir" >&2
    exit 2
fi
if [ ! -c /dev/ntsync ]; then
    echo "This check requires the qualified Linux host's /dev/ntsync device" >&2
    exit 2
fi
if [ "$(id -u)" != 0 ] && [ "$(id -u)" != 1000 ]; then
    echo "Run as host UID 1000 or root so the copied runtime can belong to UID 1000" >&2
    exit 2
fi
# Resolve the tag once and execute the inspected immutable local image identity.
image_id=$(docker image inspect --format '{{.Id}}' "$image")
mkdir -m 0750 -- "$audit_dir"
if [ "$(id -u)" = 0 ]; then chown 1000:1000 -- "$audit_dir"; fi
docker image inspect "$image_id" > "$audit_dir/image-inspect.json"

docker run --rm --network none --read-only --user 1000:1000 \
    --cpus 2 --memory 6g --memory-swap 6g --pids-limit 2048 \
    --cap-drop ALL --security-opt no-new-privileges --device /dev/ntsync \
    --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 \
    --mount "type=bind,src=$script_dir,dst=/review-tools,readonly" \
    --mount "type=bind,src=$audit_dir,dst=/audit" \
    --env "AUDIT_VERSION=$version" --entrypoint /bin/bash "$image_id" -c '
set -euo pipefail
python - <<"PY"
import os
from pathlib import Path
from prepare import load_runtime, windows_seed_path, write_json
version = os.environ["AUDIT_VERSION"]
if os.environ["RAS_COMMANDER_PREPARE_HECRAS_VERSION"] != version:
    raise RuntimeError("Requested version does not match the image")
runtime = load_runtime(os.environ["RAS_COMMANDER_PREPARE_RUNTIME_MANIFEST"], version)
if os.getuid() != 1000 or os.access(runtime["prefix"] / "user.reg", os.W_OK):
    raise RuntimeError("The embedded registry must be protected from the worker")
exe = windows_seed_path(runtime["prefix"], runtime["ras_executable"], "wine.ras_executable")
Path("/audit/expected-exe-sha256.txt").write_text(runtime["hashes"][exe] + "\n")
write_json(Path("/audit/runtime-identity.json"), runtime["identity"])
PY
cp -a /runtime/wine-seed/prefix /audit/prefix
export WINEPREFIX=/audit/prefix WINEDEBUG=-all HOME=/tmp
cleanup() { wineserver -k >/dev/null 2>&1 || true; wineserver -w >/dev/null 2>&1 || true; }
trap cleanup EXIT
xvfb-run -a wine "C:\Python311\python.exe" -I \
    "Z:\review-tools\verify_windows_runtime.py" "$AUDIT_VERSION" \
    --expected-exe-sha256 "$(cat /audit/expected-exe-sha256.txt)" \
    > /audit/windows-runtime.json 2> /audit/wine-stderr.log
' > "$audit_dir/verification.log" 2>&1
printf 'Runtime and saved TCU verified: %s\nEvidence: %s\n' "$version" "$audit_dir"
