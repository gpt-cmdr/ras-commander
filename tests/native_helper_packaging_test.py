import os
from pathlib import Path

import pytest

from ras_commander import _native_helper


def test_packaged_helper_resources_exist():
    with _native_helper.packaged_helper_executable_path() as helper_exe:
        assert helper_exe.exists()
        assert helper_exe.name == "RasStoreMapHelper.exe"

    with _native_helper.packaged_helper_source_path() as helper_cs:
        assert helper_cs.exists()
        assert helper_cs.name == "RasStoreMapHelper.cs"


def test_normalize_store_map_render_mode_handles_strings_and_dicts():
    assert _native_helper.normalize_store_map_render_mode("horizontal") == "horizontal"
    assert _native_helper.normalize_store_map_render_mode("sloping") == "sloping"
    assert (
        _native_helper.normalize_store_map_render_mode("slopingpretty")
        == "slopingPretty"
    )
    assert (
        _native_helper.normalize_store_map_render_mode({"mode": "sloped"})
        == "sloping"
    )


def test_helper_path_override_is_respected(monkeypatch, tmp_path):
    override = tmp_path / "custom_helper.exe"
    override.write_bytes(b"helper")
    monkeypatch.setenv("RAS_COMMANDER_MAP_HELPER_PATH", str(override))

    with _native_helper.packaged_helper_executable_path() as helper_exe:
        assert helper_exe == override


def test_stage_helper_executable_builds_runtime_bundle_with_gdal(tmp_path):
    hecras_dir = tmp_path / "hecras"
    (hecras_dir / "GDAL" / "common").mkdir(parents=True)
    (hecras_dir / "GDAL" / "common" / "gdal-data.txt").write_text(
        "gdal",
        encoding="utf-8",
    )

    with _native_helper.packaged_helper_executable_path() as helper_exe:
        staged = _native_helper.stage_helper_executable(
            helper_exe,
            stage_dir=tmp_path,
            hecras_dir=hecras_dir,
        )

    assert staged.exists()
    assert staged.parent.parent == tmp_path
    assert staged.name == "RasStoreMapHelper.exe"
    assert (staged.parent / "GDAL").is_dir()
    assert (
        staged.parent / "GDAL" / "common" / "gdal-data.txt"
    ).read_text(encoding="utf-8") == "gdal"


def test_hecras_gdal_subprocess_env_points_at_bundled_runtime(monkeypatch, tmp_path):
    hecras_dir = tmp_path / "hecras"
    (hecras_dir / "GDAL" / "bin64").mkdir(parents=True)
    (hecras_dir / "GDAL" / "common" / "data").mkdir(parents=True)
    monkeypatch.setenv("PATH", "C:\\Existing")

    env = _native_helper._hecras_gdal_subprocess_env(hecras_dir)

    assert env["GDAL_DATA"] == str(hecras_dir / "GDAL" / "common" / "data")
    assert env["PROJ_LIB"] == env["GDAL_DATA"]
    assert env["PATH"].split(os.pathsep)[:2] == [
        str(hecras_dir / "GDAL" / "bin64"),
        str(hecras_dir),
    ]


def test_run_store_all_maps_helper_honors_disable_flag(monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_MAP_HELPER_DISABLE", "1")

    with pytest.raises(RuntimeError, match="disabled"):
        _native_helper.run_store_all_maps_helper(
            hecras_dir=Path("C:/HEC-RAS/6.6"),
            render_mode="horizontal",
            rasmap_path=Path("C:/Project/Test.rasmap"),
            result_hdf_path=Path("C:/Project/Test.p01.hdf"),
        )
