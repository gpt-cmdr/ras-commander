#!/bin/bash
#SBATCH --job-name=sif-build
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=2:00:00
# Convert a pinned `docker save` archive into an Apptainer SIF as an
# unprivileged Slurm job (no root, no fakeroot, no Docker daemon). Select the
# account, partition and log path on the sbatch command line, for example:
#
#   sbatch --account=<account> --partition=<partition> --output=<logs>/sif-build-%j.out \
#     --export=ALL,RAS_COMMANDER_SIF_NAME=hec-ras-wine-executor_6.6-20261013,RAS_COMMANDER_SIF_SRC=/shared/images/hec-ras-wine-executor_6.6-20261013.tar.gz,RAS_COMMANDER_SIF_DEST=/shared/images \
#     containers/apptainer/build_sif_from_archive.sbatch
#
# Required:
#   RAS_COMMANDER_SIF_NAME     safe basename; publishes <DEST>/<name>.sif
#   RAS_COMMANDER_SIF_SRC      docker-save archive (.tar or .tar.gz)
#   RAS_COMMANDER_SIF_DEST     existing destination directory
# Optional:
#   RAS_COMMANDER_SIF_SMOKE    command run with /bin/sh -c inside the new SIF
#                              (default: python -m ras_commander.remote.execute_request --help)
#   RAS_COMMANDER_SIF_SCRATCH  node-local scratch root (default: /scratch/$SLURM_JOB_ID)
#
# The archive must match its <archive>.sha256 sidecar when one exists. The job
# builds in scratch, runs the smoke command with --contain --cleanenv, copies
# the SIF to a temporary name in DEST, checks the hash again and publishes
# three files with no-clobber renames:
#   <name>.sif          the image
#   <name>.sif.sha256   "<sha256>  <name>.sif", the digest a submission pins
#   <name>.sif.json     ras-commander-sif-record/v1: SIF digest, the image ID
#                       read from the archive's manifest.json (the Config
#                       digest), the archive and its digest, smoke command and
#                       build host
# Never overwrites an existing file; on any failure the partial files are
# removed. The scratch work directory is always removed.
set -euo pipefail
umask 022

NAME=${RAS_COMMANDER_SIF_NAME:?set RAS_COMMANDER_SIF_NAME}
SRC=${RAS_COMMANDER_SIF_SRC:?set RAS_COMMANDER_SIF_SRC}
DEST=${RAS_COMMANDER_SIF_DEST:?set RAS_COMMANDER_SIF_DEST}
SMOKE=${RAS_COMMANDER_SIF_SMOKE:-python -m ras_commander.remote.execute_request --help}
JOB=${SLURM_JOB_ID:-local-$$}
SCRATCH_ROOT=${RAS_COMMANDER_SIF_SCRATCH:-/scratch/$JOB}

[[ "$NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._=-]*$ ]] || { echo "invalid RAS_COMMANDER_SIF_NAME: expected a safe basename"; exit 2; }
[[ "$NAME" != *..* && "$NAME" != */* ]] || { echo "invalid RAS_COMMANDER_SIF_NAME: '..' and slashes are forbidden"; exit 2; }
[ -n "${SMOKE//[[:space:]]/}" ] || { echo "invalid RAS_COMMANDER_SIF_SMOKE: empty command"; exit 2; }
[ -f "$SRC" ] || { echo "invalid RAS_COMMANDER_SIF_SRC: $SRC is not a file"; exit 2; }
SRC=$(realpath -e -- "$SRC")
DST_DIR=$(realpath -m -- "$DEST")
[ -d "$DST_DIR" ] || { echo "invalid RAS_COMMANDER_SIF_DEST: $DST_DIR does not exist"; exit 2; }
[ -w "$DST_DIR" ] || { echo "invalid RAS_COMMANDER_SIF_DEST: $DST_DIR is not writable"; exit 2; }
DST=$(realpath -m -- "$DST_DIR/$NAME.sif")
case "$DST" in
  "$DST_DIR"/*) ;;
  *) echo "invalid RAS_COMMANDER_SIF_NAME: output path escapes $DST_DIR"; exit 2 ;;
esac
command -v apptainer >/dev/null || { echo "apptainer is not on PATH"; exit 2; }
command -v python3 >/dev/null || { echo "python3 is required on the build node"; exit 2; }

TMP=$DST.partial-$JOB
DST_SHA=$DST.sha256
DST_REC=$DST.json
PUBLISHED=0
RENAMED=()
S=""
cleanup() {
  status=$?
  if [ $status -ne 0 ] || [ "$PUBLISHED" != 1 ]; then
    rm -f "$TMP" "$TMP.sha256" "$TMP.json"
    for path in "${RENAMED[@]}"; do rm -f "$path"; done
  fi
  if [ -n "$S" ]; then rm -rf -- "$S"; fi
}
trap cleanup EXIT
publish_no_clobber() {
  src=$1
  dst=$2
  mv -n "$src" "$dst" || { echo "RENAME FAILED: $dst"; exit 6; }
  if [ -e "$src" ]; then
    echo "REFUSE: $dst appeared during rename"
    exit 2
  fi
  [ -e "$dst" ] || { echo "RENAME FAILED: $dst missing"; exit 6; }
  RENAMED+=("$dst")
}
refuse_existing() {
  for path in "$DST" "$DST_SHA" "$DST_REC"; do
    if [ -e "$path" ]; then echo "REFUSE: $path already exists"; exit 2; fi
  done
}

echo "job=$JOB host=$(hostname -s) id=$(id) start=$(date -Is)"
refuse_existing
apptainer --version
P=$(cut -d: -f3 /proc/self/cgroup | head -n1); while [ -n "$P" ]; do echo "cgroup $P memory.max=$(cat "/sys/fs/cgroup$P/memory.max" 2>/dev/null)"; P=${P%/*}; done
mkdir -p "$SCRATCH_ROOT" || exit 3
S=$(mktemp -d "$SCRATCH_ROOT/sif-build.XXXXXX") || exit 3
export APPTAINER_TMPDIR=$S/tmp APPTAINER_CACHEDIR=$S/cache
mkdir -p "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR" || exit 3
echo "source:"; ls -l "$SRC"
SRC_SHA=$(sha256sum "$SRC" | cut -d' ' -f1); echo "source sha256=$SRC_SHA"
if [ -f "$SRC.sha256" ]; then
  [ "$(cut -d' ' -f1 "$SRC.sha256")" = "$SRC_SHA" ] || { echo "SOURCE HASH MISMATCH against $SRC.sha256"; exit 5; }
  echo "source matches $SRC.sha256"
fi
# docker-archive:// cannot read a gzipped archive ("gzip: invalid header").
TAR=$S/$NAME.tar
case "$SRC" in
  *.gz) gunzip -c "$SRC" > "$TAR" ;;
  *) cp "$SRC" "$TAR" ;;
esac
IMAGE_ID=$(tar -xOf "$TAR" manifest.json 2>/dev/null | python3 -c '
import json, re, sys
config = json.load(sys.stdin)[0]["Config"]
print("sha256:" + re.search(r"[0-9a-f]{64}", config).group(0))
') || IMAGE_ID=""
echo "image_id=${IMAGE_ID:-unknown} (archive manifest.json Config)"
start=$(date +%s)
set +e
apptainer build "$S/$NAME.sif" "docker-archive://$TAR"; rc=$?
set -e
echo "docker-archive build rc=$rc elapsed=$(( $(date +%s) - start ))s"
if [ $rc -ne 0 ]; then
  rm -f "$S/$NAME.sif"
  start=$(date +%s)
  set +e
  apptainer build "$S/$NAME.sif" "oci-archive://$TAR"; rc=$?
  set -e
  echo "oci-archive build rc=$rc elapsed=$(( $(date +%s) - start ))s"
fi
[ $rc -eq 0 ] || { echo "BUILD FAILED rc=$rc"; df -h "$S"; exit $rc; }
rm -f "$TAR"
ls -l "$S/$NAME.sif"
LOCAL_SHA=$(sha256sum "$S/$NAME.sif" | cut -d' ' -f1); echo "scratch sif sha256=$LOCAL_SHA"
echo "== inspect"; apptainer inspect "$S/$NAME.sif"
echo "== runscript"; apptainer inspect --runscript "$S/$NAME.sif"
echo "== smoke: $SMOKE (first 40 lines)"
SMOKE_LOG=$S/$NAME.smoke.txt
mkdir -p "$S/smoke-work"
apptainer exec --contain --cleanenv --workdir "$S/smoke-work" "$S/$NAME.sif" /bin/sh -c "$SMOKE" > "$SMOKE_LOG" 2>&1 \
  || { head -40 "$SMOKE_LOG"; echo "SMOKE FAILED"; exit 7; }
head -40 "$SMOKE_LOG"
echo "== copy to $DST_DIR under a temporary name"
cp "$S/$NAME.sif" "$TMP" || { echo "COPY FAILED"; exit 4; }
DEST_SHA=$(sha256sum "$TMP" | cut -d' ' -f1); echo "destination tmp sha256=$DEST_SHA"
[ "$DEST_SHA" = "$LOCAL_SHA" ] || { echo "HASH MISMATCH after copy"; exit 5; }
printf '%s  %s\n' "$DEST_SHA" "$(basename "$DST")" > "$TMP.sha256"
python3 - "$TMP.json" "$(basename "$DST")" "$DEST_SHA" "$IMAGE_ID" "$SRC" "$SRC_SHA" \
  "$SMOKE" "$JOB" "$(hostname -s)" "$(apptainer --version)" <<'PY'
import json, sys
from datetime import datetime, timezone
path, sif, sha, image_id, src, src_sha, smoke, job, host, apptainer = sys.argv[1:]
record = {
    "schema": "ras-commander-sif-record/v1",
    "sif": sif,
    "sif_sha256": sha,
    "image_id": image_id or None,
    "source_archive": src,
    "source_archive_sha256": src_sha,
    "smoke_command": smoke,
    "slurm_job_id": job,
    "build_host": host,
    "apptainer_version": apptainer,
    "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
with open(path, "w") as handle:
    json.dump(record, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
refuse_existing
publish_no_clobber "$TMP.sha256" "$DST_SHA"
publish_no_clobber "$TMP.json" "$DST_REC"
publish_no_clobber "$TMP" "$DST"
PUBLISHED_SHA=$(sha256sum "$DST" | cut -d' ' -f1)
[ "$PUBLISHED_SHA" = "$LOCAL_SHA" ] || { echo "PUBLISHED HASH MISMATCH"; exit 5; }
(cd "$DST_DIR" && sha256sum -c "$(basename "$DST_SHA")")
PUBLISHED=1
ls -ln "$DST" "$DST_SHA" "$DST_REC"; cat "$DST_SHA" "$DST_REC"
echo "== scratch use at end"; du -sh "$S"; df -h "$S" | tail -1
echo "end=$(date -Is)"
