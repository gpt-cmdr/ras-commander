#!/usr/bin/env bash
# Run on a CLB Docker host after staging this committed checkout and example ZIP.
# Usage: bash validate_perimeter_bc_fleet.sh /mnt/staged/ras-bc /mnt/cache /mnt/scratch/ras-bc
# Start via nohup; inspect container.log and evidence.json. No source models are mutated.
set -euo pipefail
REPO=$(realpath "$1")
CACHE=$(realpath "$2")
SCRATCH=$(realpath "$3")
IMAGE=fim-hecras-wine:6.6-clb-v8
test -f "$CACHE/Example_Projects_6_6.zip"
test -f "$REPO/scripts/validate_perimeter_bc.py"
echo "host=$(hostname) load=$(cut -d' ' -f1 /proc/loadavg)"
df -h "$SCRATCH" /mnt/fim-nas
docker ps --format '{{.Names}} {{.RunningFor}}'
# Capacity preflight: 2 CPUs/job with at least one CPU reserved, 5 GB scratch/job.
CPUS=$(getconf _NPROCESSORS_ONLN)
ACTIVE=$(docker ps --filter label=fim.run --format '{{.ID}}' | wc -l)
test "$(( (ACTIVE + 1) * 2 ))" -lt "$CPUS"
test "$(df -Pk "$SCRATCH" | awk 'NR==2 {print $4}')" -ge 5242880
IDENTITY=$(docker image inspect "$IMAGE" --format '{{.Id}}')
HASH=$( { sha256sum "$REPO/ras_commander/hdf/HdfMesh.py" "$REPO/ras_commander/geom/GeomBcLines.py" "$REPO/scripts/validate_perimeter_bc.py" "$CACHE/Example_Projects_6_6.zip" | awk '{print $1}'; echo "$IDENTITY"; } | sha256sum | cut -c1-12)
OUT="/mnt/fim-nas/runs/ras-bc-qualification/clb-perimeter-v1/$HASH"
test ! -e "$OUT"
mkdir -p "$OUT" "$SCRATCH"
JOB=$(mktemp -d "$SCRATCH/perimeter-$HASH-XXXXXX")
mkdir -p "$JOB/tmp" "$JOB/cache"
cp "$CACHE/Example_Projects_6_6.zip" "$JOB/cache/"
chmod 1777 "$JOB/tmp"
. /mnt/clb-repos/fim-commander/containers/hecras-wine/fim_jobs.sh
fim_run_start perimeter-bc 1 "$OUT/status.jsonl"
trap 'chown -R 3001:4000 "$OUT"; chmod -R g+rwX "$OUT"; chmod 2775 "$OUT"; _fim_write_run finished' EXIT
docker run --rm --cpus 2 --security-opt apparmor=unconfined \
  --name "perimeter-$HASH" $(fim_labels "$HASH") \
  -v "$REPO:/repo:ro" -v "$JOB:/work:rw" -v "$JOB/tmp:/tmp:rw" \
  --entrypoint bash "$IMAGE" -lc '
    set -e
    cp -a /runtime/wine-seed/prefix /tmp/p
    export WINEPREFIX=/tmp/p WINEARCH=win64 WINEDEBUG=-all
    export PYTHONPATH="Z:\\repo"
    xvfb-run -a wine "C:\\Python311\\python.exe" \
      "Z:\\repo\\scripts\\validate_perimeter_bc.py" \
      --output "Z:\\work\\acceptance" --example-cache "Z:\\work\\cache" \
      --ras-exe "C:\\Program Files (x86)\\HEC\\HEC-RAS\\6.6\\Ras.exe" --native
  ' > "$OUT/container.log" 2>&1
cp -a "$JOB/acceptance" "$OUT/"
printf '{"state":"completed","image":"%s","identity":"%s","host":"%s"}\n' "$IMAGE" "$IDENTITY" "$(hostname)" > "$OUT/status.jsonl"
# Retain scratch and compiled child for inspection; cleanup is an explicit later action.
