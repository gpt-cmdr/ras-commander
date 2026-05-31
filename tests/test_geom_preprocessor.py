import os
import time
from pathlib import Path

from ras_commander.geom.GeomPreprocessor import (
    GEOMETRY_PREPROCESSOR_GEOMETRY_ONLY_RUN_FLAGS,
    GeomPreprocessor,
)
from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan


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
