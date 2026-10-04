"""Native-Linux HEC-RAS 6.6 unsteady execution on Slurm through Apptainer.

``RasApptainer`` takes the artifacts produced by Windows preprocessing
(``<project>.p##.tmp.hdf``, ``<project>.b##``, ``<project>.x##``; see
``RasPreprocess``), renders a self-contained job folder plus an ``sbatch``
script, and drives it over a pluggable SSH transport.

Nothing here contacts a cluster unless a transport is supplied and
``dry_run=False``. ``render_job`` and ``submit(..., dry_run=True)`` are fully
offline. The receipt written by the job is computational/transfer evidence
only; it is never a statement that results are acceptable engineering output.

Selected fim-commander ``PortableSiteProfile`` fields are accepted as logged
compatibility no-ops. A usable profile still needs this API's SSH and
native-image settings.
"""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import shlex
import shutil
import subprocess
import uuid
from typing import Any, Mapping, Optional, Sequence, Union

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasSlurm import (
    _CONTAINER_IDENTITY,
    _ENV_NAME,
    _MEMORY,
    _MODULE,
    _REMOTE_PATH,
    _SHA256,
    _TIME,
    _TOKEN,
)
from .remote.ExecutionContract import atomic_write_json, sha256_file

logger = get_logger(__name__)

PROFILE_SCHEMA = "ras-commander-apptainer-profile/v1"
JOB_SCHEMA = "ras-commander-apptainer-job/v1"
RECEIPT_SCHEMA = "ras-commander-apptainer-receipt/v1"

_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_PLAN_NUMBER = re.compile(r"[0-9]{2}\Z")
_JOB_ID = re.compile(r"[1-9][0-9]*\Z")
TERMINAL_STATES = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
    "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "PREEMPTED",
})
# Default image layout is derived from its Dockerfile and registry metadata.  It has not
# been qualified by a live run through this API; sites must qualify their own profile.
DEFAULT_OCI_SOURCE = "docker://rascommander/hec-ras-linux-unsteady_6.6:v1"
DEFAULT_HECRAS_DIR = "/opt/hecras-runtime/engine"
DEFAULT_LD_LIBRARY_PATH = (
    f"{DEFAULT_HECRAS_DIR}/libs", f"{DEFAULT_HECRAS_DIR}/libs/mkl",
    f"{DEFAULT_HECRAS_DIR}/libs/rhel_8",
)
_STACK_SIZE = re.compile(r"[1-9][0-9]*[KMGkmg]?\Z")
_OCI_SOURCE = re.compile(
    r"docker://[a-z0-9][a-z0-9._/-]*(?::[A-Za-z0-9_][A-Za-z0-9._-]{0,127}|@sha256:[0-9a-f]{64})\Z"
)
_ZERO_SHA256 = "0" * 64
_WINDOWS_ABSOLUTE_DSS = re.compile(r"^[A-Za-z]:[\\/].*\.dss\s*$", re.IGNORECASE)
_WRITE_DSS_FILE = re.compile(r"^\s*Write DSS File\s*=\s*T\s*$", re.IGNORECASE)
_FIM_ONLY_FIELDS = frozenset({
    "launcher_python_executable", "max_concurrent", "memory_per_task", "ras_executable",
    "rsync_executable", "timeout_seconds", "transfer_mode",
})


# --------------------------------------------------------------------------
# Site profile
# --------------------------------------------------------------------------

class ApptainerProfileError(ValueError):
    """Raised with every problem found in a site profile, one per line."""

    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("Invalid Apptainer site profile:\n- " + "\n- ".join(self.problems))


@dataclass(frozen=True)
class ApptainerSiteProfile:
    """Cluster, image and resource settings for one site (no secrets).

    ``scratch_root`` is the shared filesystem root visible to the login node
    and the compute nodes; job folders are staged beneath it. ``node_scratch_root``
    is node-local scratch; the job works in ``<node_scratch_root>/$SLURM_JOB_ID``.
    ``image`` is a shared SIF that an administrator pulled once from the OCI
    reference in ``container_identity``; its bytes are SHA-256 verified by every job.
    """

    site_name: str
    host: str
    ssh_user: str
    scratch_root: str
    image: str
    apptainer_image_sha256: str
    container_identity: str
    ssh_port: int = 22
    identity_file: Optional[str] = None
    known_hosts_file: Optional[str] = None
    node_scratch_root: str = "/scratch"
    hecras_dir: str = DEFAULT_HECRAS_DIR
    ld_library_path: tuple[str, ...] = DEFAULT_LD_LIBRARY_PATH
    ras_version: str = "6.6"
    num_cores: int = 2
    slurm_memory: Optional[str] = None
    time_limit: str = "08:00:00"
    account: Optional[str] = None
    partition: Optional[str] = None
    qos: Optional[str] = None
    nodelist: Optional[str] = None
    modules: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    geom_preprocess: bool = False
    oci_source: str = DEFAULT_OCI_SOURCE
    stack_unlimited: bool = True
    omp_stacksize: str = "2G"
    kmp_stacksize: str = "2G"
    apptainer_executable: str = "apptainer"
    sbatch_executable: str = "sbatch"
    scancel_executable: str = "scancel"
    sacct_executable: str = "sacct"
    squeue_executable: str = "squeue"
    ssh_executable: str = "ssh"
    scp_executable: str = "scp"

    def __post_init__(self) -> None:
        object.__setattr__(self, "modules", tuple(self.modules))
        object.__setattr__(self, "ld_library_path", tuple(self.ld_library_path))
        object.__setattr__(self, "environment", dict(self.environment))
        problems = _profile_problems(self)
        if problems:
            raise ApptainerProfileError(problems)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["modules"] = list(self.modules)
        data["ld_library_path"] = list(self.ld_library_path)
        return data


def _safe_posix(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_REMOTE_PATH.fullmatch(value))
        and not any(part in {".", ".."} for part in value.split("/"))
    )


def _profile_problems(p: ApptainerSiteProfile) -> list[str]:
    bad: list[str] = []
    for name in ("site_name", "ssh_user", "partition", "account", "qos", "nodelist"):
        v = getattr(p, name)
        if v is not None and not (isinstance(v, str) and _TOKEN.fullmatch(v)):
            bad.append(f"{name} must be a safe token (letters, digits, . _ + -)")
    if not (isinstance(p.host, str) and _TOKEN.fullmatch(p.host)):
        bad.append("host must be a hostname token without shell characters")
    if type(p.ssh_port) is not int or not 1 <= p.ssh_port <= 65535:
        bad.append("ssh_port must be an integer from 1 through 65535")
    for name in ("scratch_root", "node_scratch_root", "image", "hecras_dir"):
        if not _safe_posix(getattr(p, name)):
            bad.append(f"{name} must be a safe absolute POSIX path")
    for entry in p.ld_library_path:
        if not _safe_posix(entry):
            bad.append(f"ld_library_path entry {entry!r} must be a safe absolute POSIX path")
    if not p.ld_library_path:
        bad.append("ld_library_path must not be empty")
    if not (isinstance(p.apptainer_image_sha256, str) and _SHA256.fullmatch(p.apptainer_image_sha256)):
        bad.append("apptainer_image_sha256 is required and must be a lowercase 64-hex SHA-256")
    if not (isinstance(p.container_identity, str) and _CONTAINER_IDENTITY.fullmatch(p.container_identity)):
        bad.append(
            "container_identity must be an immutable reference: "
            "'sif:sha256:<hex>' or '<registry>/<repo>@sha256:<hex>' (mutable tags are rejected)"
        )
    if not (isinstance(p.ras_version, str) and re.fullmatch(r"6\.[0-9]+(?:\.[0-9]+)?", p.ras_version)):
        bad.append("ras_version must look like '6.6' (native Linux unsteady is HEC-RAS 6.x)")
    if type(p.num_cores) is not int or not 1 <= p.num_cores <= 256:
        bad.append("num_cores must be an integer from 1 through 256")
    if p.slurm_memory is not None and not (isinstance(p.slurm_memory, str) and _MEMORY.fullmatch(p.slurm_memory)):
        bad.append("slurm_memory must be omitted or look like '14336M' or '14G'")
    if not (isinstance(p.time_limit, str) and _TIME.fullmatch(p.time_limit)):
        bad.append("time_limit must use [[days-]HH:]MM:SS form")
    for module in p.modules:
        if not (isinstance(module, str) and _MODULE.fullmatch(module)):
            bad.append(f"module name {module!r} contains unsupported shell characters")
    for key, value in p.environment.items():
        if not _ENV_NAME.fullmatch(str(key)) or "\x00" in str(value) or "\n" in str(value):
            bad.append(f"environment entry {key!r} is invalid")
    if type(p.geom_preprocess) is not bool:
        bad.append("geom_preprocess must be true or false")
    if type(p.stack_unlimited) is not bool:
        bad.append("stack_unlimited must be true or false")
    for name in ("omp_stacksize", "kmp_stacksize"):
        if not (isinstance(getattr(p, name), str) and _STACK_SIZE.fullmatch(getattr(p, name))):
            bad.append(f"{name} must look like '2G' or '512M'")
    if not (isinstance(p.oci_source, str) and _OCI_SOURCE.fullmatch(p.oci_source)):
        bad.append(
            "oci_source must look like 'docker://<repo>:<tag>' or "
            "'docker://<repo>@sha256:<digest>'"
        )
    for name in ("identity_file", "known_hosts_file"):
        v = getattr(p, name)
        if v is not None and (not isinstance(v, str) or "\x00" in v):
            bad.append(f"{name} must be a path string")
    for name in ("apptainer_executable", "sbatch_executable", "scancel_executable", "sacct_executable",
                 "squeue_executable", "ssh_executable", "scp_executable"):
        value = getattr(p, name)
        if not (isinstance(value, str) and (_MODULE.fullmatch(value) or _safe_posix(value))):
            bad.append(f"{name} contains unsupported characters")
    return bad


# --------------------------------------------------------------------------
# Results and receipt
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ApptainerJob:
    """Durable handle for a rendered (and possibly submitted) job."""

    job_name: str
    request_sha256: str
    job_directory: Path
    remote_directory: str
    project_name: str
    plan_number: str
    geometry_token: str
    attempt_id: str
    state: str = "RENDERED"  # RENDERED | SUBMITTING | SUBMITTED
    slurm_job_id: Optional[str] = None
    dry_run: bool = False
    submitted_at: Optional[str] = None

    @property
    def script_path(self) -> Path:
        return Path(self.job_directory) / "job.sh"


@dataclass(frozen=True)
class ApptainerStatus:
    """Scheduler view of the allocation. ``state`` is UNKNOWN until accounting appears."""

    slurm_job_id: str
    state: str
    terminal: bool
    exit_code: Optional[str] = None
    elapsed: Optional[str] = None
    node: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class ApptainerCollection:
    """Collected evidence. ``success`` needs scheduler AND receipt AND hash agreement."""

    slurm_job_id: str
    scheduler_state: str
    directory: Path
    receipt: Optional[dict]
    success: bool
    problems: tuple[str, ...] = ()


def validate_receipt(payload: Any) -> dict:
    """Validate the receipt schema; raise ValueError on any inconsistency."""
    required = {
        "schema", "request_sha256", "job_name", "slurm_job_id", "node",
        "container_identity", "apptainer_image_sha256", "status", "reason_code",
        "exit_code", "started_at", "finished_at", "elapsed_seconds", "num_cores",
        "input_hashes", "outputs", "copy_verified", "dss_output_rewrite", "detail",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        missing = sorted(required - set(payload)) if isinstance(payload, dict) else "not an object"
        extra = sorted(set(payload) - required) if isinstance(payload, dict) else ""
        raise ValueError(f"Invalid receipt fields (missing={missing}, extra={extra})")
    if payload["schema"] != RECEIPT_SCHEMA:
        raise ValueError("Unsupported receipt schema")
    for key in ("request_sha256", "apptainer_image_sha256"):
        if not _SHA256.fullmatch(str(payload[key])):
            raise ValueError(f"Invalid receipt {key}")
    if not _JOB_ID.fullmatch(str(payload["slurm_job_id"])):
        raise ValueError("Invalid receipt slurm_job_id")
    if type(payload["exit_code"]) is not int or type(payload["copy_verified"]) is not bool:
        raise ValueError("Invalid receipt exit_code/copy_verified")
    rewrite = payload["dss_output_rewrite"]
    if rewrite is not None:
        if (not isinstance(rewrite, dict) or set(rewrite) != {"input", "source_path", "staged_path"}
                or not _SAFE_NAME.fullmatch(str(rewrite["input"]))
                or not isinstance(rewrite["source_path"], str)
                or not _SAFE_NAME.fullmatch(str(rewrite["staged_path"]))):
            raise ValueError("Invalid receipt dss_output_rewrite")
    if payload["status"] not in {"succeeded", "failed"}:
        raise ValueError("Invalid receipt status")
    if payload["status"] == "succeeded" and (
        payload["exit_code"] != 0 or not payload["copy_verified"]
        or payload["reason_code"] != "COMPLETED" or not payload["outputs"]
    ):
        raise ValueError("Inconsistent successful receipt")
    if payload["status"] == "failed" and payload["reason_code"] == "COMPLETED":
        raise ValueError("Inconsistent failed receipt")
    for key in ("started_at", "finished_at"):
        if datetime.fromisoformat(payload[key]).tzinfo is None:
            raise ValueError(f"Receipt {key} must include a timezone")
    if type(payload["elapsed_seconds"]) not in {int, float} or payload["elapsed_seconds"] < 0:
        raise ValueError("Invalid receipt elapsed_seconds")
    for key in ("input_hashes", "outputs"):
        if not isinstance(payload[key], dict):
            raise ValueError(f"Receipt {key} must be an object")
        for name, record in payload[key].items():
            parts = re.split(r"[\\\\/]", name)
            if name.startswith(("/", "\\")) or any(x in {"", ".", ".."} for x in parts):
                raise ValueError(f"Unsafe receipt path: {name!r}")
            if (not isinstance(record, dict) or set(record) != {"sha256", "size_bytes"}
                    or type(record["size_bytes"]) is not int or record["size_bytes"] < 0
                    or not _SHA256.fullmatch(str(record["sha256"]))):
                raise ValueError(f"Invalid artifact record for {name!r}")
    return payload


# --------------------------------------------------------------------------
# Transport (pluggable, mockable)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class ApptainerTransport:
    """Interface used by submit/status/collect. Subclass or mock in tests."""

    def run(self, argv: Sequence[str], timeout: Optional[float] = None) -> CommandResult:
        raise NotImplementedError

    def put_tree(self, local_dir: Path, remote_dir: str) -> None:
        """Copy the contents of ``local_dir`` into the existing ``remote_dir``."""
        raise NotImplementedError

    def get_tree(self, remote_dir: str, local_dir: Path) -> None:
        """Copy the contents of ``remote_dir`` into the new local ``local_dir``."""
        raise NotImplementedError


class SshApptainerTransport(ApptainerTransport):
    """OpenSSH/scp transport. Host keys are always checked (StrictHostKeyChecking=yes)."""

    def __init__(self, profile: ApptainerSiteProfile):
        self.profile = profile

    def _options(self, port_flag: str) -> list[str]:
        p = self.profile
        opts = [port_flag, str(p.ssh_port), "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=yes"]
        if p.identity_file:
            opts += ["-i", p.identity_file, "-o", "IdentitiesOnly=yes"]
        if p.known_hosts_file:
            opts += ["-o", f"UserKnownHostsFile={p.known_hosts_file}"]
        return opts

    def _target(self) -> str:
        return f"{self.profile.ssh_user}@{self.profile.host}"

    def run(self, argv: Sequence[str], timeout: Optional[float] = None) -> CommandResult:
        command = [self.profile.ssh_executable, *self._options("-p"), self._target(),
                   "--", shlex.join([str(a) for a in argv])]
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return CommandResult(done.returncode, done.stdout, done.stderr)

    def put_tree(self, local_dir: Path, remote_dir: str) -> None:
        command = [self.profile.scp_executable, "-r", *self._options("-P"),
                   f"{Path(local_dir)}/.", f"{self._target()}:{remote_dir}/"]
        subprocess.run(command, check=True, capture_output=True, text=True)

    def get_tree(self, remote_dir: str, local_dir: Path) -> None:
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=False)
        command = [self.profile.scp_executable, "-r", *self._options("-P"),
                   f"{self._target()}:{remote_dir}/.", str(local_dir)]
        subprocess.run(command, check=True, capture_output=True, text=True)


# --------------------------------------------------------------------------
# Pre-submit input check (solver-ready tmp.hdf)
# --------------------------------------------------------------------------

_PRECIP_GROUP = "Event Conditions/Meteorology/Precipitation"
_PRECIP_DATASETS = ("Cell Indexes", "Cell Info", "Cell Weights",
                    "Face Indexes", "Face Info", "Face Weights")
# ``Cells Minimum Elevation`` legitimately contains NaN in ghost cells.  Every
# other floating property table emitted for a 2D area is solver input and must
# be finite.  The named list documents the HEC-RAS 6.6 tables; the traversal
# below deliberately also catches future floating property tables.
_NAN_CHUNK_ROWS = 1_000_000


class InputCheckError(ValueError):
    """The tmp.hdf is not solver-ready; ``problems`` lists every finding."""

    def __init__(self, tmp_hdf: Union[str, Path], problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__(f"{tmp_hdf} is not solver-ready:\n- " + "\n- ".join(self.problems))


def _area_names(hdf: Any) -> list[str]:
    import h5py
    base = "Geometry/2D Flow Areas"
    if base not in hdf:
        return []
    group = hdf[base]
    attrs = group.get("Attributes")
    if attrs is not None and attrs.dtype.names and "Name" in attrs.dtype.names:
        return [n.decode("utf-8", "replace").strip() if isinstance(n, bytes) else str(n).strip()
                for n in attrs["Name"]]
    return [k for k, v in group.items() if isinstance(v, h5py.Group)]


def check_solver_ready(tmp_hdf: Union[str, Path], *, geom_preprocess: bool = False) -> list[str]:
    """Return the problems that would crash the Linux solver; an empty list means ready.

    Opens the LOCAL, completed file read-only with HDF5 locking disabled. Never call this
    on a tmp.hdf that HEC-RAS is still writing. Checks: (1) when gridded precipitation is
    present, every 2D area has the
    ``.../Precipitation/2D Flow Areas/<area>/`` interpolation datasets, non-empty; (2) the 2D
    property tables contain no NaN; and (3) unless ``geom_preprocess=True`` (for an image that
    ships ``RasGeomPreprocess``), ``/Geometry/GeomPreprocess`` is present and non-empty.
    2D-specific checks are skipped for valid 1D/storage-area-only plans.
    """
    import h5py
    import numpy as np

    problems: list[str] = []
    try:
        hdf = h5py.File(str(tmp_hdf), "r", locking=False)
    except (OSError, TypeError) as exc:
        return [f"cannot open as HDF5: {exc}"]
    with hdf:
        areas = _area_names(hdf)
        if not geom_preprocess:
            geompre = hdf.get("Geometry/GeomPreprocess")
            if (geompre is None or not hasattr(geompre, "keys") or not len(geompre)):
                problems.append(
                    "missing or empty Geometry/GeomPreprocess; this profile does not run "
                    "RasGeomPreprocess in the image"
                )
        precip = hdf.get(_PRECIP_GROUP)
        mode = precip.attrs.get("Mode") if precip is not None else None
        if isinstance(mode, bytes):
            mode = mode.decode("utf-8", "replace")
        # Older completed HDFs did not persist Mode, so retain Values as a conservative
        # compatibility signal.  A non-gridded explicit mode always wins.
        gridded = bool(precip is not None and (
            str(mode).strip().casefold() == "gridded" or
            (mode is None and f"{_PRECIP_GROUP}/Values" in hdf)
        ))
        for area in areas:
            if gridded:
                base = f"{_PRECIP_GROUP}/2D Flow Areas/{area}"
                if base not in hdf:
                    problems.append(
                        f"missing {base}/ (gridded precipitation present; the solver fails with "
                        "'2D Flow Areas folder not found'; written by the Windows engine at start-up)")
                else:
                    for name in _PRECIP_DATASETS:
                        node = hdf.get(f"{base}/{name}")
                        if node is None or not getattr(node, "shape", None) or node.shape[0] == 0:
                            problems.append(f"missing or empty {base}/{name}")
            area_group = hdf[f"Geometry/2D Flow Areas/{area}"]
            float_tables: list[tuple[str, Any]] = []

            def find_float_tables(name: str, node: Any) -> None:
                if (getattr(node, "dtype", None) is not None and node.dtype.kind == "f"
                        and node.shape and name != "Cells Minimum Elevation"):
                    float_tables.append((name, node))

            area_group.visititems(find_float_tables)
            for table, node in float_tables:
                for start in range(0, node.shape[0], _NAN_CHUNK_ROWS):
                    if np.isnan(node[start:start + _NAN_CHUNK_ROWS]).any():
                        problems.append(
                            f"NaN in Geometry/2D Flow Areas/{area}/{table} (solver SIGSEGV)"
                        )
                        break
    return problems


# --------------------------------------------------------------------------
# Script templates
# --------------------------------------------------------------------------
# ENGINE_SCRIPT_TEMPLATE is the ONLY place that knows how the HEC-RAS 6.6 Linux
# binary is invoked inside the image. It mirrors RasCmdr.compute_plan_linux
# (io.* aliases, LD_LIBRARY_PATH, ``RasUnsteady <proj>.p##.tmp.hdf x##``) and the
# CLB T7.1 cluster scripts. If the image contract changes (different binary
# path, extra preprocessing, different validation), change this template only.
# Placeholders are ``@NAME@`` and are filled by ``_render_engine_script``.

ENGINE_SCRIPT_TEMPLATE = """#!/bin/bash
# Runs INSIDE the Apptainer image, cwd /job (writable node-scratch copy).
set -u
PROJECT=@PROJECT@
PLAN=@PLAN@
XTOKEN=@XTOKEN@
HECRAS=@HECRAS_DIR@
export LD_LIBRARY_PATH=@LD_LIBRARY_PATH@
export OMP_NUM_THREADS=@CORES@
export MKL_NUM_THREADS=@CORES@
@STACK@
cd /job || exit 1

# The Fortran solver opens files by the base name "io" (see RasCmdr.compute_plan_linux).
for f in "$PROJECT".*; do
  ln -s "$f" "io.${f#"$PROJECT".}"
done
ln -s "$PROJECT.b$PLAN" io.b
ln -s "$PROJECT.$XTOKEN" io.X
ln -s "$PROJECT.$XTOKEN" io.x
@GEOM_PREPROCESS@
"$HECRAS/RasUnsteady" "$PROJECT.p$PLAN.tmp.hdf" "$XTOKEN" > solver.log 2>&1 &
SOLVER_PID=$!
trap 'kill -TERM "$SOLVER_PID" 2>/dev/null; wait "$SOLVER_PID"; exit 143' TERM
wait "$SOLVER_PID"
RC=$?
find . -maxdepth 1 -type l -name 'io.*' -delete
[ "$RC" -eq 0 ] || exit "$RC"

grep -qi 'Finished Unsteady Flow Simulation' solver.log || { echo 'missing completion banner' >&2; exit 4; }
if grep -Eqi 'encountered an error|did not complete|failed to converge|computations were stopped|fatal error|forrtl:|segmentation fault|^\\s*(error\\s*:|hdf_error\\b)' solver.log; then
  echo 'fatal solver message' >&2; exit 4
fi
mv "$PROJECT.p$PLAN.tmp.hdf" "$PROJECT.p$PLAN.hdf" || exit 4
exit 0
"""

_GEOM_PREPROCESS_BLOCK = """"$HECRAS/RasGeomPreprocess" "$PROJECT.p$PLAN.tmp.hdf" "$XTOKEN" > geompre.log 2>&1 || exit 3
grep -q 'Finished Processing Geometry' geompre.log || exit 3"""

JOB_SCRIPT_TEMPLATE = """#!/bin/bash
@SBATCH@
set -u
umask 002
@MODULES@
JOB_ROOT=@JOB_ROOT@
IMAGE=@IMAGE@
IMAGE_SHA256=@IMAGE_SHA@
ENGINE_SHA256=@ENGINE_SHA@
REQUEST_SHA256=@REQUEST_SHA@
JOB_NAME=@JOB_NAME@
CONTAINER_IDENTITY=@IDENTITY@
NUM_CORES=@CORES@
NODE_SCRATCH_ROOT=@NODE_SCRATCH@
APPTAINER=@APPTAINER@
PROJECT=@PROJECT@
PLAN=@PLAN@
XTOKEN=@XTOKEN@
DSS_OUTPUT_REWRITE=@DSS_OUTPUT_REWRITE@
@ENVIRONMENT@
OUT_FINAL="$JOB_ROOT/out/$SLURM_JOB_ID"
OUT="$OUT_FINAL.partial"
SCRATCH="$NODE_SCRATCH_ROOT/$SLURM_JOB_ID/ras"
WORK="$SCRATCH/job"
STARTED=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
T0=$SECONDS
STATUS=failed; REASON=LAUNCH_FAILED; DETAIL=""; RC=1; COPY_OK=false
ENGINE_PID=""; TERMINATED=0
trap 'TERMINATED=1; [ -n "$ENGINE_PID" ] && kill -TERM "$ENGINE_PID" 2>/dev/null' TERM

sha_of() { sha256sum < "$1" | cut -d' ' -f1; }

inventory_json() {  # inventory_json <dir> <name-prefix>
  local dir=$1 prefix=$2 sep="" f n
  while IFS= read -r f; do
    n=${f#"$dir"/}
    printf '%s\\n    ' "$sep"
    json_string "$prefix$n"
    printf ': {"sha256": "%s", "size_bytes": %s}' "$(sha_of "$f")" "$(stat -c %s "$f")"
    sep=","
  done < <(find "$dir" -type f ! -name SHA256SUMS ! -name receipt.json | LC_ALL=C sort)
}

json_string() {  # JSON string without assuming python/jq in the image.
  local value=$1
  local char char_code i
  printf '"'
  for ((i=0; i<${#value}; i++)); do
    char=${value:i:1}
    case "$char" in
      '"') printf '%s' '\\\"' ;;
      $'\\n') printf '%s' '\\n' ;;
      $'\\r') printf '%s' '\\r' ;;
      $'\\t') printf '%s' '\\t' ;;
      *) printf -v char_code '%d' "'$char"; if [ "$char_code" -eq 92 ]; then printf '%s' '\\\\\\\\'; else printf '%s' "$char"; fi ;;
    esac
  done
  printf '"'
}

write_receipt() {
  local finished node
  finished=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
  node=${SLURMD_NODENAME:-unknown}
  {
    printf '{\\n'
    printf '  "schema": "ras-commander-apptainer-receipt/v1",\\n'
    printf '  "request_sha256": "%s",\\n' "$REQUEST_SHA256"
    printf '  "job_name": '; json_string "$JOB_NAME"; printf ',\\n'
    printf '  "slurm_job_id": '; json_string "$SLURM_JOB_ID"; printf ',\\n'
    printf '  "node": '; json_string "$node"; printf ',\\n'
    printf '  "container_identity": '; json_string "$CONTAINER_IDENTITY"; printf ',\\n'
    printf '  "apptainer_image_sha256": '; json_string "$IMAGE_SHA256"; printf ',\\n'
    printf '  "status": '; json_string "$STATUS"; printf ',\\n'
    printf '  "reason_code": '; json_string "$REASON"; printf ',\\n'
    printf '  "exit_code": %s,\\n' "$RC"
    printf '  "started_at": "%s",\\n' "$STARTED"
    printf '  "finished_at": "%s",\\n' "$finished"
    printf '  "elapsed_seconds": %s,\\n' "$((SECONDS - T0))"
    printf '  "num_cores": %s,\\n' "$NUM_CORES"
    printf '  "input_hashes": {%s\\n  },\\n' "$(inventory_json "$JOB_ROOT/inputs" "")"
    printf '  "outputs": {%s\\n  },\\n' "$(inventory_json "$OUT" "")"
    printf '  "copy_verified": %s,\\n' "$COPY_OK"
    printf '  "dss_output_rewrite": %s,\\n' "$DSS_OUTPUT_REWRITE"
    printf '  "detail": '; json_string "$DETAIL"; printf '\\n'
    printf '}\\n'
  } > "$OUT/receipt.json"
}

copy_back() {
  mkdir -p "$OUT/project" "$OUT/logs" || return 1
  local f n sum
  for f in "$WORK"/*; do
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    n=$(basename "$f"); sum=$(sha_of "$f")
    # Unchanged staged inputs are not copied back; everything else is hash-verified.
    if grep -qxF "$sum  $n" "$SCRATCH/input.sha256"; then continue; fi
    cp -p "$f" "$OUT/project/$n" || return 1
    [ "$(sha_of "$OUT/project/$n")" = "$sum" ] || return 1
  done
  [ -f "$SCRATCH/engine.log" ] && cp -p "$SCRATCH/engine.log" "$OUT/logs/engine.log"
  return 0
}

run_job() {
  [ "$(sha_of "$IMAGE")" = "$IMAGE_SHA256" ] || { REASON=IMAGE_MISMATCH; return 1; }
  [ "$(sha_of "$JOB_ROOT/engine.sh")" = "$ENGINE_SHA256" ] || { REASON=ENGINE_SCRIPT_MISMATCH; return 1; }
  (cd "$JOB_ROOT/inputs" && sha256sum --quiet -c SHA256SUMS) || { REASON=INPUT_MISMATCH; return 1; }
  mkdir -p "$WORK" "$SCRATCH/tmp" "$SCRATCH/control" || { REASON=SCRATCH_FAILED; return 1; }
  while read -r _ name; do
    cp -p "$JOB_ROOT/inputs/$name" "$WORK/$name" || { REASON=STAGE_FAILED; return 1; }
  done < "$JOB_ROOT/inputs/SHA256SUMS"
  cp -p "$JOB_ROOT/inputs/SHA256SUMS" "$SCRATCH/input.sha256"
  cp -p "$JOB_ROOT/engine.sh" "$SCRATCH/control/engine.sh"
  (cd "$WORK" && sha256sum --quiet -c "$SCRATCH/input.sha256") || { REASON=STAGE_MISMATCH; return 1; }
  @HOST_STACK@

  "$APPTAINER" exec --cleanenv \\
    --bind "$WORK:/job" --bind "$SCRATCH/control:/control:ro" --bind "$SCRATCH/tmp:/tmp" \\
    --pwd /job "$IMAGE" bash /control/engine.sh > "$SCRATCH/engine.log" 2>&1 &
  ENGINE_PID=$!
  wait "$ENGINE_PID"; RC=$?
  if [ "$TERMINATED" -eq 1 ]; then wait "$ENGINE_PID" 2>/dev/null; REASON=TERMINATED; return 1; fi
  if [ "$RC" -ne 0 ]; then REASON=COMPUTE_FAILED; return 1; fi
  REASON=COMPLETED
  return 0
}

run_job
JOB_OK=$?
mkdir -p "$JOB_ROOT/out" && mkdir "$OUT" || { echo "output directory exists: $OUT" >&2; exit 2; }
mkdir -p "$OUT/logs" || { echo "could not create output logs directory" >&2; exit 2; }
# Preserve scheduler stdout even when image/input/scratch staging fails before copy-back.
[ -f "$JOB_ROOT/slurm-$SLURM_JOB_ID.out" ] && cp -p "$JOB_ROOT/slurm-$SLURM_JOB_ID.out" "$OUT/logs/slurm-$SLURM_JOB_ID.out"
if [ -d "$WORK" ]; then
  if copy_back; then COPY_OK=true; else REASON=COPY_BACK_FAILED; DETAIL="copy-back or hash verification failed"; fi
fi
if [ "$JOB_OK" -eq 0 ] && [ "$COPY_OK" = true ]; then STATUS=succeeded; RC=0; else STATUS=failed; [ "$RC" -ne 0 ] || RC=1; fi
[ "$STATUS" = succeeded ] || [ "$REASON" != COMPLETED ] || REASON=COPY_BACK_FAILED
write_receipt
(cd "$OUT" && find . -type f ! -name SHA256SUMS | LC_ALL=C sort | sed 's#^\\./##' | xargs -d '\\n' sha256sum > SHA256SUMS)
mv "$OUT" "$OUT_FINAL" || exit 2
# Failed scratch is preserved as diagnostic evidence; only a verified success is removed.
if [ "$STATUS" = succeeded ]; then rm -rf "$NODE_SCRATCH_ROOT/$SLURM_JOB_ID/ras"; fi
[ "$STATUS" = succeeded ]
"""


def _fill(template: str, values: Mapping[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace(f"@{key}@", value)
    leftover = re.findall(r"@[A-Z_]+@", out)
    if leftover:
        raise RuntimeError(f"Unfilled template placeholders: {sorted(set(leftover))}")
    return out


def _stack_block(profile: ApptainerSiteProfile) -> str:
    """Stack settings the solver needs on large 2D meshes (SIGSEGV at the first wet step otherwise)."""
    lines = []
    if profile.stack_unlimited:
        lines.append("ulimit -s unlimited || { echo 'ulimit -s unlimited refused' >&2; exit 5; }")
    lines.append(f"export OMP_STACKSIZE={shlex.quote(profile.omp_stacksize)}")
    lines.append(f"export KMP_STACKSIZE={shlex.quote(profile.kmp_stacksize)}")
    return "\n".join(lines)


def _host_stack_block(profile: ApptainerSiteProfile) -> str:
    """Return the host-side limit check only when unlimited stack is requested."""
    if not profile.stack_unlimited:
        return ""
    return ('ulimit -s unlimited || { REASON=STACK_LIMIT_FAILED; '
            'DETAIL="host ulimit -s unlimited failed"; return 1; }')


def _render_engine_script(profile: ApptainerSiteProfile, project: str, plan: str, xtoken: str) -> str:
    return _fill(ENGINE_SCRIPT_TEMPLATE, {
        "PROJECT": shlex.quote(project),
        "PLAN": shlex.quote(plan),
        "XTOKEN": shlex.quote(xtoken),
        "HECRAS_DIR": shlex.quote(profile.hecras_dir),
        "LD_LIBRARY_PATH": shlex.quote(":".join(profile.ld_library_path)),
        "CORES": str(profile.num_cores),
        "STACK": _stack_block(profile),
        "GEOM_PREPROCESS": _GEOM_PREPROCESS_BLOCK if profile.geom_preprocess else "",
    })


def _sbatch_directives(profile: ApptainerSiteProfile, job_name: str, remote_dir: str) -> str:
    lines = [f"#SBATCH --job-name={job_name}"]
    for flag, value in (("account", profile.account), ("partition", profile.partition),
                        ("qos", profile.qos), ("nodelist", profile.nodelist)):
        if value:
            lines.append(f"#SBATCH --{flag}={value}")
    lines += ["#SBATCH --nodes=1", "#SBATCH --ntasks=1",
              f"#SBATCH --cpus-per-task={profile.num_cores}"]
    if profile.slurm_memory:
        lines.append(f"#SBATCH --mem={profile.slurm_memory}")
    lines += [f"#SBATCH --time={profile.time_limit}",
              f"#SBATCH --output={remote_dir}/slurm-%j.out",
              "#SBATCH --signal=B:TERM@600"]
    return "\n".join(lines)


def _plan_geometry_token(project_folder: Path, project: str, plan: str) -> str:
    plan_file = project_folder / f"{project}.p{plan}"
    if not plan_file.is_file():
        raise FileNotFoundError(f"Plan file not found: {plan_file}")
    for line in plan_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Geom File="):
            match = re.search(r"(\d+)", line.split("=", 1)[1])
            if match:
                return f"x{match.group(1)}"
            break
    raise ValueError(f"No parseable 'Geom File=' entry in {plan_file}; refusing to guess the x-file")


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _decode_hdf_string(value: Any) -> str:
    """Decode one HDF scalar string without changing its stored representation."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").rstrip("\x00")
    return str(value).rstrip("\x00")


def _gridded_dss_dependency(source_tmp_hdf: Path) -> Optional[dict[str, Any]]:
    """Resolve the external DSS dependency declared by a gridded plan HDF.

    This is deliberately limited to a materialized ``Mode=Gridded`` and
    ``Source=DSS`` precipitation group.  The referenced DSS must be a regular
    local file relative to the source temporary HDF; a staging job never
    follows an absolute or ambiguous reference.
    """
    import h5py

    source_tmp_hdf = Path(source_tmp_hdf)
    precipitation_path = "Event Conditions/Meteorology/Precipitation"
    with h5py.File(source_tmp_hdf, "r", locking=False) as hdf:
        precipitation = hdf.get(precipitation_path)
        if precipitation is None:
            return None
        mode = _decode_hdf_string(precipitation.attrs.get("Mode", ""))
        source = _decode_hdf_string(precipitation.attrs.get("Source", ""))
        if mode.strip().casefold() != "gridded" or source.strip().casefold() != "dss":
            return None
        if "DSS Filename" not in precipitation.attrs:
            raise ValueError("Gridded DSS precipitation lacks a DSS Filename attribute")
        reference_value = precipitation.attrs["DSS Filename"]
        reference = _decode_hdf_string(reference_value).strip()
        pathname = _decode_hdf_string(
            precipitation.attrs.get("DSS Pathname", "")
        ).strip()
        if not reference:
            raise ValueError("Gridded DSS precipitation has an empty DSS Filename")
        if not pathname:
            raise ValueError("Gridded DSS precipitation lacks a DSS Pathname attribute")
        windows_path = PureWindowsPath(reference)
        if (
            windows_path.is_absolute()
            or windows_path.drive
            or windows_path.root
            or Path(reference.replace("\\", "/")).is_absolute()
        ):
            raise ValueError(
                "Gridded DSS Filename must be relative to the source temporary HDF"
            )
        parts = windows_path.parts
        if not parts:
            raise ValueError("Gridded DSS Filename has no usable path components")
        source_dss = (source_tmp_hdf.parent / Path(*parts)).resolve()
        try:
            source_dss.relative_to(source_tmp_hdf.parent.resolve().parent)
        except ValueError as exc:
            raise ValueError(
                "Gridded DSS Filename escapes the source project's parent directory"
            ) from exc
        if (
            source_dss.suffix.casefold() != ".dss"
            or not source_dss.is_file()
            or source_dss.is_symlink()
        ):
            raise FileNotFoundError(
                "Gridded DSS dependency must be a regular existing .dss file: "
                f"{source_dss}"
            )
        attr_dtype = precipitation.attrs.get_id("DSS Filename").dtype
        capacity = attr_dtype.itemsize if attr_dtype.kind == "S" else None

    source_sha256 = sha256_file(source_dss)
    max_digest_chars = 20 if capacity is None else min(20, capacity - 5)
    if max_digest_chars < 12:
        raise ValueError(
            "DSS Filename attribute cannot hold a collision-resistant staged name"
        )
    staged_name = f"d{source_sha256[:max_digest_chars]}.dss"
    if not _SAFE_NAME.fullmatch(staged_name):  # defensive; name is digest-derived
        raise ValueError(f"Derived staged DSS filename is unsafe: {staged_name!r}")
    return {
        "source_reference": reference,
        "source_path": str(source_dss),
        "source_sha256": source_sha256,
        "source_size_bytes": source_dss.stat().st_size,
        "staged_name": staged_name,
        "dss_pathname": pathname,
        "filename_capacity": capacity,
    }


def _stage_gridded_dss_dependency(
    source_tmp_hdf: Path,
    staged_tmp_hdf: Path,
    inputs: Path,
    dependency: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy one declared DSS and rebind only the staged HDF's filename attr."""
    import h5py
    import numpy as np

    source_dss = Path(str(dependency["source_path"]))
    staged_name = str(dependency["staged_name"])
    staged_dss = Path(inputs) / staged_name
    if staged_dss.exists():
        raise FileExistsError(f"Staged DSS filename collision: {staged_dss.name}")
    if sha256_file(source_dss) != dependency["source_sha256"]:
        raise RuntimeError("Gridded DSS dependency changed while the job was being rendered")
    shutil.copyfile(source_dss, staged_dss)
    staged_sha256 = sha256_file(staged_dss)
    if staged_sha256 != dependency["source_sha256"]:
        raise RuntimeError("Staged gridded DSS hash does not match its source dependency")

    precipitation_path = "Event Conditions/Meteorology/Precipitation"
    preserve_names = ("Mode", "Source", "DSS Pathname", "Ratio")
    with h5py.File(staged_tmp_hdf, "r+", locking=False) as hdf:
        precipitation = hdf.get(precipitation_path)
        if precipitation is None or "DSS Filename" not in precipitation.attrs:
            raise ValueError("Staged HDF lost its gridded DSS Filename attribute")
        before_reference = _decode_hdf_string(
            precipitation.attrs["DSS Filename"]
        ).strip()
        if before_reference != dependency["source_reference"]:
            raise ValueError("Staged HDF DSS Filename differs from the resolved source reference")
        preserved = {
            name: precipitation.attrs.get(name)
            for name in preserve_names
        }
        attr_dtype = precipitation.attrs.get_id("DSS Filename").dtype
        encoded_name = staged_name.encode("utf-8")
        if attr_dtype.kind == "S":
            if len(encoded_name) > attr_dtype.itemsize:
                raise ValueError("Staged DSS filename exceeds the HDF attribute capacity")
            precipitation.attrs.modify("DSS Filename", np.bytes_(encoded_name))
        else:
            precipitation.attrs.modify("DSS Filename", staged_name)
        hdf.flush()

    with h5py.File(staged_tmp_hdf, "r", locking=False) as hdf:
        precipitation = hdf.get(precipitation_path)
        if precipitation is None:
            raise ValueError("Staged HDF lacks its precipitation group after rebinding")
        readback = _decode_hdf_string(precipitation.attrs.get("DSS Filename", "")).strip()
        if readback != staged_name:
            raise ValueError("Staged HDF DSS Filename did not persist exactly")
        for name, value in preserved.items():
            current = precipitation.attrs.get(name)
            if not np.array_equal(np.asarray(current), np.asarray(value)):
                raise ValueError(f"Staged HDF changed precipitation attribute {name!r}")
    return {
        **dict(dependency),
        "staged_sha256": staged_sha256,
        "staged_size_bytes": staged_dss.stat().st_size,
    }


def _rewrite_windows_dss_output(flow_path: Path, project_name: str) -> Optional[dict[str, str]]:
    """Rewrite a requested Windows DSS output path in the staged flow file only."""
    lines = flow_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not _WRITE_DSS_FILE.fullmatch(line.rstrip("\n")):
            continue
        for candidate_index in range(index + 1, len(lines)):
            candidate = lines[candidate_index]
            source_path = candidate.strip()
            if not source_path:
                continue
            if not _WINDOWS_ABSOLUTE_DSS.fullmatch(source_path):
                break
            replacement = f"{project_name}.dss"
            indent = candidate[:len(candidate) - len(candidate.lstrip())]
            ending = "\n" if candidate.endswith("\n") else ""
            lines[candidate_index] = f"{indent}{replacement}{ending}"
            flow_path.write_text("".join(lines), encoding="utf-8", newline="\n")
            return {
                "input": flow_path.name,
                "source_path": source_path,
                "staged_path": replacement,
            }
    return None


def _job_script_request_hash(script: str) -> str:
    """Hash the job script with its self-referential request value normalized."""
    normalized = re.sub(r"^(REQUEST_SHA256=).*$", r"\1<REQUEST_SHA256>", script,
                        flags=re.MULTILINE)
    normalized = re.sub(r"attempt-[0-9a-f]{32}", "attempt-<ATTEMPT_ID>", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _expected_simulation_end(tmp_hdf: Path) -> str:
    """Read the authoritative planned end time carried by the compiled HDF."""
    import h5py

    with h5py.File(tmp_hdf, "r", locking=False) as hdf:
        info = hdf.get("Plan Data/Plan Information")
        value = info.attrs.get("Simulation End Time") if info is not None else None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str) or not value.strip() or value.strip().casefold() == "unknown":
        raise ValueError("Compiled plan HDF lacks a usable Plan Data/Plan Information Simulation End Time")
    return value.strip()


def _load_request(job: ApptainerJob) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate the immutable render evidence before an external action."""
    payload = json.loads((Path(job.job_directory) / "job.json").read_text(encoding="utf-8"))
    request = payload.get("request")
    if not isinstance(request, dict) or _canonical_sha256(request) != job.request_sha256:
        raise RuntimeError("Rendered request evidence is missing or does not match this job handle")
    inputs = request.get("input_hashes")
    if not isinstance(inputs, dict) or not inputs:
        raise RuntimeError("Rendered request has no staged input hashes")
    input_dir = Path(job.job_directory) / "inputs"
    for name, digest in inputs.items():
        path = input_dir / name
        if not _SAFE_NAME.fullmatch(str(name)) or sha256_file(path) != digest:
            raise RuntimeError(f"Staged input does not match rendered request: {name}")
    manifest = input_dir / "SHA256SUMS"
    if sha256_file(manifest) != request.get("input_manifest_sha256"):
        raise RuntimeError("Staged SHA256SUMS does not match rendered request")
    engine = Path(job.job_directory) / "engine.sh"
    if sha256_file(engine) != request.get("engine_sha256"):
        raise RuntimeError("Staged engine.sh does not match rendered request")
    script = Path(job.job_directory) / "job.sh"
    script_text = script.read_text(encoding="utf-8")
    if _job_script_request_hash(script_text) != request.get("job_sha256"):
        raise RuntimeError("Staged job.sh does not match rendered request")
    if sha256_file(script) != payload.get("job_file_sha256"):
        raise RuntimeError("Staged job.sh file hash changed after rendering")
    return request, payload


def _remote_input_check_command(remote: str, request: Mapping[str, Any]) -> str:
    """Return a shell fragment that verifies expected hashes, not remote metadata."""
    checks = "".join(
        f"{request['input_hashes'][name]}  {name}\n" for name in sorted(request["input_hashes"])
    )
    return (
        f"cd {shlex.quote(remote)}/inputs && "
        f"test \"$(sha256sum SHA256SUMS | cut -d' ' -f1)\" = {shlex.quote(str(request['input_manifest_sha256']))} && "
        f"printf %s {shlex.quote(checks)} | sha256sum --quiet -c -"
    )


def _normal_time(value: Any) -> str:
    """Canonicalize HEC-RAS timestamps, including its end-of-day ``2400`` spelling."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = " ".join(str(value).upper().split())
    parts = text.split()
    if len(parts) != 2:
        return text
    clock = parts[1].replace(":", "")
    if not clock.isdigit() or len(clock) not in {3, 4, 6}:
        return text
    if len(clock) == 3:
        clock = f"0{clock}"
    if len(clock) == 4:
        clock += "00"
    hour, minute, second = int(clock[:2]), int(clock[2:4]), int(clock[4:])
    if hour > 24 or minute > 59 or second > 59 or (hour == 24 and (minute or second)):
        return text
    try:
        parsed = datetime.strptime(parts[0], "%d%b%Y")
    except ValueError:
        return text
    canonical = parsed + timedelta(hours=hour, minutes=minute, seconds=second)
    return canonical.strftime("%d%b%Y %H:%M:%S").upper()


def _validate_collected_solve(destination: Path, job: ApptainerJob,
                              expected_end: str) -> Optional[str]:
    """Validate the promoted solve artifact, including its exact final time."""
    from .RasCmdr import RasCmdr

    result_hdf = destination / "project" / f"{job.project_name}.p{job.plan_number}.hdf"
    solver_log = destination / "project" / "solver.log"
    ok, reason = RasCmdr._validate_linux_solve(solver_log, result_hdf, job.plan_number)
    if not ok:
        return reason
    try:
        import h5py

        stamps: list[str] = []
        with h5py.File(result_hdf, "r", locking=False) as hdf:
            def collect_stamps(name: str, node: Any) -> None:
                if (isinstance(node, h5py.Dataset) and name.startswith("Results/Unsteady/")
                        and name.endswith("Time Date Stamp") and node.size):
                    stamps.append(_normal_time(node[-1]))
            hdf.visititems(collect_stamps)
        if _normal_time(expected_end) not in stamps:
            return f"result HDF does not contain expected final simulation time {expected_end!r}"
    except Exception as exc:
        return f"could not validate final simulation time: {exc}"
    return None


# --------------------------------------------------------------------------
# Public static API
# --------------------------------------------------------------------------

class RasApptainer:
    """Static namespace for native HEC-RAS 6.6 unsteady execution via Slurm + Apptainer."""

    @staticmethod
    @log_call
    def check_solver_ready(tmp_hdf: Union[str, Path], *, geom_preprocess: bool = False) -> list[str]:
        """Return pre-submit solver-readiness findings for a completed tmp.hdf."""
        return check_solver_ready(tmp_hdf, geom_preprocess=geom_preprocess)

    @staticmethod
    @log_call
    def load_profile(path: Union[str, Path]) -> ApptainerSiteProfile:
        """Load and validate a site profile JSON; unknown fields are rejected."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return RasApptainer.profile_from_dict(data)

    @staticmethod
    def profile_from_dict(data: Mapping[str, Any]) -> ApptainerSiteProfile:
        if not isinstance(data, Mapping):
            raise ApptainerProfileError(["profile must be a JSON object"])
        data = dict(data)
        problems: list[str] = []
        schema = data.pop("schema", PROFILE_SCHEMA)
        if schema != PROFILE_SCHEMA:
            problems.append(f"unsupported schema {schema!r} (expected {PROFILE_SCHEMA!r})")
        data = {k: v for k, v in data.items() if not k.startswith("_")}  # "_comment" keys
        known = {f.name for f in fields(ApptainerSiteProfile)}
        # fim-commander's memory setting describes a task; this API requests one
        # task, so it is a safe fallback when the native Slurm memory is omitted.
        if "memory_per_task" in data and "slurm_memory" not in data:
            data["slurm_memory"] = data["memory_per_task"]
        fim_only = sorted(set(data) & _FIM_ONLY_FIELDS)
        for key in fim_only:
            logger.info("Ignoring fim-commander-only profile field %s for RasApptainer", key)
            data.pop(key)
        for key in sorted(set(data) - known):
            problems.append(f"unknown field {key!r}")
        for f in fields(ApptainerSiteProfile):
            if f.default is MISSING and f.default_factory is MISSING and f.name not in data:
                problems.append(f"missing required field {f.name!r}")
        if problems:
            raise ApptainerProfileError(problems)
        return ApptainerSiteProfile(**data)

    @staticmethod
    def pull_command(profile: ApptainerSiteProfile) -> str:
        """The one-time, administrator-run command that creates the shared SIF (not executed here).

        Run it on a node, then record the printed SHA-256 in the profile
        (``apptainer_image_sha256`` and ``container_identity: sif:sha256:<digest>``).
        """
        return (f"{shlex.quote(profile.apptainer_executable)} pull {shlex.quote(profile.image)} "
                f"{shlex.quote(profile.oci_source)} && sha256sum {shlex.quote(profile.image)}")

    @staticmethod
    @log_call
    def render_job(
        project_folder: Union[str, Path],
        project_name: str,
        plan_number: Union[str, int],
        profile: ApptainerSiteProfile,
        job_directory: Union[str, Path],
        check_inputs: bool = True,
    ) -> ApptainerJob:
        """Stage Windows-preprocessed artifacts and write the sbatch script. No SSH.

        With ``check_inputs`` (default) the local tmp.hdf is first verified solver-ready
        (:func:`check_solver_ready`); ``InputCheckError`` is raised before anything is staged.

        Writes ``job_directory`` containing ``inputs/`` (tmp.hdf, .b, .x with LF line
        endings, any declared external gridded-DSS input, and ``SHA256SUMS``),
        ``engine.sh``, ``job.sh`` and ``job.json``. The source project is never
        modified.
        """
        project_folder = Path(project_folder)
        job_directory = Path(job_directory)
        plan = f"{int(plan_number):02d}" if not isinstance(plan_number, str) else plan_number
        if not _PLAN_NUMBER.fullmatch(plan):
            raise ValueError("plan_number must be two digits, e.g. '01'")
        if not _SAFE_NAME.fullmatch(project_name):
            raise ValueError("project_name must contain only letters, digits, '.', '_' and '-'")
        xtoken = _plan_geometry_token(project_folder, project_name, plan)
        names = [f"{project_name}.p{plan}.tmp.hdf", f"{project_name}.b{plan}",
                 f"{project_name}.{xtoken}"]
        missing = [n for n in names if not (project_folder / n).is_file()]
        if missing:
            raise FileNotFoundError(
                f"Missing Windows preprocessing artifacts in {project_folder}: {missing}. "
                "Run RasPreprocess.preprocess_plan() first."
            )
        if job_directory.exists() and any(job_directory.iterdir()):
            raise FileExistsError(f"job_directory must be new or empty: {job_directory}")
        if check_inputs:
            problems = check_solver_ready(project_folder / names[0], geom_preprocess=profile.geom_preprocess)
            if problems:
                raise InputCheckError(project_folder / names[0], problems)
        gridded_dss_dependency = _gridded_dss_dependency(project_folder / names[0])
        inputs = job_directory / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)

        source_hashes: dict[str, str] = {}
        for name in names:
            source = project_folder / name
            source_hashes[name] = sha256_file(source)
            data = source.read_bytes() if not name.endswith(".hdf") else None
            if data is None:
                # Large HDF: stream copy, never text-converted.
                shutil.copyfile(source, inputs / name)
            else:
                (inputs / name).write_bytes(data.replace(b"\r\n", b"\n"))  # LF for Linux solver
        input_names = list(names)
        staged_gridded_dss = None
        if gridded_dss_dependency is not None:
            staged_gridded_dss = _stage_gridded_dss_dependency(
                project_folder / names[0],
                inputs / names[0],
                inputs,
                gridded_dss_dependency,
            )
            staged_name = str(staged_gridded_dss["staged_name"])
            source_hashes[staged_name] = str(staged_gridded_dss["source_sha256"])
            input_names.append(staged_name)
        dss_output_rewrite = _rewrite_windows_dss_output(inputs / names[1], project_name)
        # RasUnsteady reads these compiled-HDF attributes, not merely OMP/MKL.
        # The source tmp.hdf is immutable; only the staged copy is rewritten.
        from .RasCmdr import RasCmdr
        core_evidence = RasCmdr._set_linux_hdf_num_cores(inputs / names[0], profile.num_cores)
        if check_inputs:
            problems = check_solver_ready(
                inputs / names[0], geom_preprocess=profile.geom_preprocess
            )
            if problems:
                raise InputCheckError(inputs / names[0], problems)
        staged = {n: sha256_file(inputs / n) for n in input_names}
        (inputs / "SHA256SUMS").write_text(
            "".join(f"{staged[n]}  {n}\n" for n in sorted(input_names)), encoding="utf-8", newline="\n")
        manifest_sha = sha256_file(inputs / "SHA256SUMS")

        engine = _render_engine_script(profile, project_name, plan, xtoken)
        (job_directory / "engine.sh").write_text(engine, encoding="utf-8", newline="\n")
        engine_sha = sha256_file(job_directory / "engine.sh")

        profile_view = profile.to_dict()
        for local_only in ("identity_file", "known_hosts_file"):
            profile_view.pop(local_only, None)
        # Job names intentionally do not encode the request: the normalized script hash below
        # is part of the request, and a unique attempt path prevents staging collisions.
        job_name = f"{profile.site_name}-{project_name}-p{plan}"[:128]
        if not _TOKEN.fullmatch(job_name):
            raise ValueError(f"Derived job name is not a safe Slurm token: {job_name!r}")
        attempt_id = uuid.uuid4().hex
        remote_dir = f"{profile.scratch_root.rstrip('/')}/{job_name}/attempt-{attempt_id}"

        env_lines = "\n".join(f"export {k}={shlex.quote(str(v))}"
                              for k, v in sorted(profile.environment.items()))
        module_lines = "\n".join(f"module load {shlex.quote(m)}" for m in profile.modules)
        script_values = {
            "SBATCH": _sbatch_directives(profile, job_name, remote_dir),
            "MODULES": module_lines,
            "JOB_ROOT": shlex.quote(remote_dir),
            "IMAGE": shlex.quote(profile.image),
            "IMAGE_SHA": profile.apptainer_image_sha256,
            "ENGINE_SHA": engine_sha,
            "REQUEST_SHA": "<REQUEST_SHA256>",
            "JOB_NAME": shlex.quote(job_name),
            "IDENTITY": shlex.quote(profile.container_identity),
            "CORES": str(profile.num_cores),
            "NODE_SCRATCH": shlex.quote(profile.node_scratch_root.rstrip("/")),
            "APPTAINER": shlex.quote(profile.apptainer_executable),
            "PROJECT": shlex.quote(project_name),
            "PLAN": shlex.quote(plan),
            "XTOKEN": shlex.quote(xtoken),
            "DSS_OUTPUT_REWRITE": shlex.quote(json.dumps(dss_output_rewrite, separators=(",", ":"))),
            "HOST_STACK": _host_stack_block(profile),
            "ENVIRONMENT": env_lines,
        }
        template_job_sha = _job_script_request_hash(_fill(JOB_SCRIPT_TEMPLATE, script_values))
        request = {
            "schema": JOB_SCHEMA, "project": project_name, "plan": plan, "xtoken": xtoken,
            "input_hashes": staged, "input_manifest_sha256": manifest_sha,
            "engine_sha256": engine_sha, "job_sha256": template_job_sha,
            "expected_simulation_end": _expected_simulation_end(inputs / names[0]),
            "dss_output_rewrite": dss_output_rewrite,
            "gridded_dss_input": staged_gridded_dss,
            "profile": profile_view,
        }
        request_sha = _canonical_sha256(request)
        script_values["REQUEST_SHA"] = request_sha
        script = _fill(JOB_SCRIPT_TEMPLATE, script_values)
        (job_directory / "job.sh").write_text(script, encoding="utf-8", newline="\n")

        job = ApptainerJob(
            job_name=job_name, request_sha256=request_sha, job_directory=job_directory,
            remote_directory=remote_dir, project_name=project_name, plan_number=plan,
            geometry_token=xtoken, attempt_id=attempt_id,
        )
        RasApptainer._persist(job, extra={
            "source_input_sha256": source_hashes, "staged_input_sha256": staged,
            "core_evidence": core_evidence, "profile": profile_view, "request": request,
            "job_file_sha256": sha256_file(job_directory / "job.sh"),
        })
        return job

    @staticmethod
    def _persist(job: ApptainerJob, extra: Optional[Mapping[str, Any]] = None) -> None:
        path = Path(job.job_directory) / "job.json"
        payload: dict[str, Any] = {}
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        payload.update({"schema": JOB_SCHEMA, **(extra or {})})
        payload["job"] = {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(job).items()}
        atomic_write_json(path, payload)

    @staticmethod
    def load_job(job_directory: Union[str, Path]) -> ApptainerJob:
        """Reload a persisted handle (for status/collect from a later process)."""
        payload = json.loads((Path(job_directory) / "job.json").read_text(encoding="utf-8"))
        data = payload["job"]
        data["job_directory"] = Path(job_directory)
        return ApptainerJob(**data)

    @staticmethod
    @log_call
    def submit(
        job: ApptainerJob,
        transport: Optional[ApptainerTransport] = None,
        profile: Optional[ApptainerSiteProfile] = None,
        dry_run: bool = True,
    ) -> ApptainerJob:
        """Transfer the job folder and ``sbatch`` it. ``dry_run=True`` (default) never contacts SSH.

        The submission intent is persisted (state ``SUBMITTING``) before ``sbatch``; a job in
        that state is never resubmitted automatically because an ambiguous SSH failure may
        already have created the allocation. Reconcile on the cluster, then render a new job.
        """
        if dry_run:
            return replace(job, dry_run=True)
        if transport is None or profile is None:
            raise ValueError("A transport and profile are required unless dry_run=True")
        if profile.apptainer_image_sha256 == _ZERO_SHA256 or profile.container_identity.endswith(_ZERO_SHA256):
            raise ApptainerProfileError([
                "all-zero image digest is a placeholder and cannot be submitted; record the SIF SHA-256"
            ])
        # The caller may hold a stale immutable handle.  Consult durable state before
        # any remote reconciliation: only an untouched rendered attempt is safe to clean.
        job = RasApptainer.load_job(job.job_directory)
        if job.state != "RENDERED":
            raise RuntimeError(
                f"Job is in state {job.state}; refusing to submit again. "
                "Render a new job after reconciling the remote attempt."
            )
        request, _ = _load_request(job)
        remote = job.remote_directory
        root = remote.rsplit("/", 1)[0]
        # An interrupted upload can be retried only within its unique attempt
        # directory.  No request root or another attempt is ever reconciled.
        for argv in (["mkdir", "-p", root], ["bash", "-c",
                      f"rm -rf -- {shlex.quote(remote)} && mkdir -- {shlex.quote(remote)}"]):
            result = transport.run(argv)
            if result.returncode != 0:
                raise RuntimeError(f"Remote directory setup failed ({argv}): {result.stderr.strip()}")
        transport.put_tree(Path(job.job_directory), remote)
        check = transport.run(["bash", "-c", _remote_input_check_command(remote, request)])
        if check.returncode != 0:
            raise RuntimeError(
                f"Remote staged-input verification against request failed: {check.stderr.strip()}"
            )
        job = replace(job, state="SUBMITTING")
        RasApptainer._persist(job)
        result = transport.run([profile.sbatch_executable, "--parsable", f"{remote}/job.sh"])
        if result.returncode != 0:
            raise RuntimeError(
                "sbatch failed or its outcome is unknown; job left in SUBMITTING state: "
                + result.stderr.strip()
            )
        job_id = result.stdout.strip().split(";")[0]
        if not _JOB_ID.fullmatch(job_id):
            raise RuntimeError(f"Unparseable sbatch output: {result.stdout!r}")
        job = replace(job, state="SUBMITTED", slurm_job_id=job_id,
                      submitted_at=datetime.now(timezone.utc).isoformat())
        RasApptainer._persist(job)
        return job

    @staticmethod
    @log_call
    def status(job: ApptainerJob, transport: ApptainerTransport,
               profile: ApptainerSiteProfile) -> ApptainerStatus:
        """sacct-based status; falls back to squeue, then UNKNOWN until accounting appears."""
        if not job.slurm_job_id:
            raise ValueError("Job has not been submitted")
        jid = job.slurm_job_id
        result = transport.run([profile.sacct_executable, "-X", "-n", "-P", "-j", jid,
                                "-o", "JobID,State,ExitCode,Elapsed,NodeList"])
        sacct_reason = None
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                cols = line.split("|")
                if len(cols) >= 5 and cols[0] == jid:
                    state = cols[1].split()[0].rstrip("+") if cols[1].strip() else "UNKNOWN"
                    return ApptainerStatus(jid, state, state in TERMINAL_STATES,
                                           cols[2] or None, cols[3] or None, cols[4] or None)
        else:
            sacct_reason = f"sacct failed: {result.stderr.strip() or result.returncode}"
        queue = transport.run([profile.squeue_executable, "-h", "-j", jid, "-o", "%T"])
        if queue.returncode == 0 and queue.stdout.strip():
            state = queue.stdout.strip().split()[0]
            return ApptainerStatus(jid, state, state in TERMINAL_STATES, reason=sacct_reason)
        reason = sacct_reason or "sacct has no record yet"
        if queue.returncode != 0:
            reason += f"; squeue failed: {queue.stderr.strip() or queue.returncode}"
        return ApptainerStatus(jid, "UNKNOWN", False, reason=reason)

    @staticmethod
    @log_call
    def cancel(job: ApptainerJob, transport: ApptainerTransport,
               profile: ApptainerSiteProfile) -> CommandResult:
        """Cancel this explicitly identified allocation; no cluster contact occurs otherwise."""
        if not job.slurm_job_id:
            raise ValueError("Job has not been submitted")
        result = transport.run([profile.scancel_executable, job.slurm_job_id])
        if result.returncode != 0:
            raise RuntimeError(f"scancel failed for {job.slurm_job_id}: {result.stderr.strip()}")
        return result

    @staticmethod
    @log_call
    def collect(job: ApptainerJob, transport: ApptainerTransport,
                profile: ApptainerSiteProfile,
                destination: Optional[Union[str, Path]] = None) -> ApptainerCollection:
        """Download a terminal job's ``out/<jobid>`` folder and verify it.

        ``success`` requires: scheduler state COMPLETED, a schema-valid receipt bound to this
        request and Slurm job, a succeeded receipt, and every output hash matching locally.
        Failed jobs are collected too so their evidence is retained.
        """
        state = RasApptainer.status(job, transport, profile)
        if not state.terminal:
            raise RuntimeError(f"Job {state.slurm_job_id} is {state.state}; not terminal yet")
        dest = Path(destination) if destination else Path(job.job_directory) / "collected" / state.slurm_job_id
        if dest.exists():
            raise FileExistsError(f"Collect destination already exists: {dest}")
        request, _ = _load_request(job)
        transport.get_tree(f"{job.remote_directory}/out/{state.slurm_job_id}", dest)
        problems: list[str] = []
        receipt: Optional[dict] = None
        try:
            receipt = validate_receipt(json.loads((dest / "receipt.json").read_text(encoding="utf-8")))
            if receipt["request_sha256"] != job.request_sha256:
                problems.append("receipt request_sha256 does not match the submitted job")
            if receipt["slurm_job_id"] != state.slurm_job_id:
                problems.append("receipt slurm_job_id does not match the allocation")
            expected_image = request["profile"]["apptainer_image_sha256"]
            if receipt["apptainer_image_sha256"] != expected_image:
                problems.append("receipt image SHA-256 does not match the rendered request")
            if receipt["container_identity"] != request["profile"]["container_identity"]:
                problems.append("receipt container identity does not match the rendered request")
            expected_inputs = request["input_hashes"]
            if (set(receipt["input_hashes"]) != set(expected_inputs)
                    or any(receipt["input_hashes"][name]["sha256"] != digest
                           for name, digest in expected_inputs.items())):
                problems.append("receipt input hashes do not match the rendered request")
            if receipt["dss_output_rewrite"] != request.get("dss_output_rewrite"):
                problems.append("receipt DSS output rewrite does not match the rendered request")
            if receipt["status"] != "succeeded":
                problems.append(f"receipt reports {receipt['status']} ({receipt['reason_code']})")
            for name, record in receipt["outputs"].items():
                path = dest / name
                if not path.is_file() or path.stat().st_size != record["size_bytes"] \
                        or sha256_file(path) != record["sha256"]:
                    problems.append(f"output hash/size mismatch: {name}")
            if receipt["status"] == "succeeded":
                completion_problem = _validate_collected_solve(
                    dest, job, request["expected_simulation_end"]
                )
                if completion_problem:
                    problems.append(f"result validation failed: {completion_problem}")
        except (OSError, ValueError, KeyError) as exc:
            problems.append(f"receipt unusable: {exc}")
        if state.state != "COMPLETED":
            problems.append(f"scheduler state is {state.state}")
        return ApptainerCollection(state.slurm_job_id, state.state, dest, receipt,
                                   success=not problems, problems=tuple(problems))
