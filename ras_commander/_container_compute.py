"""Native Linux container worker; all solver execution uses :class:`RasCmdr`.

The host project is an input/output mount. The solver works on an isolated local
copy so its Fortran ``io.*`` links never depend on Windows bind-mount semantics.
"""

from __future__ import annotations

import argparse
import codecs
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

import h5py
import numpy as np

from .LoggingConfig import get_logger

logger = get_logger(__name__)
JOB_SCHEMA = "ras-commander-job/v1"
TIME_SERIES = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _confined(path, root):
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(Path(root).resolve())
    except ValueError as exc:
        raise ValueError(f"Path is outside the mounted job/runtime: {path}") from exc
    return resolved


def _file(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty required file: {path}")
    return path


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_copy(source, destination):
    destination = Path(destination)
    descriptor, name = tempfile.mkstemp(prefix="." + destination.name, dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target, Path(source).open("rb") as stream:
            shutil.copyfileobj(stream, target, 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact(path, root):
    path = Path(path)
    return {"path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def _acquire_job_lock(path, run_id):
    """Hold an OS lock; process exit also releases it after Docker termination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        if path.stat().st_size == 0:
            stream.write(b"\x00")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Do not unlink this inode on release: another process may already hold
        # an open descriptor to it. The advisory lock, not existence, owns the job.
        return stream
    except OSError as exc:
        stream.close()
        raise RuntimeError("This project/plan already has an active native compute") from exc


def _runtime(manifest_path, expected_version=None):
    manifest_path = _file(manifest_path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("schema") not in {"ras-commander-native-runtime/v1", "ras-commander-runtime/v1"}:
        raise ValueError("Unsupported native runtime manifest schema")
    version = data.get("hec_ras_version")
    if data.get("kind") != "native" or version not in {"6.5", "6.6", "7.0.1"}:
        raise ValueError("Native runtime must declare HEC-RAS 6.5, 6.6 or 7.0.1")
    if expected_version and version != expected_version:
        raise ValueError("Bundled native runtime does not match the image HEC-RAS version")
    root = manifest_path.parent.resolve()
    engine = _confined(root / data.get("native", {}).get("engine_directory", "engine"), root)
    executable = _file(engine / "RasUnsteady")
    if os.name != "nt" and not os.access(executable, os.X_OK):
        raise ValueError("Bundled RasUnsteady is not executable")
    if not (engine / "libs").is_dir():
        raise ValueError("Bundled native runtime is missing its vendor libs directory")
    artifacts = data.get("artifacts", [])
    declared = set()
    for item in artifacts:
        artifact = _file(_confined(root / item["path"], root))
        declared.add(artifact)
        if item.get("sha256") != _sha256(artifact):
            raise ValueError(f"Bundled runtime artifact mismatch: {item['path']}")
    if executable not in declared:
        raise ValueError("Runtime manifest does not identify the native solver executable")
    return engine, {"kind": "native", "hec_ras_version": version,
                    "manifest_sha256": _sha256(manifest_path),
                    "ras_commander_version": importlib.metadata.version("ras-commander"),
                    "ras_commander_commit": os.environ.get("RAS_COMMANDER_SOURCE_COMMIT")}


def _mesh(path, expected=None):
    """Validate the populated 2D mesh and bounded hydraulic property tables."""
    summary = {}
    with h5py.File(path, "r") as hdf:
        areas = hdf.get("Geometry/2D Flow Areas")
        if not isinstance(areas, h5py.Group):
            raise ValueError("Prepared HDF is missing Geometry/2D Flow Areas")
        for name, area in areas.items():
            if not isinstance(area, h5py.Group):
                continue
            coordinates = area.get("Cells Center Coordinate")
            if (coordinates is None or coordinates.ndim != 2
                    or coordinates.shape[1] != 2 or coordinates.shape[0] == 0
                    or not np.isfinite(coordinates[:]).all()):
                raise ValueError(f"Invalid or empty 2D cells in {name}")
            cells = len(coordinates)
            summary[name] = {"cells": cells}
            for label, width, rows in (("Cells Volume Elevation", 2, cells),
                                       ("Faces Area Elevation", 4, None)):
                info, values = area.get(label + " Info"), area.get(label + " Values")
                if (info is None or values is None or info.ndim != 2 or info.shape[1] != 2
                        or not len(info) or values.ndim != 2 or values.shape[1] != width
                        or not len(values) or (rows is not None and len(info) != rows)):
                    raise ValueError(f"Missing or invalid {label} tables in {name}")
                indexes = info[:]
                if (not np.isfinite(indexes).all() or np.any(indexes < 0)
                        or np.any(indexes != np.floor(indexes))
                        or not np.any(indexes[:, 1] > 0)
                        or np.any(indexes[:, 0] + indexes[:, 1] > len(values))):
                    raise ValueError(f"Out-of-bounds {label} indexes in {name}")
                for offset in range(0, len(values), 65536):
                    if not np.isfinite(values[offset:offset + 65536]).all():
                        raise ValueError(f"Nonfinite {label} values in {name}")
                summary[name][label] = {"entries": len(info), "values": len(values)}
    if not summary:
        raise ValueError("Prepared HDF contains no populated 2D meshes")
    if expected is not None and ({n: v["cells"] for n, v in summary.items()}
                                 != {n: v["cells"] for n, v in expected.items()}):
        raise ValueError("2D mesh names or cell counts differ from preparation")
    return summary


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8").rstrip("\x00")
    return str(value)


def _prepared_window(path):
    from .hdf.HdfUtils import HdfUtils

    with h5py.File(path, "r") as hdf:
        if "Results" in hdf:
            raise ValueError("Prepared temporary HDF contains stale /Results; preprocess again")
        info = hdf.get("Plan Data/Plan Information")
        if info is None:
            raise ValueError("Prepared HDF lacks Plan Data/Plan Information")
        times = []
        for label in ("Simulation Start Time", "Simulation End Time"):
            if label not in info.attrs:
                raise ValueError(f"Prepared HDF lacks {label}")
            times.append(HdfUtils.parse_ras_datetime(_text(info.attrs[label])))
        if times[1] <= times[0]:
            raise ValueError("Prepared simulation end must follow its start")
    return tuple(times)


def _preparation_receipt(root, project, plan, version, explicit=None):
    identity = project.relative_to(root).as_posix()
    if explicit is not None:
        candidates = [_file(_confined(explicit, root))]
    else:
        candidates = sorted((root / ".ras-commander" / "runs").glob("*/prepare.json"),
                            key=lambda p: (p.stat().st_mtime_ns, str(p)), reverse=True)
    selected = None
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if explicit is not None:
                raise ValueError("Explicit preparation receipt is unreadable or malformed")
            continue
        if not isinstance(payload, dict):
            if explicit is not None:
                raise ValueError("Explicit preparation receipt must be a JSON object")
            continue
        if explicit is None and payload.get("runtime", {}).get("hec_ras_version") != version:
            continue
        if (payload.get("project") == identity and payload.get("plan") == plan
                and payload.get("command") == "prepare" and payload.get("status") == "succeeded"):
            selected = path, payload
            break
        if explicit is not None:
            raise ValueError("Preparation receipt must be successful and match the selected project/plan")
    if selected is None:
        raise ValueError("No successful preparation receipt for this project/plan; run the Wine precompute image first")
    path, payload = selected
    if payload.get("schema") != JOB_SCHEMA:
        raise ValueError("Preparation receipt schema is not ras-commander-job/v1")
    runtime = payload.get("runtime", {})
    if runtime.get("kind") != "wine" or runtime.get("hec_ras_version") != version:
        raise ValueError("Preparation and native HEC-RAS versions do not match")
    geometry = payload.get("geometry", "")
    if not isinstance(geometry, str) or not re.fullmatch(r"\d{2}", geometry):
        raise ValueError("Preparation receipt lacks a valid geometry number")
    expected = [project.with_suffix(f".p{plan}.tmp.hdf"),
                project.with_suffix(f".b{plan}"), project.with_suffix(f".x{geometry}")]
    records = payload.get("artifacts")
    if not isinstance(records, list):
        raise ValueError("Preparation receipt lacks artifact records")
    seen = set()
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Preparation receipt contains a malformed artifact record")
        size, digest = item.get("size_bytes"), item.get("sha256")
        if (isinstance(size, bool) or not isinstance(size, int) or size <= 0
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Preparation artifacts must declare a positive byte size and SHA-256")
        artifact = _file(_confined(root / item["path"], root))
        if artifact in seen:
            raise ValueError("Preparation receipt repeats an artifact")
        seen.add(artifact)
        if size != artifact.stat().st_size:
            raise ValueError(f"Prepared artifact size changed: {artifact.name}")
        if digest != _sha256(artifact):
            raise ValueError(f"Prepared artifact changed: {artifact.name}")
    if not set(expected).issubset(seen):
        raise ValueError("Preparation receipt does not identify tmp.hdf, boundary and geometry inputs")
    for artifact in expected:
        _file(artifact)
    result = payload.get("result", {})
    if result.get("timed_out") is not False or result.get("full_result_copied") is not False:
        raise ValueError("Preparation receipt records a timeout or full-result fallback")
    return path, payload, geometry, expected


def _stage_project(source, destination):
    """Copy the job tree while omitting historical receipts and solver outputs."""
    source = source.resolve()
    excluded_outputs = re.compile(r"\.(?:p\d{2}\.hdf|bco|p\d{2}\.computeMsgs\.txt|dss\.lock)$", re.I)
    def ignore(directory, names):
        skipped = []
        for name in names:
            candidate = Path(directory) / name
            if (name in {".ras-commander", ".git", "__pycache__"}
                    or name.startswith(("io.", "compute_linux_", ".ras-commander-compute-"))
                    or excluded_outputs.search(name)):
                skipped.append(name)
            elif candidate.is_symlink():
                raise ValueError(f"Input project contains a symlink; supply ordinary files: {candidate}")
        return skipped
    shutil.copytree(source, destination, ignore=ignore)


def _initialize(project, executable):
    from .RasPrj import RasPrj, init_ras_project

    return init_ras_project(project, ras_version=str(executable), ras_object=RasPrj(),
                            load_results_summary=False, load_hdf_metadata=False, hide_intro=True)


def _validate_selected_plan(ras_object, plan, geometry, window):
    from .RasPlan import RasPlan
    from .hdf.HdfUtils import HdfUtils

    geometry_ref = str(RasPlan.get_plan_value(plan, "Geom File", ras_object=ras_object)).strip()
    if geometry_ref.lower() != "g" + geometry:
        raise ValueError("Selected plan geometry differs from the preparation receipt")
    dates = str(RasPlan.get_plan_value(plan, "Simulation Date", ras_object=ras_object)).split(",")
    if len(dates) != 4:
        raise ValueError("Selected plan lacks a readable simulation window")
    requested = tuple(HdfUtils.parse_ras_window_datetime(dates[i].strip() + " " + dates[i + 1].strip())
                      for i in (0, 2))
    if requested != window:
        raise ValueError("Plan simulation window changed after preprocessing")


def _call_compute(ras_object, engine, plan, timeout, num_cores):
    from .RasCmdr import RasCmdr

    return RasCmdr.compute_plan_linux(plan, ras_exe_dir=engine, ras_object=ras_object,
                                      timeout_sec=timeout, num_cores=num_cores, retry=False)


class _ProgressText:
    """Forward log text without retaining a complete log or an unbounded line."""

    fragment_size = 8192

    def __init__(self, stream):
        self.stream = stream
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.pending = []
        self.after_cr = False

    def _flush(self, newline=False):
        text = "".join(self.pending) + ("\n" if newline else "")
        self.pending.clear()
        if text:
            self.stream.write(text)
            self.stream.flush()

    def feed(self, data, *, final=False):
        for char in self.decoder.decode(data, final=final):
            if self.after_cr and char == "\n":
                self.after_cr = False
                continue
            self.after_cr = False
            if char in "\r\n":
                self._flush(newline=True)
                self.after_cr = char == "\r"
            else:
                self.pending.append(char)
                if len(self.pending) >= self.fragment_size:
                    # Preserve long lines, but do not wait indefinitely for their newline.
                    self._flush()
        if final:
            self._flush()


@contextmanager
def _forward_native_progress(log, *, stream=None, poll_interval=0.1):
    """Tail the current attempt's log to flushed stderr while RasCmdr is running.

    The solver owns its file and buffering. Only bytes it has already written
    are forwarded; no percentage or heartbeat is fabricated. LF, CRLF and lone
    CR delimiters become LF, including delimiters split between reads. The final
    unterminated fragment is drained before leaving this context on either a
    successful return or an exception. This never changes the retained log.
    """
    stop = threading.Event()
    output = _ProgressText(sys.stderr if stream is None else stream)

    def follow():
        source = None
        try:
            while True:
                finishing = stop.is_set()
                if source is None:
                    try:
                        source = Path(log).open("rb")
                    except FileNotFoundError:
                        pass  # RasCmdr creates the file when it launches the solver.
                if source is not None:
                    block = source.read(65536)
                    if block:
                        output.feed(block)
                        continue
                if finishing:
                    break
                stop.wait(poll_interval)
            output.feed(b"", final=True)
        except (OSError, ValueError) as exc:
            # Progress transport must not replace the solver's result or error.
            logger.warning("Native progress forwarding stopped: %s", exc)
        finally:
            if source is not None:
                source.close()

    thread = threading.Thread(target=follow, name="ras-native-progress", daemon=True)
    thread.start()
    try:
        yield thread
    finally:
        stop.set()
        thread.join()


def _validate_result(path, log, plan, meshes, window):
    from .RasCmdr import RasCmdr
    from .hdf.HdfUtils import HdfUtils

    ok, reason = RasCmdr._validate_linux_solve(log, path, plan)
    if not ok:
        raise ValueError("Native solver did not complete: " + reason)
    _mesh(path, meshes)
    validation = {"completion_verified": True, "meshes": {}}
    with h5py.File(path, "r") as hdf:
        base = hdf.get(TIME_SERIES)
        if base is None:
            raise ValueError("Result HDF lacks unsteady base-output time series")
        stamps = base.get("Time Date Stamp (ms)")
        parse_time = HdfUtils.parse_ras_datetime_ms
        if stamps is None:
            stamps = base.get("Time Date Stamp")
            parse_time = HdfUtils.parse_ras_datetime
        if stamps is None or not len(stamps):
            raise ValueError("Result HDF lacks output timestamps")
        timestamps = [parse_time(_text(value)) for value in stamps[:]]
        if any(later <= earlier for earlier, later in zip(timestamps, timestamps[1:])):
            raise ValueError("Result timestamps are not strictly increasing")
        if timestamps[0] != window[0] or timestamps[-1] != window[1]:
            raise ValueError("Result timestamps do not cover the full requested simulation window")
        for name, mesh in meshes.items():
            water = base.get("2D Flow Areas/" + name + "/Water Surface")
            if water is None or water.shape != (len(timestamps), mesh["cells"]):
                raise ValueError(f"Result water-surface dimensions are incomplete for {name}")
            for offset in range(0, len(water), 8):
                if not np.isfinite(water[offset:offset + 8]).all():
                    raise ValueError(f"Result water surfaces contain nonfinite values for {name}")
            validation["meshes"][name] = {"water_surface_shape": list(water.shape), "finite": True}
        validation.update(output_times=len(timestamps), simulation_start=timestamps[0].isoformat(),
                          simulation_end=timestamps[-1].isoformat())
    return validation


def _inspect_execution_evidence(ras_object, plan):
    """Retain the shared API's observations without substituting for native checks."""
    from .RasCmdr import RasCmdr

    try:
        return RasCmdr.inspect_execution_evidence(
            plan, ras_object=ras_object, hash_files=False,
        ).to_dict()
    except Exception as exc:
        # Diagnostic inspection must not mask a solver failure or replace the
        # native log, full-window, mesh-size and finite-value acceptance gates.
        logger.warning("Execution evidence inspection failed: %s", exc)
        return {"inspection_error": {"type": type(exc).__name__, "message": str(exc)}}


def run_compute(*, project, plan, timeout=14400, num_cores=2, run_id=None,
                replace_generated=False, prepare_receipt=None, job_root=None,
                runtime_manifest=None, scratch_root=None):
    """Run one prepared 2D plan and publish only a validated complete result."""
    plan = str(plan).zfill(2)
    if not re.fullmatch(r"\d{2}", plan):
        raise ValueError("Plan must be a two-digit plan number")
    if isinstance(timeout, bool) or int(timeout) != timeout or timeout <= 0:
        raise ValueError("Timeout must be a positive integer")
    if isinstance(num_cores, bool) or int(num_cores) != num_cores or not 1 <= num_cores <= 8:
        raise ValueError("num_cores must be an integer between 1 and 8")
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
        raise ValueError("Run ID contains unsupported characters or is too long")
    root = Path(job_root or os.environ.get("RAS_COMMANDER_JOB_ROOT", "/job")).resolve(strict=True)
    project = _file(_confined(project, root))
    if project.suffix.lower() != ".prj":
        raise ValueError("Project must identify a .prj file")
    receipt_dir = _confined(root / ".ras-commander" / "runs" / run_id, root)
    receipt_dir.mkdir(parents=True, exist_ok=False)
    receipt_path = receipt_dir / "compute.json"
    final = project.with_suffix(f".p{plan}.hdf")
    started = time.monotonic()
    payload = {"schema": JOB_SCHEMA, "command": "compute", "run_id": run_id,
               "project": project.relative_to(root).as_posix(), "plan": plan,
               "runtime": {"kind": "native", "hec_ras_version": os.environ.get("HEC_RAS_VERSION")},
               "started_at": datetime.now(timezone.utc).isoformat(),
               "arguments": {"timeout_seconds": timeout, "num_cores": num_cores,
                             "replace_generated": replace_generated, "retry": False},
               "artifacts": [], "result": {"success": False}}
    staging = None
    project_key = hashlib.sha256(project.relative_to(root).as_posix().encode()).hexdigest()[:24]
    lock_path = _confined(root / ".ras-commander" / "locks" / f"{project_key}-p{plan}.lock", root)
    lock_stream = None
    try:
        lock_stream = _acquire_job_lock(lock_path, run_id)
        if final.exists() and not replace_generated:
            raise ValueError("Final plan HDF already exists; use --replace-generated on a disposable copy")
        if final.is_symlink():
            raise ValueError("Final plan HDF must not be a symlink")
        engine, identity = _runtime(runtime_manifest or os.environ.get(
            "RAS_COMMANDER_NATIVE_RUNTIME", "/opt/hecras-runtime/runtime.json"),
            os.environ.get("HEC_RAS_VERSION"))
        payload["runtime"] = identity
        prep_path, prep, geometry, inputs = _preparation_receipt(
            root, project, plan, identity["hec_ras_version"], prepare_receipt)
        payload.update(preparation_receipt=prep_path.relative_to(root).as_posix(),
                       preparation_run_id=prep["run_id"], geometry=geometry)
        meshes = _mesh(inputs[0])
        window = _prepared_window(inputs[0])
        geometry_hdf = project.with_suffix(f".g{geometry}.hdf")
        if geometry_hdf.exists():
            _mesh(geometry_hdf, meshes)
        tracked_inputs = {*inputs, project, project.with_suffix(f".p{plan}"),
                          project.with_suffix(f".g{geometry}")}
        if geometry_hdf.exists():
            tracked_inputs.add(geometry_hdf)
        snapshots = {path: _sha256(_file(path)) for path in tracked_inputs}
        scratch = Path(scratch_root or os.environ.get("RAS_COMMANDER_COMPUTE_SCRATCH", "/tmp"))
        if scratch.resolve().is_relative_to(root):
            raise ValueError("Native compute scratch must be outside the mounted job tree")
        scratch.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="ras-compute-", dir=scratch))
        staged_root = staging / "job"
        _stage_project(root, staged_root)
        staged_project = staged_root / project.relative_to(root)
        if any(_sha256(staged_root / path.relative_to(root)) != digest
               for path, digest in snapshots.items()):
            raise ValueError("Prepared model changed while copying inputs to native scratch")
        ras_object = _initialize(staged_project, engine / "RasUnsteady")
        _validate_selected_plan(ras_object, plan, geometry, window)
        log = staged_project.parent / f"compute_linux_{plan}.log"
        with _forward_native_progress(log):
            result = _call_compute(ras_object, engine, plan, timeout, num_cores)
        payload["execution_evidence"] = _inspect_execution_evidence(ras_object, plan)
        staged_final = staged_project.with_suffix(f".p{plan}.hdf")
        if not result:
            raise RuntimeError("RasCmdr.compute_plan_linux reported failure; inspect compute_linux log")
        _file(staged_final)
        validation = _validate_result(staged_final, log, plan, meshes, window)
        # Detect changed handoff inputs before publishing a result from the copied model.
        _preparation_receipt(root, project, plan, identity["hec_ras_version"], prep_path)
        if any(_sha256(_file(path)) != digest for path, digest in snapshots.items()):
            raise ValueError("Prepared model changed during native compute; output was not published")
        if final.exists():
            if not replace_generated:
                raise ValueError("A final result appeared while compute was running")
            preserved = receipt_dir / "replaced"
            preserved.mkdir()
            _atomic_copy(final, preserved / final.name)
            payload["replaced_artifact"] = _artifact(preserved / final.name, root)
        _atomic_copy(log, project.parent / log.name)
        _atomic_copy(staged_final, final)
        payload.update(status="succeeded", artifacts=[_artifact(final, root)],
                       result={"success": True, "completion_verified": True,
                               "geometry_preprocessing_invoked": False,
                               "prepared_inputs_preserved": True, "hdf_validation": validation})
    except Exception as exc:
        logger.error("Native container compute failed: %s", exc)
        payload.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
    finally:
        evidence_errors = []
        if staging is not None:
            staged_project = staging / "job" / project.relative_to(root)
            for name in (f"compute_linux_{plan}.log", project.with_suffix(".bco").name):
                source = staged_project.parent / name
                if source.is_file():
                    try:
                        _atomic_copy(source, receipt_dir / source.name)
                    except OSError as exc:
                        evidence_errors.append(str(exc))
            if payload.get("status") == "failed":
                # Keep partial native output as diagnostic evidence, never at the final result path.
                for suffix in (f".p{plan}.tmp.hdf", f".p{plan}.hdf"):
                    source = staged_project.with_suffix(suffix)
                    if source.is_file():
                        try:
                            _atomic_copy(source, receipt_dir / ("failed-" + source.name))
                        except OSError as exc:
                            evidence_errors.append(str(exc))
            try:
                if not evidence_errors:
                    shutil.rmtree(staging)
            except OSError as exc:
                evidence_errors.append(str(exc))
        if lock_stream is not None:
            try:
                lock_stream.close()
            except OSError as exc:
                evidence_errors.append(str(exc))
        if evidence_errors:
            payload["evidence_warnings"] = evidence_errors
            payload["scratch_retained"] = str(staging)
        payload.update(finished_at=datetime.now(timezone.utc).isoformat(),
                       duration_seconds=time.monotonic() - started)
        _atomic_json(receipt_path, payload)
    return payload["status"] == "succeeded", receipt_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    compute = commands.add_parser("compute", help="compute one prepared 2D plan using native Linux HEC-RAS")
    compute.add_argument("--project", required=True, type=Path)
    compute.add_argument("--plan", required=True)
    compute.add_argument("--timeout", type=int, default=14400)
    compute.add_argument("--num-cores", type=int, default=2,
                         help="solver threads (1-8; default: 2)")
    compute.add_argument("--run-id")
    compute.add_argument("--replace-generated", action="store_true")
    compute.add_argument("--prepare-receipt", type=Path)
    args = vars(parser.parse_args(argv))
    args.pop("command")
    try:
        success, receipt = run_compute(**args)
        print(json.dumps({"receipt": str(receipt), "success": success}))
        return 0 if success else 1
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
