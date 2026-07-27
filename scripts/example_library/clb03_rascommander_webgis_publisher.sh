#!/usr/bin/env bash
# Installed on CLB03 as root. See provision_webgis_rascommander_publisher.sh
# for the corresponding one-time WebGIS host setup.
set -euo pipefail

readonly STAGE_ROOT="/mnt/pool_12tb/rascommander-webgis-staging"
readonly KEY_PATH="/root/.ssh/rascommander-webgis-publish-ed25519"
readonly KNOWN_HOSTS="/root/.ssh/rascommander-webgis-known_hosts"
readonly WEBGIS_HOST="192.168.3.3"
readonly WEBGIS_USER="rascommander-publish"
readonly SERVICE_KEY_PATH="/root/.ssh/clb-webgis-promote-ed25519"
readonly RASTER_CT_ID="230"
readonly VERSION_ROOT="hec-ras-7.0"
readonly WEBGIS_DATA_ROOT="/webgis_ssd_mirror/rascommander-webgis/data/rasexamples/${VERSION_ROOT}"
readonly CT_DATA_ROOT="/var/www/rascommander-webgis/data/rasexamples/${VERSION_ROOT}"
readonly RASTER_SERVICE_URL="http://127.0.0.1:8087/ras-raster/ready"
readonly VERSIONER="/usr/local/libexec/rascommander-version-webgis-release.py"
readonly PUBLIC_VALIDATOR="/usr/local/libexec/rascommander-validate-public-webgis-release.py"
readonly PUBLIC_ORIGIN="https://rascommander.info"

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

release_id_from_manifest() {
    python3 - "$1/manifest.json" <<'PY'
import json
import re
import sys
from pathlib import Path

release_id = str(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("releaseId") or "")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", release_id):
    raise SystemExit("Release manifest has an unsafe or missing releaseId")
print(release_id)
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

validate_raster_catalog_candidate() {
    local release_id="$1"
    local validation
    validation="$(
        webgis_exec \
            pct exec "$RASTER_CT_ID" -- \
            /opt/ras2cng/.venv/bin/python -c \
            'from pathlib import Path; import json,sys; from ras2cng.webgis_service import RasterAssetCatalog; catalog=RasterAssetCatalog.load(Path(sys.argv[1]), Path(sys.argv[2])); print(json.dumps({"assets":len(catalog.assets),"releaseId":catalog.release_id}))' \
            "${CT_DATA_ROOT}/raster-assets.json.candidate" \
            "$CT_DATA_ROOT"
    )"
    python3 - "$release_id" "$validation" <<'PY'
import json
import sys

release_id = sys.argv[1]
validation = json.loads(sys.argv[2])
if validation.get("releaseId") != release_id:
    raise SystemExit("Candidate raster catalog has the wrong active release")
assets = int(validation.get("assets") or 0)
if assets < 1:
    raise SystemExit("Candidate raster catalog contains no assets")
print(assets)
PY
}

merge_raster_catalog_candidate() {
    local release_id="$1"
    local release_catalog="${CT_DATA_ROOT}/releases/${release_id}/raster-assets.json"
    local candidate="${CT_DATA_ROOT}/raster-assets.json.candidate"
    local live="${CT_DATA_ROOT}/raster-assets.json"
    local -a command=(
        pct exec "$RASTER_CT_ID" --
        /opt/ras2cng/.venv/bin/ras2cng
        raster-service-catalog-merge "$candidate"
        --catalog "$release_catalog"
        --release-id "$release_id"
    )
    if webgis_exec test -f "${WEBGIS_DATA_ROOT}/raster-assets.json"; then
        command+=(--catalog "$live")
    fi
    webgis_exec "${command[@]}"
}

raster_service_ready() {
    local expected_assets="$1"
    local release_id="$2"
    local health
    health="$(
        webgis_exec \
            pct exec "$RASTER_CT_ID" -- \
            curl --fail --silent --show-error "$RASTER_SERVICE_URL" \
            2>/dev/null
    )" || return 1
    python3 - "$expected_assets" "$release_id" "$health" <<'PY'
import json
import sys

expected = int(sys.argv[1])
release_id = sys.argv[2]
try:
    health = json.loads(sys.argv[3])
except json.JSONDecodeError:
    raise SystemExit(1)
if (
    health.get("status") != "ready"
    or health.get("assets") != expected
    or health.get("releaseId") != release_id
    or health.get("missingAssets") != 0
):
    raise SystemExit(1)
PY
}

wait_for_raster_service() {
    local expected_assets="$1"
    local release_id="$2"
    local attempt
    for attempt in $(seq 1 30); do
        if raster_service_ready "$expected_assets" "$release_id"; then
            printf 'Numeric raster service is ready for %s with %s assets.\n' \
                "$release_id" "$expected_assets"
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
    local release_id="$1"
    local expected_assets candidate_path live_path backup_path
    candidate_path="${WEBGIS_DATA_ROOT}/raster-assets.json.candidate"
    live_path="${WEBGIS_DATA_ROOT}/raster-assets.json"
    backup_path="${WEBGIS_DATA_ROOT}/raster-assets.json.rollback.$$"

    merge_raster_catalog_candidate "$release_id"
    if ! expected_assets="$(validate_raster_catalog_candidate "$release_id")"; then
        webgis_exec rm -f -- "$candidate_path" || true
        return 1
    fi

    if webgis_exec test -f "$live_path"; then
        webgis_exec cp --preserve=mode,ownership,timestamps -- \
            "$live_path" "$backup_path"
        RASTER_CATALOG_BACKUP="$backup_path"
    else
        backup_path=""
        RASTER_CATALOG_BACKUP=""
    fi
    webgis_exec mv -f -- "$candidate_path" "$live_path"
    restart_raster_service

    if wait_for_raster_service "$expected_assets" "$release_id"; then
        return 0
    fi

    report_raster_service_failure
    if [[ -n $backup_path ]]; then
        webgis_exec mv -f -- "$backup_path" "$live_path"
        RASTER_CATALOG_BACKUP=""
        restart_raster_service || true
    else
        webgis_exec rm -f -- "$live_path"
        restart_raster_service || true
    fi
    printf 'Restored the previous raster catalog after failed readiness.\n' >&2
    return 1
}

finalize_raster_catalog() {
    if [[ -n ${RASTER_CATALOG_BACKUP:-} ]]; then
        webgis_exec rm -f -- "$RASTER_CATALOG_BACKUP"
        RASTER_CATALOG_BACKUP=""
    fi
}

rollback_raster_catalog() {
    local live_path="${WEBGIS_DATA_ROOT}/raster-assets.json"
    if [[ -z ${RASTER_CATALOG_BACKUP:-} ]]; then
        return 0
    fi
    webgis_exec mv -f -- "$RASTER_CATALOG_BACKUP" "$live_path"
    RASTER_CATALOG_BACKUP=""
    restart_raster_service
    printf 'Restored the previous raster catalog.\n' >&2
}

remote_path_exists() {
    webgis_exec test -e "$1" || webgis_exec test -L "$1"
}

prepare_pointer_backup() {
    local release_id="$1"
    local name live_path
    POINTER_BACKUP_DIR="${WEBGIS_DATA_ROOT}/.pointer-rollback.${release_id}.$$"
    webgis_exec install -d -o root -g root -m 0700 "$POINTER_BACKUP_DIR" \
        || return 1
    for name in \
        current \
        catalog.json \
        example-projects.geojson \
        snapshot.json \
        current-release.json; do
        live_path="${WEBGIS_DATA_ROOT}/${name}"
        if remote_path_exists "$live_path"; then
            webgis_exec cp -a -- \
                "$live_path" "${POINTER_BACKUP_DIR}/${name}" \
                || return 1
        fi
    done
}

promote_current_release() {
    local release_id="$1"
    local current_path="${WEBGIS_DATA_ROOT}/current"
    local temporary_current="${WEBGIS_DATA_ROOT}/.current.${release_id}.$$"
    local metadata temporary_metadata

    PREVIOUS_CURRENT_TARGET="$(
        webgis_exec readlink "$current_path" 2>/dev/null || true
    )"
    case "$PREVIOUS_CURRENT_TARGET" in
        ""|releases/*) ;;
        *)
            printf 'Unsafe existing current-release target: %s\n' \
                "$PREVIOUS_CURRENT_TARGET" >&2
            return 1
            ;;
    esac

    prepare_pointer_backup "$release_id" || return 1
    webgis_exec ln -s -- "releases/${release_id}" "$temporary_current" \
        || return 1
    webgis_exec mv -Tf -- "$temporary_current" "$current_path" \
        || return 1
    CURRENT_SWITCHED=1

    for metadata in catalog.json example-projects.geojson snapshot.json; do
        temporary_metadata="${WEBGIS_DATA_ROOT}/.${metadata}.${release_id}.$$"
        webgis_exec ln -s -- "current/${metadata}" "$temporary_metadata" \
            || return 1
        webgis_exec mv -Tf -- \
            "$temporary_metadata" "${WEBGIS_DATA_ROOT}/${metadata}" \
            || return 1
    done
    temporary_metadata="${WEBGIS_DATA_ROOT}/.current-release.json.${release_id}.$$"
    webgis_exec ln -s -- "current/release.json" "$temporary_metadata" \
        || return 1
    webgis_exec mv -Tf -- \
        "$temporary_metadata" "${WEBGIS_DATA_ROOT}/current-release.json" \
        || return 1
}

rollback_current_release() {
    local release_id="$1"
    local backup_path live_path name
    if [[ ${CURRENT_SWITCHED:-0} != 1 ]]; then
        if [[ -n ${POINTER_BACKUP_DIR:-} ]]; then
            webgis_exec rm -rf -- "$POINTER_BACKUP_DIR"
            POINTER_BACKUP_DIR=""
        fi
        return 0
    fi
    if [[ -z ${POINTER_BACKUP_DIR:-} ]]; then
        printf 'No public-pointer rollback snapshot is available for %s.\n' \
            "$release_id" >&2
        return 1
    fi
    for name in \
        current \
        catalog.json \
        example-projects.geojson \
        snapshot.json \
        current-release.json; do
        live_path="${WEBGIS_DATA_ROOT}/${name}"
        backup_path="${POINTER_BACKUP_DIR}/${name}"
        webgis_exec rm -rf -- "$live_path"
        if remote_path_exists "$backup_path"; then
            webgis_exec mv -T -- "$backup_path" "$live_path"
        fi
    done
    webgis_exec rm -rf -- "$POINTER_BACKUP_DIR"
    POINTER_BACKUP_DIR=""
    CURRENT_SWITCHED=0
    printf 'Restored the previous public release pointers.\n' >&2
}

finalize_current_release() {
    if [[ -n ${POINTER_BACKUP_DIR:-} ]]; then
        webgis_exec rm -rf -- "$POINTER_BACKUP_DIR"
        POINTER_BACKUP_DIR=""
    fi
}

if [[ $# -ne 2 || $1 != "--release-dir" ]]; then
    usage
fi

release_dir="$(require_release_dir "$2")"
verify_manifest "$release_dir"
release_id="$(release_id_from_manifest "$release_dir")"
source_root="${release_dir}/data/rasexamples/${VERSION_ROOT}"
remote_release_path="${WEBGIS_DATA_ROOT}/releases/${release_id}"
incoming_name="${release_id}.$$"
remote_incoming_path="${WEBGIS_DATA_ROOT}/.incoming/${incoming_name}"
remote_incoming_destination="./${VERSION_ROOT}/.incoming/${incoming_name}/"

if [[ ! -x $VERSIONER || ! -x $PUBLIC_VALIDATOR ]]; then
    printf 'Required publication helpers are not installed under /usr/local/libexec.\n' >&2
    exit 1
fi
if webgis_exec test -e "$remote_release_path"; then
    printf 'Immutable WebGIS release already exists: %s\n' "$remote_release_path" >&2
    exit 1
fi

overlay_dir="$(mktemp -d "${STAGE_ROOT}/.versioned-overlay.XXXXXX")"
incoming_active=1
cleanup() {
    rm -rf -- "$overlay_dir"
    if [[ ${incoming_active:-0} == 1 ]]; then
        webgis_exec rm -rf -- "$remote_incoming_path" || true
    fi
}
trap cleanup EXIT
python3 "$VERSIONER" \
    --source-root "$source_root" \
    --output-root "$overlay_dir" \
    --release-id "$release_id"

current_target="$(
    webgis_exec readlink "${WEBGIS_DATA_ROOT}/current" 2>/dev/null || true
)"
case "$current_target" in
    releases/*) link_destination="../../${current_target}" ;;
    "") link_destination="../.." ;;
    *)
        printf 'Unsafe existing current-release target: %s\n' "$current_target" >&2
        exit 1
        ;;
esac

webgis_exec install -d -o "$WEBGIS_USER" -g "$WEBGIS_USER" -m 2775 \
    "${WEBGIS_DATA_ROOT}/releases" \
    "${WEBGIS_DATA_ROOT}/.incoming" \
    "$remote_incoming_path"
if ! rsync_artifacts \
    --link-dest="$link_destination" \
    "${source_root}/" \
    "${WEBGIS_USER}@${WEBGIS_HOST}:${remote_incoming_destination}"; then
    printf 'Hard-link reuse was unavailable; retrying the staged transfer without it.\n' >&2
    rsync_artifacts \
        "${source_root}/" \
        "${WEBGIS_USER}@${WEBGIS_HOST}:${remote_incoming_destination}"
fi
rsync_artifacts \
    "${overlay_dir}/" \
    "${WEBGIS_USER}@${WEBGIS_HOST}:${remote_incoming_destination}"
webgis_exec mv -T -- "$remote_incoming_path" "$remote_release_path"
incoming_active=0

promote_raster_catalog "$release_id"
CURRENT_SWITCHED=0
if ! promote_current_release "$release_id"; then
    rollback_current_release "$release_id"
    rollback_raster_catalog
    exit 1
fi

if ! python3 "$PUBLIC_VALIDATOR" \
    --origin "$PUBLIC_ORIGIN" \
    --release-id "$release_id"; then
    rollback_current_release "$release_id"
    rollback_raster_catalog
    exit 1
fi

finalize_current_release
finalize_raster_catalog
rm -rf -- "$overlay_dir"
trap - EXIT
printf 'Published and publicly validated immutable WebGIS release %s.\n' \
    "$release_id"
