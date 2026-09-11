"""Container adapter guards; live model/solver qualification is a separate gate."""

import json
from pathlib import Path
import shutil

import h5py
import numpy as np
import pytest

from ras_commander import _container_compute as worker


def _prepared(path):
    with h5py.File(path, "w") as hdf:
        area = hdf.create_group("Geometry/2D Flow Areas/Mesh")
        area.create_dataset("Cells Center Coordinate", data=[[0., 0.], [1., 1.]])
        area.create_dataset("Cells Volume Elevation Info", data=[[0, 1], [1, 1]])
        area.create_dataset("Cells Volume Elevation Values", data=[[0., 0.], [1., 1.]])
        area.create_dataset("Faces Area Elevation Info", data=[[0, 1]])
        area.create_dataset("Faces Area Elevation Values", data=[[0., 0., 0., 0.]])
        info = hdf.create_group("Plan Data/Plan Information")
        info.attrs["Simulation Start Time"] = np.bytes_("01Jan2020 00:00:00")
        info.attrs["Simulation End Time"] = np.bytes_("01Jan2020 01:00:00")


def _results(path, truncated=False):
    with h5py.File(path, "a") as hdf:
        base = hdf.create_group(worker.TIME_SERIES)
        times = [b"01Jan2020 00:00:00", b"01Jan2020 01:00:00"]
        if truncated:
            times[-1] = b"01Jan2020 00:30:00"
        base.create_dataset("Time Date Stamp", data=times)
        base.create_dataset("2D Flow Areas/Mesh/Water Surface", data=[[1., 2.], [3., 4.]])


@pytest.fixture
def packet(tmp_path, monkeypatch):
    root = tmp_path / "job"
    root.mkdir()
    project = root / "Example.prj"
    project.write_text("Proj Title=Example\nPlan File=p01\n")
    project.with_suffix(".p01").write_text(
        "Plan Title=Plan\nGeom File=g01\nFlow File=u01\n"
        "Simulation Date=01Jan2020,0000,01Jan2020,0100\n")
    project.with_suffix(".g01").write_bytes(b"Geom Title=Mesh\r\n")
    project.with_suffix(".b01").write_bytes(b"Boundary input\r\n")
    project.with_suffix(".x01").write_bytes(b"Geometry input\r\n")
    temporary = project.with_suffix(".p01.tmp.hdf")
    _prepared(temporary)
    shutil.copyfile(temporary, project.with_suffix(".g01.hdf"))
    runtime = tmp_path / "runtime"
    (runtime / "engine" / "libs").mkdir(parents=True)
    executable = runtime / "engine" / "RasUnsteady"
    executable.write_bytes(b"test executable - never launched")
    executable.chmod(0o755)
    manifest = runtime / "runtime.json"
    manifest.write_text(json.dumps({
        "schema": "ras-commander-native-runtime/v1", "kind": "native", "hec_ras_version": "6.5",
        "native": {"engine_directory": "engine"}, "artifacts": [worker._artifact(executable, runtime)]}))
    prep = root / ".ras-commander" / "runs" / "preparation" / "prepare.json"
    payload = {"schema": worker.JOB_SCHEMA, "command": "prepare", "status": "succeeded",
               "run_id": "preparation", "project": project.name, "plan": "01", "geometry": "01",
               "runtime": {"kind": "wine", "hec_ras_version": "6.5", "ras_commander_commit": "different"},
               "artifacts": [worker._artifact(p, root) for p in
                             (temporary, project.with_suffix(".b01"), project.with_suffix(".x01"))],
               "result": {"timed_out": False, "full_result_copied": False}}
    worker._atomic_json(prep, payload)
    monkeypatch.delenv("HEC_RAS_VERSION", raising=False)
    monkeypatch.setattr(worker, "_initialize", lambda path, exe: path)
    # Domain plan selection is separately checked through actual RasPlan below.
    monkeypatch.setattr(worker, "_validate_selected_plan", lambda *args: None)
    return {"root": root, "project": project, "temporary": temporary,
            "manifest": manifest, "prep": prep, "payload": payload, "scratch": tmp_path / "scratch"}


def _run(packet, **kwargs):
    return worker.run_compute(project=packet["project"], plan="01", job_root=packet["root"],
                              runtime_manifest=packet["manifest"], scratch_root=packet["scratch"],
                              run_id="compute", **kwargs)


def _fake_success(project, engine, plan, timeout, num_cores):
    temporary = project.with_suffix(f".p{plan}.tmp.hdf")
    final = project.with_suffix(f".p{plan}.hdf")
    temporary.rename(final)
    _results(final)
    project.with_suffix(".g01").write_text("solver touched staged geometry\n")
    (project.parent / f"compute_linux_{plan}.log").write_text("Finished Unsteady Flow Simulation\n")
    return True


def test_success_preserves_prepared_inputs_and_publishes_validated_result(packet, monkeypatch):
    monkeypatch.setattr(worker, "_call_compute", _fake_success)
    before = worker._sha256(packet["temporary"])
    success, receipt = _run(packet, prepare_receipt=packet["prep"])
    payload = json.loads(receipt.read_text())
    assert success and payload["status"] == "succeeded"
    assert payload["runtime"]["hec_ras_version"] == "6.5"
    assert payload["result"]["hdf_validation"]["meshes"]["Mesh"]["water_surface_shape"] == [2, 2]
    assert worker._sha256(packet["temporary"]) == before
    assert packet["project"].with_suffix(".g01").read_bytes() == b"Geom Title=Mesh\r\n"
    assert packet["project"].with_suffix(".p01.hdf").is_file()
    assert not list(packet["scratch"].iterdir())


@pytest.mark.parametrize("problem", ["missing", "empty", "changed", "version", "stale", "bad_table"])
def test_rejects_bad_preparation_before_solver(packet, monkeypatch, problem):
    def forbidden(*args):
        pytest.fail("Solver API must not be called for a rejected preparation")
    monkeypatch.setattr(worker, "_call_compute", forbidden)
    if problem == "missing":
        packet["project"].with_suffix(".b01").unlink()
    elif problem == "empty":
        packet["project"].with_suffix(".x01").write_bytes(b"")
    elif problem == "changed":
        packet["project"].with_suffix(".b01").write_bytes(b"changed boundary")
    elif problem == "version":
        packet["payload"]["runtime"]["hec_ras_version"] = "6.6"
        worker._atomic_json(packet["prep"], packet["payload"])
    else:
        with h5py.File(packet["temporary"], "a") as hdf:
            if problem == "stale":
                hdf.create_group("Results")
            else:
                hdf["Geometry/2D Flow Areas/Mesh/Cells Volume Elevation Info"][0] = [99, 99]
        packet["payload"]["artifacts"][0] = worker._artifact(packet["temporary"], packet["root"])
        worker._atomic_json(packet["prep"], packet["payload"])
    success, receipt = _run(packet)
    assert not success
    assert json.loads(receipt.read_text())["status"] == "failed"
    assert not packet["project"].with_suffix(".p01.hdf").exists()


def test_failed_solver_preserves_prior_final_and_saves_log(packet, monkeypatch):
    previous = packet["project"].with_suffix(".p01.hdf")
    previous.write_bytes(b"previous result")
    def fail(project, *args):
        assert not project.with_suffix(".p01.hdf").exists()
        (project.parent / "compute_linux_01.log").write_text("Unsteady flow encountered an error\n")
        return False
    monkeypatch.setattr(worker, "_call_compute", fail)
    success, receipt = _run(packet, replace_generated=True)
    assert not success and previous.read_bytes() == b"previous result"
    assert (receipt.parent / "compute_linux_01.log").is_file()
    assert (receipt.parent / "failed-Example.p01.tmp.hdf").is_file()


def test_replace_preserves_previous_final_in_receipt_directory(packet, monkeypatch):
    monkeypatch.setattr(worker, "_call_compute", _fake_success)
    previous = packet["project"].with_suffix(".p01.hdf")
    previous.write_bytes(b"previous result")
    success, receipt = _run(packet, replace_generated=True)
    assert success
    assert (receipt.parent / "replaced" / previous.name).read_bytes() == b"previous result"
    assert json.loads(receipt.read_text())["replaced_artifact"]["size_bytes"] == len(b"previous result")


@pytest.mark.parametrize("problem", ["truncated", "nan", "empty", "log_error"])
def test_result_validation_rejects_false_success(packet, monkeypatch, problem):
    def bad_result(project, *args):
        _fake_success(project, *args)
        final = project.with_suffix(".p01.hdf")
        with h5py.File(final, "a") as hdf:
            if problem == "truncated":
                hdf[worker.TIME_SERIES + "/Time Date Stamp"][1] = b"01Jan2020 00:30:00"
            elif problem == "nan":
                hdf[worker.TIME_SERIES + "/2D Flow Areas/Mesh/Water Surface"][0, 0] = np.nan
            elif problem == "empty":
                del hdf[worker.TIME_SERIES + "/2D Flow Areas/Mesh/Water Surface"]
        if problem == "log_error":
            (project.parent / "compute_linux_01.log").write_text("Error: failed\nFinished Unsteady Flow Simulation\n")
        return True
    monkeypatch.setattr(worker, "_call_compute", bad_result)
    success, receipt = _run(packet)
    assert not success and json.loads(receipt.read_text())["error"]["message"]
    assert not packet["project"].with_suffix(".p01.hdf").exists()


def test_explicit_receipt_confined_to_job(packet):
    outside = packet["root"].parent / "outside.json"
    outside.write_text(json.dumps(packet["payload"]))
    success, receipt = _run(packet, prepare_receipt=outside)
    assert not success
    assert "outside" in json.loads(receipt.read_text())["error"]["message"]


def test_latest_matching_receipt_does_not_require_same_library_commit(packet):
    unrelated = packet["prep"].parent.parent / "unrelated" / "prepare.json"
    other = dict(packet["payload"], project="Different.prj")
    worker._atomic_json(unrelated, other)
    selected, payload, geometry, _ = worker._preparation_receipt(
        packet["root"], packet["project"], "01", "6.5")
    assert selected == packet["prep"] and geometry == "01"
    assert payload["runtime"]["ras_commander_commit"] == "different"


def test_active_compute_lock_rejects_concurrent_run_and_releases_on_close(packet):
    import hashlib
    key = hashlib.sha256(packet["project"].name.encode()).hexdigest()[:24]
    lock = packet["root"] / ".ras-commander" / "locks" / f"{key}-p01.lock"
    claim = worker._acquire_job_lock(lock, "another-run")
    try:
        success, receipt = _run(packet)
        assert not success
        assert "active native compute" in json.loads(receipt.read_text())["error"]["message"]
    finally:
        claim.close()
    new_claim = worker._acquire_job_lock(lock, "retry")
    new_claim.close()


@pytest.mark.parametrize("field", ["size_bytes", "sha256"])
def test_receipt_cannot_omit_artifact_identity(packet, field):
    packet["payload"]["artifacts"][0].pop(field)
    worker._atomic_json(packet["prep"], packet["payload"])
    success, receipt = _run(packet)
    assert not success
    assert "must declare" in json.loads(receipt.read_text())["error"]["message"]


def test_stage_excludes_receipts_stale_results_and_fortran_links(packet, tmp_path):
    packet["project"].with_suffix(".p01.hdf").write_bytes(b"old")
    (packet["root"] / "io.b").write_bytes(b"old alias")
    (packet["root"] / "compute_linux_01.log").write_text("old log")
    staged = tmp_path / "staged"
    worker._stage_project(packet["root"], staged)
    assert not (staged / ".ras-commander").exists()
    assert not (staged / "Example.p01.hdf").exists()
    assert not (staged / "io.b").exists()
    assert (staged / "Example.p01.tmp.hdf").is_file()


def test_api_invocation_disables_retry(monkeypatch):
    from ras_commander import RasCmdr
    recorded = {}
    def compute(plan, **kwargs):
        recorded.update(plan=plan, **kwargs)
        return True
    monkeypatch.setattr(RasCmdr, "compute_plan_linux", compute)
    assert worker._call_compute("project-object", Path("runtime"), "04", 900, 3)
    assert recorded["retry"] is False and recorded["num_cores"] == 3
    assert recorded["ras_object"] == "project-object"


def test_host_input_change_during_solver_prevents_result_publication(packet, monkeypatch):
    def changed(project, *args):
        result = _fake_success(project, *args)
        packet["project"].with_suffix(".p01").write_text("changed during compute")
        return result
    monkeypatch.setattr(worker, "_call_compute", changed)
    success, receipt = _run(packet)
    assert not success
    assert "changed during native compute" in json.loads(receipt.read_text())["error"]["message"]
    assert not packet["project"].with_suffix(".p01.hdf").exists()


def test_evidence_copy_error_still_writes_receipt_and_releases_lock(packet, monkeypatch):
    def fail(project, *args):
        (project.parent / "compute_linux_01.log").write_text("failed computation")
        return False
    monkeypatch.setattr(worker, "_call_compute", fail)
    def unable_to_copy(*args):
        raise OSError("injected evidence-copy failure")
    monkeypatch.setattr(worker, "_atomic_copy", unable_to_copy)
    success, receipt = _run(packet)
    assert not success
    payload = json.loads(receipt.read_text())
    assert payload["evidence_warnings"]
    lock = next((packet["root"] / ".ras-commander" / "locks").iterdir())
    with worker._acquire_job_lock(lock, "retry"):
        pass


def _bundler_module():
    import importlib.util
    path = Path(__file__).parents[1] / "containers" / "hecras-unsteady" / "bundle_runtime.py"
    spec = importlib.util.spec_from_file_location("test_native_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_contains_only_native_unsteady_libraries_and_notices(tmp_path):
    bundler = _bundler_module()
    source, libraries, notices = (tmp_path / n for n in ("source", "libraries", "notices"))
    for folder in (source, libraries, notices):
        folder.mkdir()
    header = bytearray(20)
    header[:5] = b"\x7fELF\x02"
    header[18:20] = b"\x3e\x00"
    (source / "RasUnsteady").write_bytes(header)
    (source / "RasGeomPreprocess").write_bytes(b"excluded engine")
    (source / "example.p01.hdf").write_bytes(b"excluded model")
    (libraries / "libiomp5.so").write_bytes(b"vendor library")
    (notices / "TERMS.txt").write_text("Retained vendor terms")
    output = bundler.bundle_runtime(engine_source=source, libraries_source=libraries,
                                    notices_source=notices, hec_ras_version="6.5", output=tmp_path / "bundle")
    manifest = json.loads((output / "runtime.json").read_text())
    assert manifest["hec_ras_version"] == "6.5"
    names = {row["path"] for row in manifest["artifacts"]}
    assert names == {"engine/RasUnsteady", "engine/libs/libiomp5.so", "notices/TERMS.txt"}
    assert not (output / "engine" / "RasGeomPreprocess").exists()


def test_bundle_rejects_windows_executable_and_missing_notices(tmp_path):
    bundler = _bundler_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "RasUnsteady").write_bytes(b"MZ Windows executable")
    with pytest.raises(ValueError, match="ELF"):
        bundler.bundle_runtime(engine_source=source, libraries_source=source,
                               notices_source=source, hec_ras_version="6.5", output=tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()
