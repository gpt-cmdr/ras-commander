"""Real-file cache/transport tests; these do not validate HEC-RAS hydraulics."""

import copy
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from ras_commander._container_resume import find_resume, record_resume


module = importlib.import_module("ras_commander._container_resume")


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _artifact(root, path):
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def _receipt(project, stage="prepare", run_id="prepare-one", **changes):
    root = project.parent
    if stage == "prepare":
        suffixes = (".p01.tmp.hdf", ".b01", ".x03")
        result = {"timed_out": False, "full_result_copied": False}
    else:
        suffixes = (".p01.hdf",)
        result = {"success": True, "completion_verified": True}
    artifacts = []
    for suffix in suffixes:
        path = project.with_suffix(suffix)
        if not path.exists():
            path.write_bytes(("Generated transport fixture " + suffix).encode())
        artifacts.append(_artifact(root, path))
    payload = {"schema": "ras-commander-job/v1", "run_id": run_id,
               "command": stage, "project": project.name, "plan": "01",
               "geometry": "03", "status": "succeeded", "result": result,
               "arguments": {"num_cores": 2},
               "runtime": {"kind": "wine" if stage == "prepare" else "native",
                           "hec_ras_version": "7.0.1"},
               "artifacts": artifacts}
    if stage == "compute":
        payload["preparation_receipt"] = ".ras-commander/runs/prepare-one/prepare.json"
    payload.update(changes)
    path = root / ".ras-commander" / "runs" / run_id / f"{stage}.json"
    _write_json(path, payload)
    return path


@pytest.fixture
def run(tmp_path):
    root = tmp_path / "model with spaces"
    root.mkdir()
    project = root / "Example Model.prj"
    project.write_bytes(b"Proj Title=Cache fixture\r\n")
    project.with_suffix(".p01").write_bytes(b"Geom File=g03\r\n")
    project.with_suffix(".g03").write_bytes(b"Geom Title=Fixture\r\n")
    (root / "inputs").mkdir()
    (root / "inputs" / "inflow.dat").write_bytes(b"Boundary data")
    terrain = tmp_path / "external terrain"
    terrain.mkdir()
    (terrain / "terrain.tif").write_bytes(b"Terrain fixture")
    projection = tmp_path / "projection.prj"
    projection.write_bytes(b"Projection fixture")
    identity = {"version": "7.0.1", "image": "rascommander/hec-ras-wine-precompute_7.0.1:v4",
                "num_cores": 2, "mounts": {"/terrain": str(terrain),
                                            "/projection/file.prj": str(projection)}}
    receipt = _receipt(project)
    return project, identity, receipt


def _record(run, stage="prepare"):
    project, identity, receipt = run
    record_resume(project, "01", stage, identity, receipt)
    return next((project.parent / ".ras-commander" / "resume").glob("*.json"))


def _compute(run):
    project, identity, preparation = run
    identity = {**identity, "image": "rascommander/hec-ras-linux-unsteady_7.0.1:v1",
                "prepare_receipt": str(preparation)}
    receipt = _receipt(project, "compute", "compute-one")
    return project, identity, receipt


def test_successful_receipt_without_new_host_record_is_not_reused(run):
    project, identity, _ = run
    assert find_resume(project, "01", "prepare", identity) is None
    assert not (project.parent / ".ras-commander" / "resume").exists()


@pytest.mark.parametrize("stage", ["prepare", "compute"])
def test_unchanged_success_resumes_original_receipt(run, stage):
    if stage == "compute":
        run = _compute(run)
    project, identity, receipt = run
    original = receipt.read_bytes()
    _record(run, stage)
    result = find_resume(project, "01", stage, identity)
    assert result == {"receipt_path": str(receipt), "receipt": json.loads(original)}
    assert receipt.read_bytes() == original


@pytest.mark.parametrize("stage", ["prepare", "compute"])
@pytest.mark.parametrize("cores", [None, 4, True, 2.0, "2"])
def test_receipt_must_confirm_exact_solver_core_count(run, stage, cores):
    if stage == "compute":
        run = _compute(run)
    project, identity, receipt = run
    payload = json.loads(receipt.read_text())
    payload["arguments"] = {} if cores is None else {"num_cores": cores}
    _write_json(receipt, payload)
    before = receipt.read_bytes()
    record_resume(project, "01", stage, identity, receipt)
    assert find_resume(project, "01", stage, identity) is None
    assert receipt.read_bytes() == before
    assert not (project.parent / ".ras-commander" / "resume").exists()


@pytest.mark.parametrize("change", ["project", "plan", "input", "added", "removed", "directory",
                                    "terrain", "projection", "mount-added", "tmp", "boundary"])
def test_input_and_dependency_changes_invalidate_resume(run, change):
    project, identity, _ = run
    record = _record(run)
    original_record = record.read_bytes()
    root = project.parent
    targets = {"project": project, "plan": project.with_suffix(".p01"),
               "input": root / "inputs" / "inflow.dat",
               "terrain": Path(identity["mounts"]["/terrain"]) / "terrain.tif",
               "projection": Path(identity["mounts"]["/projection/file.prj"]),
               "tmp": project.with_suffix(".p01.tmp.hdf"),
               "boundary": project.with_suffix(".b01")}
    if change in targets:
        targets[change].write_bytes(b"Changed bytes")
    elif change == "added":
        (root / "new-input.dat").write_bytes(b"new")
    elif change == "removed":
        (root / "inputs" / "inflow.dat").unlink()
    elif change == "directory":
        (root / "new-input-directory").mkdir()
    elif change == "mount-added":
        (Path(identity["mounts"]["/terrain"]) / "additional.tif").write_bytes(b"new")
    assert find_resume(project, "01", "prepare", identity) is None
    assert record.read_bytes() == original_record


def test_same_size_dependency_change_still_invalidates(run):
    project, identity, _ = run
    _record(run)
    path = Path(identity["mounts"]["/terrain"]) / "terrain.tif"
    path.write_bytes(b"x" * path.stat().st_size)
    assert find_resume(project, "01", "prepare", identity) is None


def test_new_receipts_logs_and_final_results_do_not_invalidate_preparation(run):
    project, identity, _ = run
    _record(run)
    _receipt(project, "compute", "compute-one")
    project.with_suffix(".bco01").write_bytes(b"New solver messages")
    project.with_suffix(".p01.computeMsgs.txt").write_bytes(b"New messages")
    (project.parent / "compute_linux_01.log").write_bytes(b"New log")
    (project.parent / ".ras-commander" / "runs" / "unrelated").mkdir()
    assert find_resume(project, "01", "prepare", identity)


@pytest.mark.parametrize("change", ["changed", "missing"])
def test_compute_result_artifact_changes_are_not_ignored(run, change):
    run = _compute(run)
    project, identity, _ = run
    _record(run, "compute")
    result = project.with_suffix(".p01.hdf")
    if change == "changed":
        result.write_bytes(b"Corrupted result")
    else:
        result.unlink()
    assert find_resume(project, "01", "compute", identity) is None


@pytest.mark.parametrize("key,value", [("version", "6.6"), ("num_cores", 4),
                                       ("image", "different-image:tag"),
                                       ("user", "another-user")])
def test_invocation_identity_changes_invalidate(run, key, value):
    project, identity, _ = run
    _record(run)
    assert find_resume(project, "01", "prepare", {**identity, key: value}) is None
    assert find_resume(project, "02", "prepare", identity) is None


@pytest.mark.parametrize("change", ["failed", "wrong-version", "wrong-plan", "wrong-kind",
                                    "wrong-project", "wrong-stage", "wrong-schema", "wrong-run",
                                    "no-artifacts", "bad-hash", "fallback", "timeout"])
def test_invalid_receipt_is_never_recorded(run, change):
    project, identity, receipt = run
    payload = json.loads(receipt.read_text())
    edits = {"failed": ("status", "failed"), "wrong-plan": ("plan", "02"),
             "wrong-project": ("project", "other.prj"), "wrong-stage": ("command", "compute"),
             "wrong-schema": ("schema", "unknown"), "wrong-run": ("run_id", "other"),
             "no-artifacts": ("artifacts", [])}
    if change in edits:
        key, value = edits[change]
        payload[key] = value
    elif change == "wrong-version":
        payload["runtime"]["hec_ras_version"] = "6.6"
    elif change == "wrong-kind":
        payload["runtime"]["kind"] = "native"
    elif change == "bad-hash":
        payload["artifacts"][0]["sha256"] = "0" * 64
    elif change == "fallback":
        payload["result"]["full_result_copied"] = True
    elif change == "timeout":
        payload["result"]["timed_out"] = True
    _write_json(receipt, payload)
    record_resume(project, "01", "prepare", identity, receipt)
    assert find_resume(project, "01", "prepare", identity) is None
    assert not list((project.parent / ".ras-commander" / "resume").glob("*.json"))


@pytest.mark.parametrize("contents", ["not json", "[]", "null", '{"schema":"other"}'])
def test_malformed_record_is_cache_miss(run, contents):
    project, identity, _ = run
    record = _record(run)
    record.write_text(contents)
    assert find_resume(project, "01", "prepare", identity) is None
    assert record.read_text() == contents


@pytest.mark.parametrize("location", ["record", "receipt"])
def test_receipt_path_traversal_is_rejected(run, location):
    project, identity, receipt = run
    record = _record(run)
    if location == "record":
        payload = json.loads(record.read_text())
        payload["receipt_path"] = "../external.json"
        _write_json(record, payload)
    else:
        payload = json.loads(receipt.read_text())
        payload["artifacts"][0]["path"] = "../external.hdf"
        _write_json(receipt, payload)
    assert find_resume(project, "01", "prepare", identity) is None


def test_changed_original_receipt_invalidates_even_if_successful(run):
    project, identity, receipt = run
    _record(run)
    payload = json.loads(receipt.read_text())
    payload["result"]["extra-evidence"] = "changed"
    _write_json(receipt, payload)
    assert find_resume(project, "01", "prepare", identity) is None


def test_compute_checks_linked_preparation_and_explicit_selection(run):
    preparation = run[2]
    run = _compute(run)
    project, identity, receipt = run
    _record(run, "compute")
    assert find_resume(project, "01", "compute", identity)
    preparation.write_text("{}")
    assert find_resume(project, "01", "compute", identity) is None
    assert find_resume(project, "01", "compute", {**identity, "prepare_receipt": str(receipt)}) is None


def _symlink(link, target, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"Symbolic links unavailable on this test host: {exc}")


@pytest.mark.parametrize("location", ["input", "mount", "receipt", "record", "cache-directory"])
def test_symlinks_are_ineligible(run, tmp_path, location):
    project, identity, receipt = run
    record = _record(run)
    outside = tmp_path / "outside"
    if location == "input":
        outside.write_bytes(b"external data")
        _symlink(project.parent / "linked.dat", outside)
    elif location == "mount":
        mount = Path(identity["mounts"]["/terrain"])
        mount.rename(outside)
        _symlink(mount, outside, directory=True)
    elif location in {"receipt", "record"}:
        selected = receipt if location == "receipt" else record
        selected.rename(outside)
        _symlink(selected, outside)
    else:
        directory = record.parent
        directory.rename(outside)
        _symlink(directory, outside, directory=True)
    assert find_resume(project, "01", "prepare", identity) is None


def test_unreadable_input_is_cache_miss(run, monkeypatch):
    project, identity, _ = run
    _record(run)
    blocked = project.with_suffix(".p01")
    original = Path.open
    def open_file(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("Unreadable fixture")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_file)
    assert find_resume(project, "01", "prepare", identity) is None


def test_atomic_replace_failure_preserves_existing_record(run, monkeypatch):
    project, identity, receipt = run
    record = _record(run)
    prior = record.read_bytes()
    def fail_replace(*_):
        raise OSError("Atomic replacement unavailable")
    monkeypatch.setattr(module.os, "replace", fail_replace)
    record_resume(project, "01", "prepare", identity, receipt)
    assert record.read_bytes() == prior
    assert not list(record.parent.glob(".resume-*.tmp"))


def test_receipt_and_artifacts_remain_byte_identical_when_recording(run):
    project, identity, receipt = run
    originals = {path: path.read_bytes() for path in project.parent.rglob("*") if path.is_file()}
    record_resume(project, "01", "prepare", identity, receipt)
    assert all(path.read_bytes() == data for path, data in originals.items())


def test_identity_is_not_mutated_and_key_order_does_not_matter(run):
    project, identity, _ = run
    before = copy.deepcopy(identity)
    _record(run)
    reordered = dict(reversed(list(identity.items())))
    assert find_resume(project, "01", "prepare", reordered)
    assert identity == before
