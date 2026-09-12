"""Conservative host-side reuse of successful container runs.

Only records written by ``record_resume`` are eligible. Every lookup hashes the
model input tree, all dependency mounts, the original receipts, and their output
artifacts. This can be expensive for large terrain files. This is a transport
and cache check, not a new hydraulic validation or a trust boundary against a
caller who can deliberately rewrite both model files and cache records.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

from .LoggingConfig import get_logger


logger = get_logger(__name__)
_SCHEMA = "ras-commander-container-resume/v1"
_JOB_SCHEMA = "ras-commander-job/v1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_OUTPUT = re.compile(
    r"(?:\.p\d{2}\.hdf|\.bco\d*|\.p\d{2}\.(?:computeMsgs|comp_msgs)\.txt"
    r"|\.(?:log|stdout|stderr)|\.dss\.lock)$", re.IGNORECASE,
)
_IGNORED_DIRECTORIES = {".ras-commander", ".git", "__pycache__"}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _confined(path, root):
    """Reject traversal and links, including existing parent links."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("Path traversal is not eligible for resume")
    if not path.is_absolute():
        path = root / path
    relative = path.relative_to(root)
    current = root
    if _linked(current):
        raise ValueError("Linked project root is not eligible for resume")
    for part in relative.parts:
        current = current / part
        if _linked(current):
            raise ValueError("Linked paths are not eligible for resume")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Resume path escapes the project")
    return path


def _relative_file(value, root):
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise ValueError("Receipt paths must be relative POSIX paths")
    relative = PurePosixPath(value)
    if (relative.is_absolute() or ".." in relative.parts or not relative.parts
            or relative.as_posix() != value):
        raise ValueError("Invalid relative receipt path")
    return _confined(Path(*relative.parts), root)


def _file_state(path):
    if _linked(path) or not path.is_file():
        raise ValueError("Resume inputs must be ordinary files")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if ((before.st_size, before.st_mtime_ns, before.st_ino)
            != (after.st_size, after.st_mtime_ns, after.st_ino)):
        raise ValueError("File changed while checking resume evidence")
    return {"size_bytes": after.st_size, "sha256": digest.hexdigest()}


def _context(project, plan, stage, identity):
    project = Path(project).absolute()
    root = project.parent
    _confined(project, root)
    if not project.is_file() or project.suffix.lower() != ".prj":
        raise ValueError("Resume requires an existing project file")
    if stage not in {"prepare", "compute"} or not re.fullmatch(r"\d{2}", plan):
        raise ValueError("Invalid resume stage or plan")
    # Round-trip both rejects non-JSON inputs and detaches mutable caller data.
    identity = json.loads(_json(identity))
    if (not isinstance(identity, dict) or not isinstance(identity.get("version"), str)
            or not identity["version"] or not isinstance(identity.get("image"), str)
            or not identity["image"]):
        raise ValueError("Resume identity requires version and image")
    cores = identity.get("num_cores")
    if isinstance(cores, bool) or not isinstance(cores, int) or not 1 <= cores <= 8:
        raise ValueError("Resume identity requires num_cores in 1..8")
    mounts = identity.get("mounts", {})
    if not isinstance(mounts, dict):
        raise ValueError("Resume mounts must be a normalized mapping")
    for destination, source in mounts.items():
        target = PurePosixPath(destination)
        if (not target.is_absolute() or target.as_posix() != destination
                or ".." in target.parts or "\\" in destination
                or not isinstance(source, str) or not Path(source).is_absolute()):
            raise ValueError("Resume mounts must use absolute normalized paths")
    key = hashlib.sha256(_json({"project": project.name, "plan": plan,
                               "stage": stage, "identity": identity}).encode()).hexdigest()
    record = _confined(root / ".ras-commander" / "resume" / f"{stage}-{plan}-{key}.json", root)
    return project, root, identity, record


def _inventory(path, *, model=False):
    """Hash an ordinary file or complete tree without following links."""
    path = Path(path)
    if _linked(path):
        raise ValueError("Linked dependency mount is not eligible for resume")
    if path.is_file():
        return [{"path": ".", "kind": "file", **_file_state(path)}]
    if not path.is_dir():
        raise ValueError("Resume input directory is missing")
    inventory = []

    def walk(directory):
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            # Reject links even when their names look like disposable outputs.
            if _linked(child):
                raise ValueError("Linked model or dependency file is not eligible for resume")
            relative = child.relative_to(path).as_posix()
            if model and child.is_dir() and child.name in _IGNORED_DIRECTORIES:
                continue
            if model and child.is_file() and _OUTPUT.search(child.name):
                continue
            if child.is_dir():
                inventory.append({"path": relative, "kind": "directory"})
                walk(child)
            else:
                inventory.append({"path": relative, "kind": "file", **_file_state(child)})

    walk(path)
    return inventory


def _inputs(root, identity):
    return {"project": _inventory(root, model=True),
            "mounts": {destination: _inventory(Path(source))
                       for destination, source in sorted(identity.get("mounts", {}).items())}}


def _receipt(project, plan, stage, version, path):
    root = project.parent
    path = _confined(path, root)
    relative = path.relative_to(root)
    if (len(relative.parts) != 4 or relative.parts[:2] != (".ras-commander", "runs")
            or relative.name != f"{stage}.json"):
        raise ValueError("Resume receipt must be in the selected project's run directory")
    receipt_state = _file_state(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or payload.get("schema") != _JOB_SCHEMA
            or payload.get("command") != stage or payload.get("project") != project.name
            or payload.get("plan") != plan or payload.get("status") != "succeeded"
            or payload.get("run_id") != relative.parent.name):
        raise ValueError("Resume receipt is not successful or does not match the job")
    runtime = payload.get("runtime", {})
    if (not isinstance(runtime, dict) or runtime.get("hec_ras_version") != version
            or runtime.get("kind") != ("wine" if stage == "prepare" else "native")):
        raise ValueError("Resume receipt runtime does not match")
    result = payload.get("result", {})
    if not isinstance(result, dict):
        raise ValueError("Resume receipt has no successful result")
    if stage == "prepare":
        if result.get("timed_out") is not False or result.get("full_result_copied") is not False:
            raise ValueError("Preparation receipt has incomplete or fallback output")
        geometry = payload.get("geometry")
        if not isinstance(geometry, str) or not re.fullmatch(r"\d{2}", geometry):
            raise ValueError("Preparation receipt lacks a geometry number")
        expected = {project.with_suffix(suffix).name for suffix in
                    (f".p{plan}.tmp.hdf", f".b{plan}", f".x{geometry}")}
    else:
        if result.get("success") is not True or result.get("completion_verified") is not True:
            raise ValueError("Compute receipt has not verified completion")
        expected = {project.with_suffix(f".p{plan}.hdf").name}
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Resume receipt has no artifact inventory")
    seen, checked = set(), []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("Malformed artifact record")
        target = _relative_file(artifact.get("path"), root)
        name = target.relative_to(root).as_posix()
        size, digest = artifact.get("size_bytes"), artifact.get("sha256")
        if (name in seen or isinstance(size, bool) or not isinstance(size, int) or size <= 0
                or not isinstance(digest, str) or not _HASH.fullmatch(digest)):
            raise ValueError("Malformed artifact identity")
        state = _file_state(target)
        if state != {"size_bytes": size, "sha256": digest}:
            raise ValueError("Output artifact no longer matches its receipt")
        checked.append({"path": name, **state})
        seen.add(name)
    if not expected.issubset(seen) or _file_state(path) != receipt_state:
        raise ValueError("Missing expected output or concurrently changed receipt")
    return payload, {"path": relative.as_posix(), **receipt_state,
                     "artifacts": sorted(checked, key=lambda item: item["path"])}


def _evidence(project, plan, stage, identity, path):
    payload, receipt = _receipt(project, plan, stage, identity["version"], path)
    arguments = payload.get("arguments")
    if (not isinstance(arguments, dict)
            or type(arguments.get("num_cores")) is not int
            or arguments["num_cores"] != identity["num_cores"]):
        raise ValueError("Resume receipt does not confirm the requested solver core count")
    evidence = {"receipt": receipt}
    if stage == "compute":
        preparation = _relative_file(payload.get("preparation_receipt"), project.parent)
        explicit = identity.get("prepare_receipt")
        if explicit is not None and _confined(explicit, project.parent) != preparation:
            raise ValueError("Compute receipt refers to a different preparation")
        _, evidence["preparation"] = _receipt(
            project, plan, "prepare", identity["version"], preparation)
    return payload, evidence


def find_resume(project: Path, plan: str, stage: str, identity: dict):
    """Return an unchanged successful receipt recorded by this API, or None.

    Missing, stale, malformed, linked, or unreadable evidence is a cache miss.
    A cache miss never removes old records or changes model files.
    """
    try:
        project, root, identity, record_path = _context(project, plan, stage, identity)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("schema") != _SCHEMA
                or record.get("project") != project.name or record.get("plan") != plan
                or record.get("stage") != stage or record.get("identity") != identity):
            raise ValueError("Resume record identity does not match")
        path = _relative_file(record.get("receipt_path"), root)
        payload, before = _evidence(project, plan, stage, identity, path)
        if before != record.get("evidence") or _inputs(root, identity) != record.get("inputs"):
            raise ValueError("Resume inputs or outputs changed")
        _, after = _evidence(project, plan, stage, identity, path)
        if before != after:
            raise ValueError("Resume evidence changed during lookup")
        return {"receipt_path": str(path), "receipt": payload}
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        logger.debug("Container resume cache miss: %s", exc)
        return None


def record_resume(project: Path, plan: str, stage: str, identity: dict, receipt_path: Path) -> None:
    """Best-effort atomic record after the host verified a successful run.

    Inputs are captured after success because Wine normalizes and updates them.
    Only the private resume metadata is written; original receipts and model
    files are read-only here. Failure to record simply disables later reuse.
    """
    temporary = None
    try:
        project, root, identity, record_path = _context(project, plan, stage, identity)
        _, before = _evidence(project, plan, stage, identity, receipt_path)
        inputs = _inputs(root, identity)
        _, after = _evidence(project, plan, stage, identity, receipt_path)
        if before != after:
            raise ValueError("Resume evidence changed while recording")
        record = {"schema": _SCHEMA, "project": project.name, "plan": plan,
                  "stage": stage, "identity": identity, "inputs": inputs,
                  "receipt_path": before["receipt"]["path"], "evidence": before}
        record_path.parent.mkdir(parents=True, exist_ok=True)
        _confined(record_path, root)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=record_path.parent,
                                         prefix=".resume-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(_json(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _confined(record_path, root)
        os.replace(temporary, record_path)
        temporary = None
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        logger.debug("Container resume record not saved: %s", exc)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
