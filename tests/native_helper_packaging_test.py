import hashlib
import os
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from types import SimpleNamespace

import pytest

from ras_commander import _native_helper


LOGGER_NAME = "ras_commander._native_helper"


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


def test_packaged_helper_resources_exist():
    with _native_helper.packaged_helper_executable_path() as helper_exe:
        assert helper_exe.exists()
        assert helper_exe.name == "RasStoreMapHelper.exe"

    with _native_helper.packaged_helper_source_path() as helper_cs:
        assert helper_cs.exists()
        assert helper_cs.name == "RasStoreMapHelper.cs"


def test_store_maps_runtime_provenance_hashes_actual_helper_and_mapper_runtime(
    monkeypatch,
    tmp_path,
):
    hecras_dir = tmp_path / "HEC-RAS"
    hecras_dir.mkdir()
    mapper = hecras_dir / "RasMapperLib.dll"
    mapper.write_bytes(b"mapper-runtime")
    optional = hecras_dir / "Geospatial.Core.dll"
    optional.write_bytes(b"geospatial-runtime")
    helper = tmp_path / "RasStoreMapHelper.exe"
    helper.write_bytes(b"packaged-helper")
    monkeypatch.setenv("RAS_COMMANDER_MAP_HELPER_PATH", str(helper))

    provenance = _native_helper.store_maps_runtime_provenance(hecras_dir)

    assert provenance["runner"] == "RasStoreMapHelper"
    assert provenance["helper"]["source_file"] == str(helper.resolve())
    assert (
        provenance["helper"]["sha256"] == hashlib.sha256(b"packaged-helper").hexdigest()
    )
    assert set(provenance["libraries"]) == {
        "RasMapperLib.dll",
        "Geospatial.Core.dll",
    }
    assert provenance["libraries"]["RasMapperLib.dll"]["sha256"] == (
        hashlib.sha256(b"mapper-runtime").hexdigest()
    )


def test_normalize_store_map_render_mode_handles_strings_and_dicts():
    assert _native_helper.normalize_store_map_render_mode("horizontal") == "horizontal"
    assert _native_helper.normalize_store_map_render_mode("sloping") == "sloping"
    assert (
        _native_helper.normalize_store_map_render_mode("slopingpretty")
        == "slopingPretty"
    )
    assert (
        _native_helper.normalize_store_map_render_mode({"mode": "sloped"}) == "sloping"
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
    assert (staged.parent / "GDAL" / "common" / "gdal-data.txt").read_text(
        encoding="utf-8"
    ) == "gdal"


def test_stage_helper_executable_serializes_concurrent_gdal_staging(
    monkeypatch,
    tmp_path,
):
    helper = tmp_path / "packaged" / "RasStoreMapHelper.exe"
    helper.parent.mkdir()
    helper.write_bytes(b"helper")
    hecras_dir = tmp_path / "hecras"
    (hecras_dir / "GDAL").mkdir(parents=True)
    state = {"calls": 0, "active": 0, "maximum": 0}

    def fake_link_or_copy(_source, destination):
        state["calls"] += 1
        state["active"] += 1
        state["maximum"] = max(state["maximum"], state["active"])
        try:
            time.sleep(0.05)
            destination.mkdir(parents=True, exist_ok=True)
        finally:
            state["active"] -= 1

    monkeypatch.setattr(
        _native_helper,
        "_link_or_copy_gdal_tree",
        fake_link_or_copy,
    )

    with ThreadPoolExecutor(max_workers=3) as executor:
        staged = list(
            executor.map(
                lambda _index: _native_helper.stage_helper_executable(
                    helper,
                    stage_dir=tmp_path / "stage",
                    hecras_dir=hecras_dir,
                ),
                range(3),
            )
        )

    assert len(set(staged)) == 1
    assert state["calls"] == 3
    assert state["maximum"] == 1


def test_gdal_junction_fallback_warning_is_concise_debug_has_paths(
    monkeypatch,
    tmp_path,
    caplog,
):
    hecras_dir = tmp_path / "hecras"
    source = hecras_dir / "GDAL"
    (source / "common").mkdir(parents=True)
    (source / "common" / "gdal-data.txt").write_text("gdal", encoding="utf-8")
    dest = tmp_path / "stage" / "GDAL"
    monkeypatch.setattr(_native_helper.platform, "system", lambda: "Windows")

    def fake_run(*_args, **_kwargs):
        raise CalledProcessError(returncode=1, cmd=["mklink"], stderr="no")

    monkeypatch.setattr(_native_helper.subprocess, "run", fake_run)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    _native_helper._link_or_copy_gdal_tree(source, dest)

    warning_messages = _messages(caplog, logging.WARNING)
    debug_messages = _messages(caplog, logging.DEBUG)
    assert warning_messages == ["Could not create GDAL junction; copying instead."]
    assert all(str(tmp_path) not in message for message in warning_messages)
    assert any(
        str(source) in message and str(dest) in message for message in debug_messages
    )
    assert (dest / "common" / "gdal-data.txt").read_text(encoding="utf-8") == "gdal"


def test_gdal_junction_race_accepts_runtime_created_by_other_process(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "hecras" / "GDAL"
    source.mkdir(parents=True)
    dest = tmp_path / "stage" / "GDAL"
    monkeypatch.setattr(_native_helper.platform, "system", lambda: "Windows")

    def fake_run(*_args, **_kwargs):
        dest.mkdir(parents=True)
        raise CalledProcessError(returncode=1, cmd=["mklink"], stderr="exists")

    monkeypatch.setattr(_native_helper.subprocess, "run", fake_run)
    monkeypatch.setattr(
        _native_helper.shutil,
        "copytree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not copy over an existing runtime")
        ),
    )

    _native_helper._link_or_copy_gdal_tree(source, dest)

    assert dest.is_dir()


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


def test_run_store_map_once_builds_individual_command_and_caps_gdal_threads(
    monkeypatch,
    tmp_path,
):
    helper = tmp_path / "RasStoreMapHelper.exe"
    hecras_dir = tmp_path / "HEC-RAS"
    result_hdf = tmp_path / "Demo.p01.hdf"
    output_base = tmp_path / "maps" / "Depth (Max)"
    calls = []

    monkeypatch.setattr(_native_helper, "_IS_LINUX", False)
    monkeypatch.setattr(
        _native_helper,
        "_hecras_gdal_subprocess_env",
        lambda _path: {"PATH": "test"},
    )

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return CompletedProcess(cmd, 0, stdout="RESULT_SUCCESS=True", stderr="")

    monkeypatch.setattr(_native_helper.subprocess, "run", fake_run)

    result = _native_helper._run_store_map_once(
        helper_path=helper,
        hecras_dir=hecras_dir,
        helper_mode="horizontal",
        map_type="Depth",
        result_hdf_path=result_hdf,
        profile_name="Max",
        output_base_path=output_base,
        timeout=900,
        working_dir=tmp_path,
        gdal_num_threads=1,
        gdal_cachemax_mb=256,
    )

    assert result.returncode == 0
    assert calls[0][0] == [
        str(helper),
        str(hecras_dir),
        "horizontal",
        "StoreMap",
        "Depth",
        str(result_hdf),
        "Max",
        str(output_base),
    ]
    assert calls[0][1]["timeout"] == 900
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert calls[0][1]["env"]["GDAL_NUM_THREADS"] == "1"
    assert calls[0][1]["env"]["GDAL_CACHEMAX"] == "256"


def test_store_all_maps_wine_child_receives_gdal_performance_environment(
    monkeypatch,
    tmp_path,
):
    ras_process_module = __import__("ras_commander.RasProcess", fromlist=["RasProcess"])
    calls = []
    monkeypatch.setattr(_native_helper, "_IS_LINUX", True)
    monkeypatch.setattr(
        ras_process_module.RasProcess,
        "_get_wine_config",
        staticmethod(
            lambda: SimpleNamespace(
                wine_executable="wine",
                wine_prefix=tmp_path / "wine-prefix",
            )
        ),
    )
    monkeypatch.setattr(
        ras_process_module.RasProcess,
        "_resolve_path_for_rasprocess",
        staticmethod(lambda path: f"Z:{path}"),
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(_native_helper.subprocess, "run", fake_run)

    _native_helper._run_store_all_maps_once(
        helper_path=tmp_path / "RasStoreMapHelper.exe",
        hecras_dir=tmp_path / "HEC-RAS",
        helper_mode="horizontal",
        rasmap_path=tmp_path / "Demo.rasmap",
        result_hdf_path=tmp_path / "Demo.p01.hdf",
        timeout=600,
        working_dir=tmp_path,
        gdal_num_threads="ALL_CPUS",
        gdal_cachemax_mb=256,
    )

    assert calls[0][1]["env"]["GDAL_NUM_THREADS"] == "ALL_CPUS"
    assert calls[0][1]["env"]["GDAL_CACHEMAX"] == "256"


@pytest.mark.parametrize("value", [0, -1, "many"])
def test_run_store_map_helper_rejects_invalid_gdal_threads(value):
    with pytest.raises(ValueError, match="gdal_num_threads"):
        _native_helper.run_store_map_helper(
            hecras_dir=Path("C:/HEC-RAS/7.0"),
            render_mode="horizontal",
            map_type="Depth",
            result_hdf_path=Path("C:/Project/Test.p01.hdf"),
            profile_name="Max",
            gdal_num_threads=value,
        )


@pytest.mark.parametrize("value", [0, -1, True])
def test_run_store_map_helper_rejects_invalid_gdal_cache(value):
    with pytest.raises(ValueError, match="gdal_cachemax_mb"):
        _native_helper.run_store_map_helper(
            hecras_dir=Path("C:/HEC-RAS/7.0"),
            render_mode="horizontal",
            map_type="Depth",
            result_hdf_path=Path("C:/Project/Test.p01.hdf"),
            profile_name="Max",
            gdal_cachemax_mb=value,
        )


def test_store_maps_helper_retry_warning_is_concise_debug_has_paths(
    monkeypatch,
    tmp_path,
    caplog,
):
    helper = tmp_path / "packaged" / "RasStoreMapHelper.exe"
    helper.parent.mkdir()
    helper.write_bytes(b"helper")
    (helper.parent / "GDAL").mkdir()
    hecras_dir = tmp_path / "hecras"
    (hecras_dir / "GDAL").mkdir(parents=True)
    rasmap_path = tmp_path / "project" / "Demo.rasmap"
    result_hdf_path = tmp_path / "project" / "Demo.p01.hdf"
    rasmap_path.parent.mkdir()
    rasmap_path.write_text("<RASMapper />", encoding="utf-8")
    result_hdf_path.write_bytes(b"")
    staged = tmp_path / "stage" / "RasStoreMapHelper.exe"
    calls = []

    class HelperPathContext:
        def __enter__(self):
            return helper

        def __exit__(self, *_args):
            return False

    def fake_stage_helper_executable(*_args, **_kwargs):
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"helper")
        return staged

    def fake_run_store_all_maps_once(*, helper_path, **_kwargs):
        calls.append(helper_path)
        if helper_path == helper:
            raise OSError("direct blocked")
        return CompletedProcess(
            args=[str(helper_path)], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        _native_helper,
        "packaged_helper_executable_path",
        lambda: HelperPathContext(),
    )
    monkeypatch.setattr(
        _native_helper,
        "stage_helper_executable",
        fake_stage_helper_executable,
    )
    monkeypatch.setattr(
        _native_helper,
        "_run_store_all_maps_once",
        fake_run_store_all_maps_once,
    )
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    result = _native_helper.run_store_all_maps_helper(
        hecras_dir=hecras_dir,
        render_mode="horizontal",
        rasmap_path=rasmap_path,
        result_hdf_path=result_hdf_path,
    )

    warning_messages = _messages(caplog, logging.WARNING)
    debug_messages = _messages(caplog, logging.DEBUG)
    assert result.returncode == 0
    assert calls == [helper, staged]
    assert warning_messages == [
        "Direct RasStoreMapHelper execution failed; retrying from staged path."
    ]
    assert all(str(tmp_path) not in message for message in warning_messages)
    assert any(
        str(helper) in message and str(staged) in message for message in debug_messages
    )
