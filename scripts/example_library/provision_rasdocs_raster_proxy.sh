#!/usr/bin/env bash
# Run inside CT210 (builder) and active CT213 (serve-only replica) as root
# after CT230 is healthy.
set -euo pipefail

readonly CADDYFILE="/etc/caddy/Caddyfile"
readonly WEBGIS_ORIGIN="http://192.168.30.31"
readonly MARKER="# ras2cng numeric raster service"

if [[ $EUID -ne 0 ]]; then
    printf 'This provisioner must run as root inside CT210 or CT213.\n' >&2
    exit 1
fi
if [[ ! -f $CADDYFILE ]]; then
    printf 'Caddyfile does not exist: %s\n' "$CADDYFILE" >&2
    exit 1
fi

curl -fsS "${WEBGIS_ORIGIN}/ras-raster/health" >/dev/null

python3 - "$CADDYFILE" "$MARKER" <<'PY'
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
marker = sys.argv[2]
source = path.read_text(encoding="utf-8")
if marker not in source:
    needle = "\t# --- WebGIS artifacts:"
    if source.count(needle) != 1:
        raise SystemExit(f"Expected one WebGIS artifact marker in {path}")
    block = """\t# ras2cng numeric raster service
\t# The bounded COG statistics/styled-tile app runs inside isolated CT230.
\thandle /ras-raster/* {
\t\treverse_proxy http://192.168.30.31
\t}

"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.before-ras2cng-raster-{timestamp}")
    backup.write_bytes(path.read_bytes())
    os.chmod(backup, path.stat().st_mode)
    temporary = path.with_name(f".{path.name}.ras2cng.tmp")
    temporary.write_text(source.replace(needle, block + needle), encoding="utf-8")
    os.chmod(temporary, path.stat().st_mode)
    temporary.replace(path)
PY

if [[ -r /etc/caddy/rasdocs-stats.env ]]; then
    while IFS='=' read -r key value; do
        [[ $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        export "$key=$value"
    done < /etc/caddy/rasdocs-stats.env
fi
caddy validate --config "$CADDYFILE"
# This origin intentionally has Caddy's admin endpoint disabled, so reload
# cannot reach localhost:2019. A validated restart is the supported path.
systemctl restart caddy
curl -fsS -H 'Host: rascommander.info' http://127.0.0.1/ras-raster/health
printf '\nProvisioned the rasdocs numeric raster reverse proxy.\n'
