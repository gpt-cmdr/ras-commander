#!/usr/bin/env bash
# Run inside CT230 (rascommander-webgis) as root.
# Installs the bounded ras2cng COG statistics/styled-tile service on loopback.
set -euo pipefail

readonly SERVICE_USER="rasweb"
readonly SERVICE_GROUP="rasweb"
readonly APP_ROOT="/opt/ras2cng"
readonly DATA_ROOT="/var/www/rascommander-webgis/data/rasexamples/hec-ras-7.0"
readonly CATALOG="${DATA_ROOT}/raster-assets.json"
readonly SITE_CONFIG="/etc/nginx/sites-available/rascommander-webgis"

usage() {
    printf 'Usage: %s --wheel /absolute/path/to/ras2cng.whl\n' "$0" >&2
    exit 64
}

if [[ $EUID -ne 0 ]]; then
    printf 'This provisioner must run as root inside CT230.\n' >&2
    exit 1
fi
if [[ $# -ne 2 || $1 != "--wheel" || $2 != /* || ! -s $2 ]]; then
    usage
fi
if [[ ! -s $CATALOG ]]; then
    printf 'Raster asset catalog does not exist: %s\n' "$CATALOG" >&2
    exit 1
fi
if [[ ! -f $SITE_CONFIG ]]; then
    printf 'RAS Commander WebGIS Nginx site does not exist: %s\n' "$SITE_CONFIG" >&2
    exit 1
fi

wheel="$(realpath -e "$2")"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3-pip python3-venv

if ! getent group "$SERVICE_GROUP" >/dev/null; then
    groupadd --system "$SERVICE_GROUP"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --gid "$SERVICE_GROUP" --home-dir "$APP_ROOT" \
        --shell /usr/sbin/nologin --no-create-home "$SERVICE_USER"
fi

install -d -o root -g root -m 0755 "$APP_ROOT"
python3 -m venv "${APP_ROOT}/.venv"
"${APP_ROOT}/.venv/bin/python" -m pip install --upgrade pip
"${APP_ROOT}/.venv/bin/python" -m pip install --upgrade "${wheel}[webgis]"
"${APP_ROOT}/.venv/bin/python" -m pip install --force-reinstall --no-deps "$wheel"

install -d -o root -g root -m 0755 /etc/ras2cng
cat > /etc/ras2cng/raster-service.env <<'EOF'
RAS2CNG_RASTER_ALLOWED_ORIGINS=https://rascommander.info
RAS2CNG_RASTER_ROUTE_PREFIX=/ras-raster
RAS2CNG_RASTER_MAX_VIEW_PIXELS=2097152
RAS2CNG_RASTER_MAX_VIEW_DIMENSION=4096
RAS2CNG_RASTER_CACHE_ENTRIES=512
MPLCONFIGDIR=/tmp/matplotlib
XDG_CACHE_HOME=/tmp/cache
EOF
chmod 0644 /etc/ras2cng/raster-service.env

cat > /etc/systemd/system/ras2cng-raster.service <<EOF
[Unit]
Description=RAS Commander numeric raster service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${APP_ROOT}
EnvironmentFile=/etc/ras2cng/raster-service.env
ExecStart=${APP_ROOT}/.venv/bin/ras2cng raster-service ${CATALOG} ${DATA_ROOT} --host 127.0.0.1 --port 8087
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadOnlyPaths=/var/www/rascommander-webgis
MemoryHigh=6G
MemoryMax=8G
TasksMax=128

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 /etc/systemd/system/ras2cng-raster.service

python3 - "$SITE_CONFIG" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
marker = "# ras2cng numeric raster service"
if marker not in source:
    needle = "    location / {\n"
    if source.count(needle) != 1:
        raise SystemExit(f"Expected one default location in {path}")
    block = """    # ras2cng numeric raster service
    location /ras-raster/ {
        proxy_pass http://127.0.0.1:8087/ras-raster/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_buffering on;
    }

"""
    temporary = path.with_name(f".{path.name}.ras2cng.tmp")
    temporary.write_text(source.replace(needle, block + needle), encoding="utf-8")
    os.chmod(temporary, path.stat().st_mode)
    temporary.replace(path)
PY

systemctl daemon-reload
systemctl enable ras2cng-raster.service
systemctl restart ras2cng-raster.service
nginx -t
systemctl reload nginx

for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8087/ras-raster/health >/dev/null; then
        break
    fi
    sleep 1
done
curl -fsS http://127.0.0.1:8087/ras-raster/health
curl -fsS http://127.0.0.1/ras-raster/health
printf '\nProvisioned the isolated numeric raster service.\n'
