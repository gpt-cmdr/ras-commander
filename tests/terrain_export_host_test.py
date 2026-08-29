"""Unit coverage for native RAS Mapper terrain export supervision."""

from __future__ import annotations

import importlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

import pandas as pd
import pytest

from ras_commander import RasMap, RasTerrain, TerrainExportResult
from ras_commander.native import terrain_export_host as host
from ras_commander.RasPrj import RasPrj


def _source(
    index: int,
    cell: float,
    priority: int,
    min_x: float = -100.0,
    max_y: float = 100.0,
) -> dict:
    return {
        "index": index,
        "filename": f"source {index}.tif",
        "priority": priority,
        "columns": 100,
        "rows": 100,
        "extent": {
            "min_x": min_x,
            "min_y": max_y - 100 * cell,
            "max_x": min_x + 100 * cell,
            "max_y": max_y,
        },
        "cell_sizes": [cell],
        "levels": 1,
    }


def test_terrain_selection_requires_unambiguous_exact_name():
    layers = pd.DataFrame(
        [
            {"name": "Terrain", "resolved_path": "a.hdf"},
            {"name": "Terrain's native", "resolved_path": "b.hdf"},
        ]
    )
    with pytest.raises(ValueError, match="required"):
        host.select_terrain_row(layers, None)
    assert host.select_terrain_row(layers, "Terrain's native")["resolved_path"] == "b.hdf"
    with pytest.raises(ValueError, match="not found"):
        host.select_terrain_row(layers, "terrain")
    assert host.select_terrain_row(layers.iloc[[0]], None)["name"] == "Terrain"


@pytest.mark.parametrize("factor", [1, 2, 4, 8])
def test_exact_source_derived_cell_size_math(factor):
    _, native = host.select_authoritative_source([_source(0, 3.2808333333333124, 0)])
    assert native * factor == pytest.approx(3.2808333333333124 * factor, rel=0, abs=1e-14)
    assert host.validate_downsample_factor(factor) == factor


@pytest.mark.parametrize("bad", [0, 3, 16, True, 2.0, "2"])
def test_invalid_downsample_factors_are_rejected(bad):
    with pytest.raises(ValueError, match="1, 2, 4, or 8"):
        host.validate_downsample_factor(bad)


def test_grid_snapping_is_outward_and_stable_for_negative_coordinates():
    snapped, columns, rows = host.snap_extent_to_grid(
        (-9.9, -21.1, 10.1, -0.1), origin_x=-100.0, origin_y=100.0, cell_size=5.0
    )
    assert snapped == pytest.approx((-10.0, -25.0, 15.0, 0.0))
    assert (columns, rows) == (5, 5)
    invocation = host.vendor_invocation_extent(snapped, 5.0)
    assert invocation[0] == snapped[0]
    assert invocation[3] == snapped[3]
    assert invocation[1] > snapped[1]
    assert invocation[2] < snapped[2]
    assert math_ceil_cells(invocation[2] - invocation[0], 5.0) == columns
    assert math_ceil_cells(invocation[3] - invocation[1], 5.0) == rows


def math_ceil_cells(distance: float, cell: float) -> int:
    import math

    return math.ceil(distance / cell)


def test_multi_source_selection_uses_finest_priority_without_origin_rejection():
    sources = [
        _source(0, 10.0, 0, min_x=0.25),
        _source(1, 5.0, 2, min_x=1.75),
        _source(2, 5.0, 1, min_x=-3.125),
    ]
    authoritative, native = host.select_authoritative_source(sources)
    assert native == 5.0
    assert authoritative["index"] == 2


def test_multi_source_nonintegral_resolution_ratio_is_native_resample_input():
    sources = [_source(0, 36.504512, 0), _source(1, 20.0, 1)]
    authoritative, native = host.select_authoritative_source(sources)
    assert authoritative["index"] == 1
    assert native == 20.0
    assert native * host.validate_downsample_factor(2) == 40.0


@pytest.mark.parametrize("cell_sizes", [[], [0.0], [-5.0], [float("nan")]])
def test_multi_source_still_rejects_unusable_level_zero_grids(cell_sizes):
    bad_source = _source(1, 20.0, 1)
    bad_source["cell_sizes"] = cell_sizes
    with pytest.raises(ValueError, match="level-zero|finite and positive"):
        host.select_authoritative_source([_source(0, 36.504512, 0), bad_source])


@pytest.mark.parametrize(
    "value",
    [
        Path("project with spaces/model.prj"),
        "project with spaces/model.prj",
        r"C:\Models With Spaces\model.prj",
        r"\\server\share name\model.prj",
    ],
)
def test_windows_path_str_path_unc_and_spaces_remain_lossless(monkeypatch, value):
    monkeypatch.setattr(host.platform, "system", lambda: "Windows")
    assert str(host._normalize_host_path(value)) == str(Path(os.fspath(value)))


@pytest.mark.parametrize(
    ("version", "canonical"),
    [
        ("6.4", "6.4.1"),
        ("6.4.1", "6.4.1"),
        ("6.41", "6.4.1"),
        ("64", "6.4.1"),
        ("641", "6.4.1"),
        (r"C:\Program Files (x86)\HEC\HEC-RAS\6.4.1\Ras.exe", "6.4.1"),
        ("6.5", "6.5"),
        ("6.5.0", "6.5"),
        ("6.50", "6.5"),
        ("65", "6.5"),
        ("6.6", "6.6"),
        ("6.6.0", "6.6"),
        ("6.60", "6.6"),
        ("66", "6.6"),
        ("7.0.1", "7.0.1"),
        ("7.01", "7.0.1"),
        ("701", "7.0.1"),
        (r"C:\Program Files (x86)\HEC\HEC-RAS\7.0.1\Ras.exe", "7.0.1"),
        ("7.1", "7.1"),
        ("7.1.0", "7.1"),
        ("7.10", "7.1"),
        ("71", "7.1"),
        (r"C:\Program Files (x86)\HEC\HEC-RAS\7.1\Ras.exe", "7.1"),
    ],
)
def test_exact_accepted_terrain_export_versions(version, canonical):
    assert host.resolve_supported_hecras_version(version, None) == canonical


@pytest.mark.parametrize(
    "version", ["6.4.1.1", "6.6.0.1", "6.6.1", "7.0 Beta"]
)
def test_unqualified_or_new_version_terms_are_rejected(version):
    with pytest.raises(ValueError):
        host.resolve_supported_hecras_version(version, None)


@pytest.mark.parametrize("version", ["6.7", "6.70", "6.7 Beta 4", "6.7 Beta 5"])
def test_hecras_67_betas_are_checked_but_not_accepted(version):
    with pytest.raises(ValueError, match="released only as beta builds"):
        host.resolve_supported_hecras_version(version, None)


def test_hecras_640_is_rejected_with_official_elevation_defect_reason():
    version = r"C:\Program Files (x86)\HEC\HEC-RAS\6.4\Ras.exe"
    with pytest.raises(ValueError, match=r"could add 1\.0 to elevations"):
        host.resolve_supported_hecras_version(version, None)


def test_hecras_700_is_rejected_with_official_modification_defect_reason():
    with pytest.raises(ValueError, match="omit the minimum-Y portion"):
        host.resolve_supported_hecras_version("7.0", None)


def test_hecras_71_is_forward_open_before_the_binary_is_published():
    assert host.resolve_supported_hecras_version("7.1", None) == "7.1"


@pytest.mark.parametrize(
    "version",
    [
        "6.3",
        "6.3.0.2",
        "6.3.1",
        "6.30",
        "6.31",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.3\Ras.exe",
    ],
)
def test_hecras_63_is_rejected_with_native_contract_reason(version):
    with pytest.raises(ValueError, match="6\\.3 lacks the bounded"):
        host.resolve_supported_hecras_version(version, None)


def test_public_api_rejects_unsupported_rasprj_before_filesystem_work(tmp_path):
    project = RasPrj()
    project.initialized = True
    project.ras_version = "6.3"
    output = tmp_path / "must-not-be-created" / "terrain.tif"

    with pytest.raises(
        ValueError,
        match="exactly 6\\.4\\.1, 6\\.5, 6\\.6, 7\\.0\\.1, and 7\\.1",
    ):
        RasTerrain.export_rasmapper_terrain(
            tmp_path / "missing.prj",
            output,
            ras_object=project,
        )

    assert not output.parent.exists()


def test_explicit_version_must_match_exact_rasprj_version():
    project = RasPrj()
    project.initialized = True
    project.ras_version = "6.6"

    with pytest.raises(ValueError, match="conflicts with ras_object\\.ras_version"):
        host.resolve_supported_hecras_version("6.5", project)


def test_rasprj_executable_folder_conflict_is_rejected():
    project = RasPrj()
    project.initialized = True
    project.ras_version = "6.6"
    project.ras_exe_path = r"C:\Program Files (x86)\HEC\HEC-RAS\6.5\Ras.exe"

    with pytest.raises(ValueError, match="ras_exe_path runtime '6\\.5'"):
        host.resolve_supported_hecras_version(None, project)


@pytest.mark.parametrize(
    "ras_exe_path",
    [
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.5\Ras.exe",
        r"\\server\HEC RAS Installations\6.5\Ras.exe",
    ],
)
def test_windows_executable_conflict_reports_runtime_on_posix(
    monkeypatch, ras_exe_path
):
    monkeypatch.setattr(host, "Path", PurePosixPath)
    project = RasPrj()
    project.initialized = True
    project.ras_version = "6.6"
    project.ras_exe_path = ras_exe_path

    with pytest.raises(ValueError, match="ras_exe_path runtime '6\\.5'"):
        host.resolve_supported_hecras_version(None, project)


def test_rasprj_64_alias_is_verified_as_641_from_executable_folder():
    project = RasPrj()
    project.initialized = True
    project.ras_version = "6.4"
    project.ras_exe_path = r"C:\Program Files (x86)\HEC\HEC-RAS\6.4.1\Ras.exe"

    assert host.resolve_supported_hecras_version(None, project) == "6.4.1"


def test_rasprj_700_is_rejected_before_filesystem_work(tmp_path):
    project = RasPrj()
    project.initialized = True
    project.ras_version = "7.0"
    project.ras_exe_path = r"C:\Program Files (x86)\HEC\HEC-RAS\7.0\Ras.exe"
    output = tmp_path / "must-not-be-created" / "terrain.tif"

    with pytest.raises(ValueError, match="omit the minimum-Y portion"):
        RasTerrain.export_rasmapper_terrain(
            tmp_path / "missing.prj", output, ras_object=project
        )

    assert not output.parent.exists()


def test_rasprj_701_is_accepted_from_exact_executable_folder():
    project = RasPrj()
    project.initialized = True
    project.ras_version = "7.0.1"
    project.ras_exe_path = (
        r"C:\Program Files (x86)\HEC\HEC-RAS\7.0.1\Ras.exe"
    )

    assert host.resolve_supported_hecras_version(None, project) == "7.0.1"


def test_rasprj_71_is_forward_open_from_exact_executable_folder():
    project = RasPrj()
    project.initialized = True
    project.ras_version = "7.1"
    project.ras_exe_path = r"C:\Program Files (x86)\HEC\HEC-RAS\7.1\Ras.exe"

    assert host.resolve_supported_hecras_version(None, project) == "7.1"


def test_uninitialized_rasprj_is_rejected_even_with_explicit_version():
    with pytest.raises(ValueError, match="initialized RasPrj"):
        host.resolve_supported_hecras_version("6.6", RasPrj())


def test_non_rasprj_project_context_is_rejected():
    with pytest.raises(TypeError, match="RasPrj instance"):
        host.resolve_supported_hecras_version("6.6", object())


def test_resolved_installation_must_match_qualified_release(monkeypatch, tmp_path):
    ras_prj_module = importlib.import_module("ras_commander.RasPrj")
    installation = tmp_path / "7.0"
    installation.mkdir()
    (installation / "Ras.exe").touch()
    (installation / "RasMapperLib.dll").touch()
    monkeypatch.setattr(host.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        ras_prj_module,
        "get_ras_exe",
        lambda _version: str(installation / "Ras.exe"),
    )

    with pytest.raises(ValueError, match="installation '7\\.0' conflicts"):
        host._resolve_hecras_source("6.6", None)


def test_wine_path_conversion_uses_configured_winepath(monkeypatch):
    from ras_commander.RasProcess import RasProcess

    monkeypatch.setattr(host.platform, "system", lambda: "Linux")
    monkeypatch.setattr(RasProcess, "_get_wine_config", staticmethod(lambda: object()))
    monkeypatch.setattr(
        RasProcess,
        "_resolve_wine_tool_executable",
        staticmethod(lambda _tool, _config: "/usr/bin/winepath"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_build_wine_env",
        staticmethod(lambda _config: {"WINEPREFIX": "/task/prefix"}),
    )
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "/mnt/model with spaces/model.prj\n", "")

    monkeypatch.setattr(host.subprocess, "run", fake_run)
    converted = host._normalize_host_path(r"Z:\mnt\model with spaces\model.prj")
    assert converted == Path("/mnt/model with spaces/model.prj")
    assert observed["command"] == [
        "/usr/bin/winepath",
        "-u",
        r"Z:\mnt\model with spaces\model.prj",
    ]
    assert observed["env"]["WINEPREFIX"] == "/task/prefix"


def test_wine_runtime_clones_prefix_unless_explicitly_declared_task_local(
    monkeypatch, tmp_path
):
    from ras_commander.RasProcess import WineConfig

    prefix = tmp_path / "configured-prefix"
    hecras = prefix / "drive_c" / "HEC-RAS" / "6.6"
    stage = tmp_path / "stage"
    stage.mkdir()
    config = WineConfig(prefix, "wine", hecras)
    observed = {}

    def fake_clone(source, destination, timeout):
        observed["clone"] = (source, destination, timeout)
        (destination / "drive_c" / "HEC-RAS" / "6.6").mkdir(parents=True)

    class StopAfterPrefixPreparation(Exception):
        pass

    monkeypatch.setattr(host, "_clone_wine_prefix", fake_clone)
    monkeypatch.setattr(
        host.resources,
        "files",
        lambda _package: (_ for _ in ()).throw(StopAfterPrefixPreparation()),
    )
    with pytest.raises(StopAfterPrefixPreparation):
        host._stage_runtime(stage, hecras, config, 42.0)
    assert observed["clone"] == (prefix, stage / "wineprefix", 42.0)

    stage2 = tmp_path / "stage2"
    stage2.mkdir()
    observed.clear()
    monkeypatch.setenv("RAS_COMMANDER_TERRAIN_WINE_PREFIX_IS_TASK_LOCAL", "1")
    with pytest.raises(StopAfterPrefixPreparation):
        host._stage_runtime(stage2, hecras, config, 42.0)
    assert "clone" not in observed


def test_overwrite_protection_happens_before_project_or_native_work(tmp_path):
    output = tmp_path / "protected.tif"
    output.write_bytes(b"existing")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        RasTerrain.export_rasmapper_terrain("missing.prj", output, hecras_version="6.6")


def test_request_and_response_schema_validation():
    inspect = {
        "schema_version": 1,
        "operation": "inspect",
        "rasmap_path": r"C:\model\a.rasmap",
        "terrain_name": "Terrain",
    }
    host.validate_helper_request(inspect)
    with pytest.raises(ValueError, match="schema"):
        host.validate_helper_request({**inspect, "schema_version": 2})

    response = {
        "schema_version": 1,
        "helper": "RasMapperTerrainExportHelper",
        "success": True,
        "operation": "export",
        "sources": [_source(0, 5.0, 0)],
        "resample_method": "near",
        "resample_to_one_rfi": True,
        "generate_method_is_public": False,
        "new_rfis": [r"C:\output.tif"],
    }
    host.validate_helper_response(response, "export")
    with pytest.raises(RuntimeError, match="nearest"):
        host.validate_helper_response({**response, "resample_method": "average"}, "export")


def test_semantic_validation_enforces_grid_type_crs_nodata_and_no_sidecars(tmp_path):
    tif = tmp_path / "bounded.tif"
    tif.write_bytes(b"TIFF")
    info = {
        "driverShortName": "GTiff",
        "size": [4, 3],
        "geoTransform": [-10.0, 5.0, 0.0, 20.0, 0.0, -5.0],
        "coordinateSystem": {"wkt": "PROJCRS[...]"},
        "bands": [{
            "type": "Float32",
            "noDataValue": -9999.0,
            "computedMin": 1.0,
            "computedMax": 8.0,
            "checksum": 42,
        }],
    }
    validation = host.validate_output_semantics(
        info, tif, (-10.0, 5.0, 10.0, 20.0), 5.0, 4, 3
    )
    assert validation["actual_extent"] == [-10.0, 5.0, 10.0, 20.0]
    Path(str(tif) + ".ovr").write_bytes(b"unexpected")
    with pytest.raises(RuntimeError, match="sidecars"):
        host.validate_output_semantics(
            info, tif, (-10.0, 5.0, 10.0, 20.0), 5.0, 4, 3
        )


def test_operational_failure_cleans_owned_partial_and_stage(monkeypatch, tmp_path):
    rasmap = tmp_path / "project with spaces.rasmap"
    rasmap.write_text("<RASMapper><Terrains/></RASMapper>", encoding="utf-8")
    output = tmp_path / "output with spaces.tif"
    monkeypatch.setattr(
        RasMap,
        "list_terrain_layers",
        staticmethod(lambda *_args, **_kwargs: pd.DataFrame([{
            "name": "Terrain",
            "resolved_path": str(tmp_path / "Terrain.hdf"),
        }])),
    )
    monkeypatch.setattr(
        host,
        "_resolve_hecras_source",
        lambda *_args: ("6.6", tmp_path / "fake-ras", None),
    )
    monkeypatch.setattr(
        host,
        "_stage_runtime",
        lambda stage, *_args: (stage / "helper.exe", tmp_path / "fake-ras", None),
    )
    calls = []

    def fake_helper(_helper, _ras, _config, request, _stage, _timeout):
        calls.append(request["operation"])
        if request["operation"] == "inspect":
            return {
                "schema_version": 1,
                "helper": "RasMapperTerrainExportHelper",
                "success": True,
                "operation": "inspect",
                "terrain_extent": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 20},
                "sources": [_source(0, 5.0, 0, min_x=0, max_y=20)],
            }
        Path(request["output_path"]).write_bytes(b"owned partial")
        raise RuntimeError("forced helper failure")

    monkeypatch.setattr(host, "_run_helper", fake_helper)
    result = host.export_rasmapper_terrain(
        rasmap,
        output,
        terrain_name="Terrain",
        extent=(0, 0, 20, 20),
        hecras_version="6.6",
    )
    assert isinstance(result, TerrainExportResult)
    assert not result
    assert calls == ["inspect", "export"]
    assert not output.exists()
    assert result.receipt_path.is_file()
    assert not list(tmp_path.glob(".*.partial.tif"))
    assert not list(tmp_path.glob(".ras-terrain-export-*"))
    receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert "hash" not in json.dumps(receipt).lower()


@pytest.mark.skipif(platform.system() not in {"Windows", "Linux"}, reason="process groups")
def test_forced_timeout_terminates_only_owned_process_tree(tmp_path):
    psutil = pytest.importorskip("psutil")
    child_pid = tmp_path / "child.pid"
    child_code = (
        "import subprocess,sys,time,pathlib; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        host.run_owned_process(
            [sys.executable, "-c", child_code, str(child_pid)],
            timeout=0.75,
            cwd=tmp_path,
            env=dict(os.environ),
        )
    deadline = time.monotonic() + 5
    while child_pid.exists() and time.monotonic() < deadline:
        pid = int(child_pid.read_text())
        if not psutil.pid_exists(pid):
            break
        time.sleep(0.05)
    assert child_pid.exists()
    assert not psutil.pid_exists(int(child_pid.read_text()))


def test_packaged_helper_resources_are_present():
    package = resources_for_native()
    assert package.joinpath("RasMapperTerrainExportHelper.exe").is_file()
    assert package.joinpath("RasMapperTerrainExportHelper.cs").is_file()


def resources_for_native():
    from importlib import resources

    return resources.files("ras_commander.native")
