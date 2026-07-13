#!/usr/bin/env bash
# Run once on CLB-WebGIS as root with the public key created on CLB03.
# It creates an rsync-only publisher scoped to the RAS example artifact tree.
set -euo pipefail

readonly PUBLISH_USER="rascommander-publish"
readonly PUBLISH_SOURCE="192.168.3.20"
readonly PUBLISH_ROOT="/webgis_ssd_mirror/rascommander-webgis/data/rasexamples"
readonly PUBLISH_HOME="/home/${PUBLISH_USER}"

usage() {
    printf 'Usage: %s --public-key-file /path/to/rascommander-webgis-publish-ed25519.pub\n' "$0" >&2
    exit 64
}

rrsync_path() {
    if command -v rrsync >/dev/null 2>&1; then
        command -v rrsync
        return
    fi
    dpkg-query -L rsync | grep -E '/rrsync$' | head -n 1
}

if [[ $# -ne 2 || $1 != "--public-key-file" || ! -s $2 ]]; then
    usage
fi

public_key="$(tr -d '\r\n' < "$2")"
case "$public_key" in
    ssh-ed25519\ *) ;;
    *) printf 'Expected one ssh-ed25519 public key.\n' >&2; exit 64 ;;
esac

rrsync="$(rrsync_path)"
if [[ -z $rrsync || ! -x $rrsync ]]; then
    printf 'rrsync is required but was not found in the rsync package.\n' >&2
    exit 1
fi
if [[ ! -d $PUBLISH_ROOT ]]; then
    printf 'RAS example artifact directory does not exist: %s\n' "$PUBLISH_ROOT" >&2
    exit 1
fi

if ! getent group "$PUBLISH_USER" >/dev/null; then
    groupadd --system "$PUBLISH_USER"
fi
if ! id "$PUBLISH_USER" >/dev/null 2>&1; then
    useradd --system --gid "$PUBLISH_USER" --home-dir "$PUBLISH_HOME" --shell /bin/sh --no-create-home "$PUBLISH_USER"
fi
passwd -l "$PUBLISH_USER" >/dev/null

install -d -o root -g root -m 0755 "$PUBLISH_HOME"
install -d -o root -g root -m 0700 "$PUBLISH_HOME/.ssh"
printf 'from="%s",restrict,command="%s -wo %s" %s\n' \
    "$PUBLISH_SOURCE" "$rrsync" "$PUBLISH_ROOT" "$public_key" \
    | install -o root -g root -m 0600 /dev/stdin "$PUBLISH_HOME/.ssh/authorized_keys"

# The service remains read-only to the public CT; only this identity gains
# group write access under the RAS example subtree.
chgrp -R "$PUBLISH_USER" "$PUBLISH_ROOT"
chmod -R g+rwX "$PUBLISH_ROOT"
find "$PUBLISH_ROOT" -type d -exec chmod g+s {} +

sshd -t
printf 'Provisioned %s for rsync writes from %s to %s\n' \
    "$PUBLISH_USER" "$PUBLISH_SOURCE" "$PUBLISH_ROOT"
