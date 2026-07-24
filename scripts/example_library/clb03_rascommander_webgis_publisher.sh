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
readonly SERVICE_KEY_PATH="/root/.ssh/clb-webgis-promote-ed25519"
readonly RASTER_CT_ID="230"
readonly VERSION_ROOT="hec-ras-7.0"
readonly WEBGIS_DATA_ROOT="/webgis_ssd_mirror/rascommander-webgis/data/rasexamples/${VERSION_ROOT}"
readonly CT_DATA_ROOT="/var/www/rascommander-webgis/data/rasexamples/${VERSION_ROOT}"
readonly RASTER_SERVICE_URL="http://127.0.0.1:8087/ras-raster/health"

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
schema_version = manifest.get("schemaVersion")
if schema_version == 1:
    integrity = "sha256"
elif schema_version == 2:
    integrity = manifest.get("integrity")
else:
    raise SystemExit("Unsupported or malformed release manifest")
if integrity not in {"size", "sha256"} or not isinstance(manifest.get("files"), list):
    raise SystemExit("Unsupported or malformed release manifest")

expected: set[Path] = set()

def sha256(path: Path) -> str:
    import hashlib

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
    if path.stat().st_size != entry.get("bytes"):
        raise SystemExit(f"Artifact does not match manifest: {relative}")
    if integrity == "sha256" and sha256(path) != entry.get("sha256"):
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
print(
    f"Verified {len(expected)} RAS example artifacts "
    f"against the {integrity} release inventory."
)
PY
}

rsync_artifacts() {
    rsync \
        --archive \
        --no-owner \
        --no-group \
        --no-perms \
        --chmod=Du=rwx,Dg=rwx,Do=rx,Fu=rw,Fg=rw,Fo=r \
        --omit-dir-times \
        --itemize-changes \
        -e "ssh -i ${KEY_PATH} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=${KNOWN_HOSTS}" \
        "$@"
}

webgis_exec() {
    local remote_command
    printf -v remote_command '%q ' "$@"
    if [[ ! -s $SERVICE_KEY_PATH ]]; then
        printf 'Missing WebGIS service-control key: %s\n' "$SERVICE_KEY_PATH" >&2
        return 1
    fi
    ssh \
        -i "$SERVICE_KEY_PATH" \
        -o IdentitiesOnly=yes \
        -o BatchMode=yes \
        -o StrictHostKeyChecking=yes \
        -o UserKnownHostsFile="$KNOWN_HOSTS" \
        "root@${WEBGIS_HOST}" \
        "$remote_command"
}

raster_catalog_asset_count() {
    python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path

document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assets = document.get("assets")
if document.get("schema") != "rascommander.raster-assets/v1" or not isinstance(assets, dict):
    raise SystemExit("Unsupported or malformed raster asset catalog")
print(len(assets))
PY
}

validate_raster_catalog_candidate() {
    local expected_assets="$1"
    local observed_assets
    observed_assets="$(
        webgis_exec \
            pct exec "$RASTER_CT_ID" -- \
            /opt/ras2cng/.venv/bin/python -c \
            'from pathlib import Path; from ras2cng.webgis_service import RasterAssetCatalog; print(len(RasterAssetCatalog.load(Path(__import__("sys").argv[1]), Path(__import__("sys").argv[2])).assets))' \
            "${CT_DATA_ROOT}/raster-assets.json.candidate" \
            "$CT_DATA_ROOT"
    )"
    if [[ $observed_assets != "$expected_assets" ]]; then
        printf 'Candidate raster catalog exposes %s assets; expected %s.\n' \
            "$observed_assets" "$expected_assets" >&2
        return 1
    fi
    printf 'Validated candidate raster catalog and %s referenced COGs.\n' \
        "$expected_assets"
}

raster_service_ready() {
    local expected_assets="$1"
    local health
    health="$(
        webgis_exec \
            pct exec "$RASTER_CT_ID" -- \
            curl --fail --silent --show-error "$RASTER_SERVICE_URL" \
            2>/dev/null
    )" || return 1
    python3 - "$expected_assets" "$health" <<'PY'
import json
import sys

expected = int(sys.argv[1])
try:
    health = json.loads(sys.argv[2])
except json.JSONDecodeError:
    raise SystemExit(1)
if health.get("status") != "ok" or health.get("assets") != expected:
    raise SystemExit(1)
PY
}

wait_for_raster_service() {
    local expected_assets="$1"
    local attempt
    for attempt in $(seq 1 30); do
        if raster_service_ready "$expected_assets"; then
            printf 'Numeric raster service is ready with %s assets.\n' \
                "$expected_assets"
            return 0
        fi
        sleep 1
    done
    return 1
}

restart_raster_service() {
    webgis_exec \
        pct exec "$RASTER_CT_ID" -- \
        systemctl restart ras2cng-raster.service
}

report_raster_service_failure() {
    printf 'Numeric raster service did not become ready; service diagnostics follow.\n' >&2
    webgis_exec \
        pct exec "$RASTER_CT_ID" -- \
        systemctl status ras2cng-raster.service --no-pager --lines=20 \
        >&2 || true
    webgis_exec \
        pct exec "$RASTER_CT_ID" -- \
        journalctl -u ras2cng-raster.service --no-pager --lines=40 \
        >&2 || true
}

promote_raster_catalog() {
    local raster_catalog="$1"
    local expected_assets candidate_path live_path backup_path
    expected_assets="$(raster_catalog_asset_count "$raster_catalog")"
    candidate_path="${WEBGIS_DATA_ROOT}/raster-assets.json.candidate"
    live_path="${WEBGIS_DATA_ROOT}/raster-assets.json"
    backup_path="${WEBGIS_DATA_ROOT}/raster-assets.json.rollback.$$"

    rsync_artifacts \
        "$raster_catalog" \
        "${WEBGIS_USER}@${WEBGIS_HOST}:./${VERSION_ROOT}/raster-assets.json.candidate"

    if ! validate_raster_catalog_candidate "$expected_assets"; then
        webgis_exec rm -f -- "$candidate_path" || true
        return 1
    fi

    if webgis_exec test -f "$live_path"; then
        webgis_exec cp --preserve=mode,ownership,timestamps -- \
            "$live_path" "$backup_path"
    else
        backup_path=""
    fi
    webgis_exec mv -f -- "$candidate_path" "$live_path"
    restart_raster_service

    if wait_for_raster_service "$expected_assets"; then
        if [[ -n $backup_path ]]; then
            webgis_exec rm -f -- "$backup_path"
        fi
        return 0
    fi

    report_raster_service_failure
    if [[ -n $backup_path ]]; then
        webgis_exec mv -f -- "$backup_path" "$live_path"
        restart_raster_service || true
    else
        webgis_exec rm -f -- "$live_path"
        restart_raster_service || true
    fi
    printf 'Restored the previous raster catalog after failed readiness.\n' >&2
    return 1
}

if [[ $# -ne 2 || $1 != "--release-dir" ]]; then
    usage
fi

release_dir="$(require_release_dir "$2")"
verify_manifest "$release_dir"

# Publish immutable project artifacts before exposing their catalog entries.
rsync_artifacts \
    --exclude="/${VERSION_ROOT}/raster-assets.json" \
    --exclude="/${VERSION_ROOT}/catalog.json" \
    --exclude="/${VERSION_ROOT}/example-projects.geojson" \
    --exclude="/${VERSION_ROOT}/snapshot.json" \
    "${release_dir}/data/rasexamples/" \
    "${WEBGIS_USER}@${WEBGIS_HOST}:./"

raster_catalog="${release_dir}/data/rasexamples/${VERSION_ROOT}/raster-assets.json"
if [[ -f $raster_catalog ]]; then
    promote_raster_catalog "$raster_catalog"
fi

# Expose landing-page metadata only after the raster service recognizes the
# newly published numeric assets.
for catalog_name in catalog.json example-projects.geojson snapshot.json; do
    catalog_path="${release_dir}/data/rasexamples/${VERSION_ROOT}/${catalog_name}"
    if [[ -f $catalog_path ]]; then
        rsync_artifacts \
            "$catalog_path" \
            "${WEBGIS_USER}@${WEBGIS_HOST}:./${VERSION_ROOT}/${catalog_name}"
    fi
done

if [[ -f $raster_catalog ]]; then
    printf 'Published RAS example artifacts and validated the numeric raster service.\n'
else
    printf 'Published RAS example artifacts without changing the numeric raster catalog.\n'
fi
