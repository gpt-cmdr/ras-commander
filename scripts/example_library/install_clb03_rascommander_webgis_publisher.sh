#!/usr/bin/env bash
# Run on CLB03 as root. Installs the restricted publisher bridge, but never
# grants the key access on CLB-WebGIS; that is a separate host-admin action.
set -euo pipefail

readonly STAGE_ROOT="/mnt/pool_12tb/rascommander-webgis-staging"
readonly KEY_PATH="/root/.ssh/rascommander-webgis-publish-ed25519"
readonly KNOWN_HOSTS="/root/.ssh/rascommander-webgis-known_hosts"
readonly WEBGIS_HOST="192.168.3.3"
readonly INSTALL_PATH="/usr/local/sbin/rascommander-webgis-publish"

usage() {
    printf 'Usage: %s --publisher-script /absolute/path/to/clb03_rascommander_webgis_publisher.sh\n' "$0" >&2
    exit 64
}

if [[ $EUID -ne 0 ]]; then
    printf 'This installer must run as root on CLB03.\n' >&2
    exit 1
fi
if [[ $# -ne 2 || $1 != "--publisher-script" || $2 != /* || ! -f $2 ]]; then
    usage
fi

install -d -o root -g root -m 0750 "$STAGE_ROOT"
install -d -o root -g root -m 0700 /root/.ssh
if [[ ! -f $KEY_PATH ]]; then
    ssh-keygen -q -t ed25519 -N '' -C 'clb03-rascommander-webgis-publish' -f "$KEY_PATH"
fi
if [[ ! -f ${KEY_PATH}.pub ]]; then
    ssh-keygen -y -f "$KEY_PATH" > "${KEY_PATH}.pub"
fi
if ! ssh-keygen -F "$WEBGIS_HOST" -f /root/.ssh/known_hosts > "$KNOWN_HOSTS"; then
    printf 'No trusted SSH host key for %s is present on CLB03.\n' "$WEBGIS_HOST" >&2
    exit 1
fi

install -o root -g root -m 0750 "$2" "$INSTALL_PATH"
printf 'Installed CLB03 publisher bridge. Public-key fingerprint: '
ssh-keygen -lf "${KEY_PATH}.pub" | awk '{print $2}'
printf 'WebGIS host authorization remains required before the bridge can publish.\n'
