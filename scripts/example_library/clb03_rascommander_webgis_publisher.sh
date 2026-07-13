#!/usr/bin/env bash
# Installed on CLB03 as root. See provision_webgis_rascommander_publisher.sh
# for the corresponding one-time WebGIS host setup.
set -euo pipefail

readonly STAGE_ROOT="/mnt/pool_12tb/rascommander-webgis-staging"
readonly KEY_PATH="/root/.ssh/rascommander-webgis-publish-ed25519"
readonly KNOWN_HOSTS="/root/.ssh/rascommander-webgis-known_hosts"
readonly WEBGIS_HOST="192.168.3.3"
readonly WEBGIS_USER="rascommander-publish"
readonly PUBLISHER="/usr/local/sbin/rascommander-webgis-publish"

usage() {
    printf 'Usage: %s --release-dir /mnt/pool_12tb/rascommander-webgis-staging/<release>\n' "$0" >&2
    exit 64
}

require_release_dir() {
    local candidate="$1"
    local resolved_root resolved_release
    resolved_root="$(realpath -e "$STAGE_ROOT")"
    resolved_release="$(realpath -e "$candidate")"
    case "${resolved_release}/" in
        "${resolved_root}/"*) printf '%s\n' "$resolved_release" ;;
        *) printf 'Release directory must be beneath %s\n' "$resolved_root" >&2; exit 64 ;;
    esac
}

verify_manifest() {
    local release_dir="$1"
    python3 - "$release_dir" <<'PY'
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

release_dir = Path(sys.argv[1])
manifest_path = release_dir / "manifest.json"
payload_root = release_dir / "data" / "rasexamples"
if not manifest_path.is_file() or manifest_path.is_symlink():
    raise SystemExit(f"Missing regular manifest file: {manifest_path}")
if not payload_root.is_dir() or payload_root.is_symlink():
    raise SystemExit(f"Missing regular payload directory: {payload_root}")

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("schemaVersion") != 1 or not isinstance(manifest.get("files"), list):
    raise SystemExit("Unsupported or malformed release manifest")

expected: set[Path] = set()

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for block in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

for entry in manifest["files"]:
    relative = PurePosixPath(entry.get("path", ""))
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:3] != ("data", "rasexamples", "hec-ras-7.0")
    ):
        raise SystemExit(f"Manifest path is outside the RAS example namespace: {entry!r}")
    path = release_dir.joinpath(*relative.parts)
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"Missing regular artifact file: {relative}")
    digest = sha256(path)
    if digest != entry.get("sha256") or path.stat().st_size != entry.get("bytes"):
        raise SystemExit(f"Artifact does not match manifest: {relative}")
    expected.add(path.relative_to(release_dir))

actual = {
    path.relative_to(release_dir)
    for path in payload_root.rglob("*")
    if path.is_file() or path.is_symlink()
}
if actual != expected:
    missing = sorted(str(path) for path in expected - actual)
    unexpected = sorted(str(path) for path in actual - expected)
    raise SystemExit(f"Manifest mismatch; missing={missing}, unexpected={unexpected}")
print(f"Verified {len(expected)} RAS example artifacts against the release manifest.")
PY
}

if [[ $# -ne 2 || $1 != "--release-dir" ]]; then
    usage
fi

release_dir="$(require_release_dir "$2")"
verify_manifest "$release_dir"

exec rsync \
    --archive \
    --checksum \
    --no-owner \
    --no-group \
    --no-perms \
    --omit-dir-times \
    --itemize-changes \
    --protect-args \
    -e "ssh -i ${KEY_PATH} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=${KNOWN_HOSTS}" \
    "${release_dir}/data/rasexamples/" \
    "${WEBGIS_USER}@${WEBGIS_HOST}:./"
