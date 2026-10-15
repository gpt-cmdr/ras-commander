"""RasDocker native worker guards for pre-6.3.1 (``cfile``) releases: 5.0.7 and 6.1.

Those releases read their 2D property tables from the computed-geometry ``.c##`` file,
so the prepared/result HDF need not carry them; the ``.c##`` file is required instead.
"""

import json
import shutil

import h5py
import numpy as np
import pytest

from ras_commander import _container_compute as worker
from test_container_compute import _results, _run, packet  # noqa: F401  (fixture)

FILE_VERSIONS = {"5.0.7": b"HEC-RAS 5.0.7 March 2019", "6.1": b"HEC-RAS 6.1 September 2021",
                 "6.6": b"HEC-RAS 6.6 September 2024"}


def _cfile_prepared(path, file_version):
    """A prepared HDF shaped like a cfile release: cells, no property tables."""
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Version"] = np.bytes_(file_version)
        area = hdf.create_group("Geometry/2D Flow Areas/Mesh")
        area.create_dataset("Cells Center Coordinate", data=[[0., 0.], [1., 1.]])
        info = hdf.create_group("Plan Data/Plan Information")
        info.attrs["Simulation Start Time"] = np.bytes_("01Jan2020 00:00:00")
        info.attrs["Simulation End Time"] = np.bytes_("01Jan2020 01:00:00")


def test_mesh_property_tables_are_optional_only_when_requested(tmp_path):
    path = tmp_path / "x.hdf"
    _cfile_prepared(path, FILE_VERSIONS["6.1"])
    assert worker._mesh(path, property_tables=False) == {"Mesh": {"cells": 2}}
    with pytest.raises(ValueError, match="Missing or invalid Cells Volume Elevation"):
        worker._mesh(path)
    with pytest.raises(ValueError, match="cell counts differ"):
        worker._mesh(path, {"Mesh": {"cells": 3}}, property_tables=False)


@pytest.mark.parametrize("version, file_version, expected", [
    ("5.0.7", "5.0.7", "cfile"),
    ("6.1", "6.1", "cfile"),
    ("6.6", "6.6", "tmphdf"),
    ("6.1", None, "cfile"),
    ("7.0.1", None, "tmphdf"),
    (None, "6.1", "cfile"),
])
def test_solver_arguments_follow_release(tmp_path, version, file_version, expected):
    path = tmp_path / "x.hdf"
    if file_version:
        _cfile_prepared(path, FILE_VERSIONS[file_version])
    else:
        path.write_bytes(b"no hdf")
    assert worker._solver_arguments(version, path) == expected


def test_solver_arguments_reject_runtime_and_hdf_mismatch(tmp_path):
    path = tmp_path / "x.hdf"
    _cfile_prepared(path, FILE_VERSIONS["6.1"])
    with pytest.raises(ValueError, match="native runtime is HEC-RAS 6.6"):
        worker._solver_arguments("6.6", path)


def _as_release(packet, version):
    """Rewrite the packet's runtime, preparation receipt and HDFs for ``version``."""
    root, project = packet["root"], packet["project"]
    manifest = json.loads(packet["manifest"].read_text())
    manifest["hec_ras_version"] = version
    if version == "5.0.7":
        engine = packet["manifest"].parent / "engine"
        (engine / "bin_ras").mkdir()
        executable = engine / "bin_ras" / "rasUnsteady64"
        executable.write_bytes(b"test executable - never launched")
        executable.chmod(0o755)
        manifest["native"]["layout"] = "bin_ras"
        manifest["artifacts"] = [worker._artifact(executable, packet["manifest"].parent)]
    worker._atomic_json(packet["manifest"], manifest)
    _cfile_prepared(packet["temporary"], FILE_VERSIONS[version])
    shutil.copyfile(packet["temporary"], project.with_suffix(".g01.hdf"))
    project.with_suffix(".c01").write_bytes(b"\x00computed geometry\r\n")
    packet["payload"]["runtime"]["hec_ras_version"] = version
    packet["payload"]["artifacts"][0] = worker._artifact(packet["temporary"], root)
    worker._atomic_json(packet["prep"], packet["payload"])


def _fake_cfile_success(project, engine, plan, timeout, num_cores):
    assert project.with_suffix(".c01").read_bytes() == b"\x00computed geometry\r\n"
    final = project.with_suffix(f".p{plan}.hdf")
    project.with_suffix(f".p{plan}.tmp.hdf").rename(final)
    _results(final)
    (project.parent / f"compute_linux_{plan}.log").write_text("Finished Unsteady Flow Simulation\n")
    return True


@pytest.mark.parametrize("version", ["5.0.7", "6.1"])
def test_cfile_release_publishes_without_hdf_property_tables(packet, monkeypatch, version):
    _as_release(packet, version)
    monkeypatch.setattr(worker, "_call_compute", _fake_cfile_success)
    success, receipt = _run(packet, prepare_receipt=packet["prep"])
    payload = json.loads(receipt.read_text())
    assert success, payload.get("error")
    assert payload["solver_arguments"] == "cfile"
    assert payload["result"]["hdf_validation"]["meshes"]["Mesh"]["water_surface_shape"] == [2, 2]
    assert packet["project"].with_suffix(".p01.hdf").is_file()


@pytest.mark.parametrize("problem", ["missing", "empty"])
def test_cfile_release_requires_computed_geometry(packet, monkeypatch, problem):
    _as_release(packet, "6.1")
    c_file = packet["project"].with_suffix(".c01")
    if problem == "missing":
        c_file.unlink()
    else:
        c_file.write_bytes(b"")
    monkeypatch.setattr(worker, "_call_compute",
                        lambda *a: pytest.fail("solver must not run without the .c file"))
    success, receipt = _run(packet, prepare_receipt=packet["prep"])
    payload = json.loads(receipt.read_text())
    assert not success
    assert "Example.c01" in payload["error"]["message"]


def test_cfile_computed_geometry_change_during_solve_blocks_publication(packet, monkeypatch):
    _as_release(packet, "6.1")

    def mutate(project, engine, plan, timeout, num_cores):
        packet["project"].with_suffix(".c01").write_bytes(b"changed on the host")
        return _fake_cfile_success(project, engine, plan, timeout, num_cores)

    monkeypatch.setattr(worker, "_call_compute", mutate)
    success, receipt = _run(packet, prepare_receipt=packet["prep"])
    assert not success
    assert "changed during native compute" in json.loads(receipt.read_text())["error"]["message"]


def test_tmphdf_release_still_requires_hdf_property_tables(packet, monkeypatch):
    _as_release(packet, "6.1")
    manifest = json.loads(packet["manifest"].read_text())
    manifest["hec_ras_version"] = "6.6"
    worker._atomic_json(packet["manifest"], manifest)
    _cfile_prepared(packet["temporary"], FILE_VERSIONS["6.6"])
    shutil.copyfile(packet["temporary"], packet["project"].with_suffix(".g01.hdf"))
    packet["payload"]["runtime"]["hec_ras_version"] = "6.6"
    packet["payload"]["artifacts"][0] = worker._artifact(packet["temporary"], packet["root"])
    worker._atomic_json(packet["prep"], packet["payload"])
    monkeypatch.setattr(worker, "_call_compute", lambda *a: pytest.fail("must not run"))
    success, receipt = _run(packet, prepare_receipt=packet["prep"])
    assert not success
    assert "Cells Volume Elevation" in json.loads(receipt.read_text())["error"]["message"]
