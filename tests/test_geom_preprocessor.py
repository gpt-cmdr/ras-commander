import os
import time
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from ras_commander.geom.GeomPreprocessor import (
    GEOMETRY_PREPROCESSOR_GEOMETRY_ONLY_RUN_FLAGS,
    GeomPreprocessor,
)
from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan


def _write_legacy_geometry_hdf(
    path: Path,
    *,
    file_version: str = "HEC-RAS 6.6 September 2024",
) -> Path:
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Type"] = "HEC-RAS Geometry"
        hdf.attrs["File Version"] = file_version
        hdf.create_group("Geometry/GeomPreprocess").create_dataset(
            "Cache",
            data=np.array([1], dtype=np.int32),
        )
        mesh = hdf.create_group("Geometry/2D Flow Areas/MainArea")
        mesh.create_dataset(
            "Faces Area Elevation Info",
            data=np.array([[0, 2]], dtype=np.int32),
        )
        mesh.create_dataset(
            "Faces Area Elevation Values",
            data=np.array(
                [[100.0, 0.0, 0.0, 0.04], [101.0, 5.0, 2.5, 0.04]],
                dtype=np.float64,
            ),
        )
        mesh.create_dataset(
            "Faces FacePoint Indexes",
            data=np.array([[0, 1]], dtype=np.int32),
        )
        landcover = hdf.create_group("Geometry/Land Cover (Manning's n)")
        landcover.create_dataset(
            "Calibration Table",
            data=np.array(
                [(b"Region", 1.0)],
                dtype=[("Name", "S16"), ("Factor", "<f8")],
            ),
        )
    return path


def _write_ready_2d_geometry_hdf(path: Path) -> Path:
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Type"] = "HEC-RAS Geometry"
        collection = hdf.create_group("Geometry/2D Flow Areas")
        collection.create_dataset(
            "Attributes",
            data=np.array([(b"MainArea",)], dtype=[("Name", "S32")]),
        )
        mesh = collection.create_group("MainArea")
        mesh.create_dataset(
            "Cells Center Coordinate",
            data=np.array([[1.0, 2.0]], dtype=np.float64),
        )
        mesh.create_dataset(
            "Faces FacePoint Indexes",
            data=np.array([[0, 1]], dtype=np.int32),
        )
    return path


def test_compute_message_paths_include_data_error_files(tmp_path):
    paths = GeomPreprocessor._compute_message_paths(tmp_path, "Model", "04")

    names = {Path(path).name for path in paths}

    assert "Model.p04.data_errors.txt" in names
    assert "Model.p04.data_warnings.txt" in names


def test_read_compute_messages_ignores_stale_hdf_messages(tmp_path, monkeypatch):
    start_time = time.time()
    hdf_path = tmp_path / "Model.p01.hdf"
    hdf_path.write_bytes(b"placeholder")
    os.utime(hdf_path, (start_time - 30, start_time - 30))

    monkeypatch.setattr(
        HdfResultsPlan,
        "get_compute_messages_hdf_only",
        staticmethod(lambda _path: "stale hdf messages"),
    )

    paths, messages = GeomPreprocessor._read_compute_messages(
        [],
        hdf_message_path=hdf_path,
        modified_after=start_time,
    )

    assert paths == []
    assert messages == ""


def test_read_compute_messages_includes_fresh_hdf_messages(tmp_path, monkeypatch):
    start_time = time.time()
    hdf_path = tmp_path / "Model.p01.hdf"
    hdf_path.write_bytes(b"placeholder")
    os.utime(hdf_path, (start_time + 1, start_time + 1))

    monkeypatch.setattr(
        HdfResultsPlan,
        "get_compute_messages_hdf_only",
        staticmethod(lambda _path: "fresh hdf messages"),
    )

    paths, messages = GeomPreprocessor._read_compute_messages(
        [],
        hdf_message_path=hdf_path,
        modified_after=start_time,
    )

    assert paths == [hdf_path]
    assert messages == "fresh hdf messages"


def test_preprocessor_artifacts_include_fresh_tmp_hdf_only(tmp_path):
    start_time = time.time()
    stale_geom_hdf = tmp_path / "Model.g01.hdf"
    fresh_tmp_hdf = tmp_path / "Model.p02.tmp.hdf"
    stale_geom_hdf.write_bytes(b"old")
    fresh_tmp_hdf.write_bytes(b"new")
    os.utime(stale_geom_hdf, (start_time - 30, start_time - 30))
    os.utime(fresh_tmp_hdf, (start_time + 1, start_time + 1))

    artifacts = GeomPreprocessor._preprocessor_artifacts(
        tmp_path,
        "Model",
        "02",
        "01",
        tmp_hdf_path=fresh_tmp_hdf,
        modified_after=start_time,
    )

    assert artifacts == [fresh_tmp_hdf]


@pytest.mark.parametrize("hdf_written_at", [None, 0, 30])
@pytest.mark.parametrize("signal_message", [False, True])
def test_geometry_only_waits_for_fresh_hdf_after_sidecar(
    tmp_path, monkeypatch, hdf_written_at, signal_message
):
    import importlib

    module = importlib.import_module("ras_commander.geom.GeomPreprocessor")
    start = 1000.0
    clock = {"now": start}
    hdf = _write_ready_2d_geometry_hdf(tmp_path / "Model.g01.hdf")
    sidecar = tmp_path / "Model.c01"
    sidecar.write_bytes(b"new preprocessor sidecar")
    os.utime(sidecar, (start, start))
    os.utime(hdf, (start - 300, start - 300))
    message = tmp_path / "Model.bco01"
    if signal_message:
        message.write_text("Starting Unsteady Flow Computations\n")
        os.utime(message, (start, start))
    if hdf_written_at == 0:
        os.utime(hdf, (start, start))

    def sleep(seconds):
        clock["now"] += seconds
        if hdf_written_at and clock["now"] >= start + hdf_written_at:
            written = start + hdf_written_at
            os.utime(hdf, (written, written))

    monkeypatch.setattr(
        module, "time", SimpleNamespace(time=lambda: clock["now"], sleep=sleep)
    )
    process = SimpleNamespace(poll=lambda: 0 if clock["now"] >= start + 60 else None)
    result = GeomPreprocessor._monitor_compute_messages(
        process=process,
        message_paths=[message] if signal_message else [],
        start_time=start,
        max_wait=80,
        signals=["Starting Unsteady Flow Computations"] if signal_message else [],
        geometry_only_artifacts=[sidecar, hdf],
        geometry_hdf_path=hdf,
        flow_type="unsteady_2d",
    )

    assert not result["timed_out"]
    if hdf_written_at is None:
        assert result["signal_detected"] is None
        assert clock["now"] == start + 60
    else:
        if signal_message and hdf_written_at == 0:
            assert result["signal_detected"] == "Starting Unsteady Flow Computations"
        else:
            assert "semantically ready and stable" in result["signal_detected"]
            assert clock["now"] >= start + hdf_written_at + 10


@pytest.mark.parametrize("force", [False, True])
def test_geometry_only_normal_exit_rejects_inherited_hdf(tmp_path, monkeypatch, force):
    import importlib

    module = importlib.import_module("ras_commander.geom.GeomPreprocessor")
    plan = tmp_path / "Model.p01"
    plan.write_text("Geom File=g01\nRun UNet=-1\n")
    project = tmp_path / "Model.prj"
    project.write_text("Proj Title=synthetic readiness fixture\n")
    executable = tmp_path / "mock-native-executable"
    executable.write_bytes(b"never executed")
    hdf = _write_ready_2d_geometry_hdf(tmp_path / "Model.g01.hdf")
    past = time.time() - 300
    os.utime(hdf, (past, past))
    ras = SimpleNamespace(
        project_folder=tmp_path,
        project_name="Model",
        prj_file=project,
        ras_exe_path=executable,
        check_initialized=lambda: None,
    )

    def start_process(*args, **kwargs):
        (tmp_path / "Model.c01").write_bytes(b"new sidecar, inherited HDF")
        return SimpleNamespace(
            returncode=0,
            poll=lambda: 0,
            wait=lambda **kwargs: 0,
            communicate=lambda **kwargs: (b"", b""),
        )

    monkeypatch.setattr(module.subprocess, "Popen", start_process)
    monkeypatch.setattr(
        GeomPreprocessor, "_resolve_flow_type", lambda *args: "unsteady_2d"
    )
    monkeypatch.setattr(
        GeomPreprocessor,
        "_wait_for_preprocess_child",
        lambda **kwargs: {"saw_child": False, "timed_out": False, "tmp_hdf_path": None},
    )
    monkeypatch.setattr(
        module.BcoMonitor, "enable_detailed_logging", lambda *args: None
    )
    monkeypatch.setattr(
        module.RasPlan, "set_geom_preprocessor", lambda *args, **kwargs: None
    )
    result = GeomPreprocessor.run_geometry_preprocessor(
        plan,
        ras_object=ras,
        force=force,
        clear_messages=False,
        geometry_only=True,
        dialog_watchdog=False,
    )

    assert not result.success
    assert "Geometry HDF was not freshly written" in result.error
    assert Path(result.artifact_paths[0]).name == "Model.c01"


def test_geometry_hdf_readiness_rejects_empty_placeholder(tmp_path):
    hdf_path = tmp_path / "Model.g03.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_group("Geometry")

    ready, reason = GeomPreprocessor._geometry_hdf_readiness(
        hdf_path,
        flow_type="unsteady_2d",
    )

    assert not ready
    assert "File Type" in reason


def test_geometry_hdf_readiness_rejects_2d_area_without_topology(tmp_path):
    hdf_path = tmp_path / "Model.g03.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.attrs["File Type"] = "HEC-RAS Geometry"
        collection = hdf.create_group("Geometry/2D Flow Areas")
        collection.create_dataset(
            "Attributes",
            data=np.array([(b"MainArea",)], dtype=[("Name", "S32")]),
        )
        collection.create_group("MainArea")

    ready, reason = GeomPreprocessor._geometry_hdf_readiness(
        hdf_path,
        flow_type="unsteady_2d",
    )

    assert not ready
    assert "cell/face topology" in reason


def test_geometry_hdf_readiness_accepts_populated_2d_mesh(tmp_path):
    hdf_path = _write_ready_2d_geometry_hdf(tmp_path / "Model.g03.hdf")

    ready, reason = GeomPreprocessor._geometry_hdf_readiness(
        hdf_path,
        flow_type="unsteady_2d",
    )

    assert ready
    assert "MainArea" in reason


def _write_current_geometry_pair(tmp_path):
    """Create current text and populated native-format synthetic 2D metadata."""
    path = _write_ready_2d_geometry_hdf(tmp_path / "Model.g03.hdf")
    ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    text = path.with_suffix("")
    text.write_text(
        "Geom Title=Synthetic current geometry\nStorage Area=MainArea,5,5\n"
        "Storage Area Surface Line= 5\n"
        + "".join(f"{x:16.6f}{y:16.6f}\n" for x, y in ring)
        + "Storage Area Type= 0\nStorage Area Area=\nStorage Area Min Elev=\n"
        "Storage Area Is2D=-1\nStorage Area 2D Points= 3\n",
        encoding="utf-8",
    )
    with h5py.File(path, "a") as hdf:
        areas = hdf["Geometry/2D Flow Areas"]
        del areas["Attributes"]
        areas.create_dataset(
            "Attributes",
            data=np.array(
                [(b"MainArea", 3)], dtype=[("Name", "S32"), ("Cell Count", "<i4")]
            ),
        )
        mesh = areas["MainArea"]
        del mesh["Cells Center Coordinate"]
        mesh.create_dataset("Cells Center Coordinate", data=np.zeros((3, 2)))
        areas.create_dataset(
            "Polygon Info", data=np.array([[0, 5, 0, 1]], dtype=np.int32)
        )
        areas.create_dataset("Polygon Parts", data=np.array([[0, 5]], dtype=np.int32))
        areas.create_dataset("Polygon Points", data=np.asarray(ring, dtype=float))
    return text, path


def test_geometry_hdf_readiness_accepts_current_text_import(tmp_path):
    _text, hdf = _write_current_geometry_pair(tmp_path)
    ready, reason = GeomPreprocessor._geometry_hdf_readiness(hdf, flow_type="Unsteady")
    assert ready, reason


def test_geometry_hdf_readiness_preserves_partial_text_without_mesh_metadata(tmp_path):
    text, hdf = _write_current_geometry_pair(tmp_path)
    text.write_text("Geom Title=Synthetic partial text\n", encoding="utf-8")
    ready, reason = GeomPreprocessor._geometry_hdf_readiness(hdf, flow_type="Unsteady")
    assert ready, reason


def test_geometry_hdf_readiness_preserves_pure_1d_geometry(tmp_path):
    path = tmp_path / "Model.g01.hdf"
    path.with_suffix("").write_text(
        "Geom Title=Synthetic 1D geometry\n", encoding="utf-8"
    )
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Type"] = "HEC-RAS Geometry"
        hdf.create_dataset(
            "Geometry/Cross Sections/Attributes",
            data=np.array([(b"XS1",)], dtype=[("Name", "S32")]),
        )
    ready, reason = GeomPreprocessor._geometry_hdf_readiness(path, flow_type="Steady")
    assert ready, reason
    assert "Cross Sections" in reason


@pytest.mark.parametrize("mismatch", ["perimeter", "breakline", "cell_count"])
def test_geometry_hdf_readiness_rejects_rewritten_parent_metadata(tmp_path, mismatch):
    text, path = _write_current_geometry_pair(tmp_path)
    if mismatch == "perimeter":
        with h5py.File(path, "r+") as hdf:
            hdf["Geometry/2D Flow Areas/Polygon Points"][:] *= 2
    elif mismatch == "breakline":
        text.write_text(
            text.read_text() + "BreakLine Name=New channel\n", encoding="utf-8"
        )
    else:
        with h5py.File(path, "r+") as hdf:
            areas = hdf["Geometry/2D Flow Areas"]
            del areas["Attributes"]
            areas.create_dataset(
                "Attributes",
                data=np.array(
                    [(b"MainArea", 20)], dtype=[("Name", "S32"), ("Cell Count", "<i4")]
                ),
            )
    # A new timestamp and populated parent topology must not establish readiness.
    assert path.stat().st_mtime > time.time() - 5
    ready, reason = GeomPreprocessor._geometry_hdf_readiness(path, flow_type="Unsteady")
    assert not ready
    assert "geometry text/HDF mismatch" in reason


def test_geometry_hdf_readiness_requires_stored_2d_topology_for_generic_unsteady(
    tmp_path,
):
    _text, path = _write_current_geometry_pair(tmp_path)
    with h5py.File(path, "r+") as hdf:
        del hdf["Geometry/2D Flow Areas/MainArea/Faces FacePoint Indexes"]
    ready, reason = GeomPreprocessor._geometry_hdf_readiness(path, flow_type="Unsteady")
    assert not ready
    assert "cell/face topology" in reason


def test_geometry_only_monitor_waits_for_current_text_import(tmp_path, monkeypatch):
    import importlib

    module = importlib.import_module("ras_commander.geom.GeomPreprocessor")
    _text, path = _write_current_geometry_pair(tmp_path)
    with h5py.File(path, "r+") as hdf:
        points = hdf["Geometry/2D Flow Areas/Polygon Points"][:]
        hdf["Geometry/2D Flow Areas/Polygon Points"][:] = points * 2
    start = time.time()
    os.utime(path, (start, start))
    clock = {"now": start, "imported": False}

    def advance(seconds):
        clock["now"] += seconds
        if clock["now"] >= start + 40 and not clock["imported"]:
            with h5py.File(path, "r+") as hdf:
                hdf["Geometry/2D Flow Areas/Polygon Points"][:] = points
            os.utime(path, (clock["now"], clock["now"]))
            clock["imported"] = True

    monkeypatch.setattr(module.time, "time", lambda: clock["now"])
    monkeypatch.setattr(module.time, "sleep", advance)
    result = GeomPreprocessor._monitor_compute_messages(
        process=SimpleNamespace(poll=lambda: None),
        message_paths=[],
        start_time=start,
        max_wait=80,
        signals=[],
        geometry_only_artifacts=[path],
        geometry_hdf_path=path,
        flow_type="Unsteady",
    )
    assert not result["timed_out"]
    assert "semantically ready and stable" in result["signal_detected"]
    assert clock["imported"]
    assert clock["now"] >= start + 50


def test_geometry_only_run_flags_disable_unsteady_flow(tmp_path):
    plan_path = tmp_path / "Model.p01"
    plan_path.write_text(
        "\n".join(
            [
                "Run HTab=-1 ",
                "Run UNet=-1 ",
                "Run PostProcess=-1 ",
                "Run RASMapper=-1 ",
                "Run Sediment=-1 ",
                "Run WQNet=-1 ",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    GeomPreprocessor._set_plan_run_flags(
        plan_path,
        GEOMETRY_PREPROCESSOR_GEOMETRY_ONLY_RUN_FLAGS,
    )

    updated = plan_path.read_text(encoding="utf-8")
    assert "Run UNet= 0" in updated
    assert "Run PostProcess= 0" in updated
    assert "Run RASMapper= 0" in updated


def test_legacy_geometry_hdf_recovery_requires_explicit_acknowledgement(
    tmp_path,
):
    hdf_path = _write_legacy_geometry_hdf(tmp_path / "Model.g01.hdf")

    with pytest.raises(RuntimeError, match="acknowledge_legacy_recovery=True"):
        GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache(
            hdf_path,
            expected_file_version="HEC-RAS 6.6 September 2024",
        )

    assert not list(tmp_path.glob("*.legacy-recovery.bak.hdf"))
    with h5py.File(hdf_path, "r") as hdf:
        assert "Geometry/GeomPreprocess" in hdf


def test_legacy_geometry_hdf_recovery_requires_exact_version_before_backup(
    tmp_path,
):
    hdf_path = _write_legacy_geometry_hdf(tmp_path / "Model.g01.hdf")

    with pytest.raises(ValueError, match="file-version guard"):
        GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache(
            hdf_path,
            expected_file_version="HEC-RAS 6.5 June 2024",
            acknowledge_legacy_recovery=True,
        )

    assert not list(tmp_path.glob("*.legacy-recovery.bak.hdf"))


def test_legacy_geometry_hdf_recovery_rejects_hec_ras_7(tmp_path):
    hdf_path = _write_legacy_geometry_hdf(
        tmp_path / "Model.g01.hdf",
        file_version="HEC-RAS 7.0 April 2026",
    )

    with pytest.raises(ValueError, match="restricted to legacy"):
        GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache(
            hdf_path,
            expected_file_version="HEC-RAS 7.0 April 2026",
            acknowledge_legacy_recovery=True,
        )

    assert not list(tmp_path.glob("*.legacy-recovery.bak.hdf"))


def test_legacy_geometry_hdf_recovery_backs_up_and_preserves_source_data(
    tmp_path,
):
    hdf_path = _write_legacy_geometry_hdf(tmp_path / "Model.g01.hdf")

    removed = GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache(
        hdf_path,
        expected_file_version="HEC-RAS 6.6 September 2024",
        acknowledge_legacy_recovery=True,
    )

    backup_path = tmp_path / "Model.g01.legacy-recovery.bak.hdf"
    assert backup_path.exists()
    assert "Geometry/GeomPreprocess" in removed
    assert "Geometry/2D Flow Areas/MainArea/Faces Area Elevation Info" in removed
    assert "Geometry/2D Flow Areas/MainArea/Faces Area Elevation Values" in removed
    with h5py.File(backup_path, "r") as backup:
        assert "Geometry/GeomPreprocess" in backup
        assert "Geometry/2D Flow Areas/MainArea/Faces Area Elevation Values" in backup
    with h5py.File(hdf_path, "r") as hdf:
        assert "Geometry/GeomPreprocess" not in hdf
        assert "Geometry/2D Flow Areas/MainArea/Faces Area Elevation Values" not in hdf
        assert "Geometry/2D Flow Areas/MainArea/Faces FacePoint Indexes" in hdf
        assert "Geometry/Land Cover (Manning's n)/Calibration Table" in hdf


def test_legacy_geometry_hdf_recovery_refuses_existing_backup(tmp_path):
    hdf_path = _write_legacy_geometry_hdf(tmp_path / "Model.g01.hdf")
    backup_path = tmp_path / "Model.g01.legacy-recovery.bak.hdf"
    backup_path.write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="already exists"):
        GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache(
            hdf_path,
            expected_file_version="HEC-RAS 6.6 September 2024",
            acknowledge_legacy_recovery=True,
        )

    assert backup_path.read_bytes() == b"existing"
    with h5py.File(hdf_path, "r") as hdf:
        assert "Geometry/GeomPreprocess" in hdf


def test_legacy_geometry_hdf_recovery_rejects_malformed_dataset_pair(
    tmp_path,
):
    hdf_path = _write_legacy_geometry_hdf(tmp_path / "Model.g01.hdf")
    with h5py.File(hdf_path, "r+") as hdf:
        del hdf["Geometry/2D Flow Areas/MainArea/Faces Area Elevation Values"]

    with pytest.raises(ValueError, match="incomplete legacy property-table pair"):
        GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache(
            hdf_path,
            expected_file_version="HEC-RAS 6.6 September 2024",
            acknowledge_legacy_recovery=True,
        )

    assert not list(tmp_path.glob("*.legacy-recovery.bak.hdf"))


def test_legacy_geometry_hdf_recovery_is_idempotent_after_invalidation(
    tmp_path,
):
    hdf_path = _write_legacy_geometry_hdf(tmp_path / "Model.g01.hdf")

    first = GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache(
        hdf_path,
        expected_file_version="HEC-RAS 6.6 September 2024",
        acknowledge_legacy_recovery=True,
    )
    second = GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache(
        hdf_path,
        expected_file_version="HEC-RAS 6.6 September 2024",
        acknowledge_legacy_recovery=True,
    )

    assert first
    assert second == []
    assert len(list(tmp_path.glob("*.legacy-recovery.bak.hdf"))) == 1


def test_clear_geompre_hdf_deprecated_wrapper_is_guarded(tmp_path):
    hdf_path = _write_legacy_geometry_hdf(tmp_path / "Model.g01.hdf")

    with pytest.warns(DeprecationWarning, match="deprecated"):
        removed = GeomPreprocessor.clear_geompre_hdf(
            hdf_path,
            expected_file_version="HEC-RAS 6.6 September 2024",
            acknowledge_legacy_recovery=True,
        )

    assert "Geometry/GeomPreprocess" in removed
