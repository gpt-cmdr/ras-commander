from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from importlib import import_module
import logging
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import h5py
import pytest


ras_process_module = import_module("ras_commander.RasProcess")
RasProcess = ras_process_module.RasProcess
LOGGER_NAME = "ras_commander.RasProcess"


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


def test_add_stored_map_creates_checked_expanded_results_plan_layer(tmp_path):
    rasmap_path = tmp_path / "Demo.rasmap"
    rasmap_path.write_text("<RASMapper><Results /></RASMapper>", encoding="utf-8")

    assert RasProcess._add_stored_map_to_rasmap(
        rasmap_path,
        "Demo.p01.hdf",
        "depth",
        "Max",
        "PipePumpUpgrade",
    )

    root = ET.parse(rasmap_path).getroot()
    plan_layer = root.find("./Results/Layer[@Type='RASResults']")

    assert plan_layer is not None
    assert plan_layer.get("Name") == "PipePumpUpgrade"
    assert plan_layer.get("Filename") == r".\Demo.p01.hdf"
    assert plan_layer.get("Checked") == "True"
    assert plan_layer.get("Expanded") == "True"

    map_layer = plan_layer.find("./Layer[@Type='RASResultsMap']")
    assert map_layer is not None
    assert map_layer.get("Name") == "Depth"

    params = map_layer.find("MapParameters")
    assert params is not None
    assert params.get("MapType") == "depth"
    assert params.get("OutputMode") == "Stored Current Terrain"
    assert params.get("StoredFilename") == r".\PipePumpUpgrade\Depth (Max).vrt"


def test_mapper_compatible_hdf_normalizes_temporary_copy_and_restores_source(
    tmp_path,
):
    hdf_path = tmp_path / "Demo.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Geometry Time"] = b"15Jul2026 19:33:14"
        flow_area = geometry.create_group("2D Flow Areas/area2")
        flow_area.attrs["Data Date"] = b"15Jul2026 19:33:21"
        flow_area.create_dataset("Cells Minimum Elevation", data=[1.0, 2.0])
        pipe_network = geometry.create_group("Pipe Networks/Network")
        pipe_network.create_dataset("Cell Property Table", data=[3.0])
        pump_stations = geometry.create_group("Pump Stations")
        pump_stations.create_dataset("Attributes", data=[4.0])

    original_bytes = hdf_path.read_bytes()
    with RasProcess._mapper_compatible_result_hdf(hdf_path, "7.0") as mapped:
        assert mapped == hdf_path
        assert hdf_path.read_bytes() != original_bytes
        with h5py.File(hdf_path, "r") as hdf:
            geometry_time = hdf["Geometry"].attrs["Geometry Time"]
            data_date = hdf["Geometry/2D Flow Areas/area2"].attrs["Data Date"]
            if isinstance(geometry_time, bytes):
                geometry_time = geometry_time.decode()
            if isinstance(data_date, bytes):
                data_date = data_date.decode()
            assert geometry_time == "15Jul2026 07:33:14"
            assert (
                data_date
                == "15Jul2026 07:33:21"
            )

    assert hdf_path.read_bytes() == original_bytes
    assert not list(tmp_path.glob(".Demo.p01.hdf.*.mapper-*"))


def test_mapper_compatible_hdf_leaves_morning_geometry_unchanged(tmp_path):
    hdf_path = tmp_path / "Demo.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Geometry Time"] = b"15Jul2026 06:17:31"
        geometry.create_dataset("Attributes", data=[1.0])

    original_bytes = hdf_path.read_bytes()
    with RasProcess._mapper_compatible_result_hdf(hdf_path, "7.0"):
        assert hdf_path.read_bytes() == original_bytes
    assert hdf_path.read_bytes() == original_bytes


def test_windows_extended_length_path_conversion_is_cross_platform(monkeypatch):
    monkeypatch.setattr(ras_process_module, "IS_WINDOWS", True)

    drive_path = r"C:\projects\Demo\PlanShort\Depth (Max).tif"
    unc_path = r"\\server\share\Demo\PlanShort\Depth (Max).tif"
    prefixed_drive_path = r"\\?\C:\projects\Demo\PlanShort\Depth (Max).tif"
    prefixed_unc_path = r"\\?\UNC\server\share\Demo\PlanShort\Depth (Max).tif"

    assert ras_process_module._windows_extended_length_path(drive_path) == (
        r"\\?\C:\projects\Demo\PlanShort\Depth (Max).tif"
    )
    assert ras_process_module._windows_extended_length_path(unc_path) == (
        r"\\?\UNC\server\share\Demo\PlanShort\Depth (Max).tif"
    )
    assert (
        ras_process_module._windows_extended_length_path(prefixed_drive_path)
        == prefixed_drive_path
    )
    assert (
        ras_process_module._windows_extended_length_path(prefixed_unc_path)
        == prefixed_unc_path
    )

    monkeypatch.setattr(ras_process_module, "IS_WINDOWS", False)
    assert ras_process_module._windows_extended_length_path(unc_path) == unc_path


@pytest.mark.parametrize(
    ("directory", "expected_scan_path"),
    [
        (
            r"C:\projects\Demo\PlanShort",
            r"\\?\C:\projects\Demo\PlanShort",
        ),
        (
            r"\\server\share\Demo\PlanShort",
            r"\\?\UNC\server\share\Demo\PlanShort",
        ),
    ],
)
def test_glob_paths_scans_with_extended_length_drive_and_unc_paths(
    monkeypatch,
    directory,
    expected_scan_path,
):
    scanned_paths = []

    def fake_scandir(path):
        scanned_paths.append(path)
        return nullcontext(
            [
                SimpleNamespace(name="WSE (Max).Terrain.tif"),
                SimpleNamespace(name="Depth (Max).Terrain B.tif"),
                SimpleNamespace(name="Depth (Max).Terrain A.tif"),
            ]
        )

    monkeypatch.setattr(ras_process_module, "IS_WINDOWS", True)
    monkeypatch.setattr(ras_process_module.os, "scandir", fake_scandir)

    matches = ras_process_module._glob_paths(directory, "Depth (Max)*.tif")

    assert scanned_paths == [expected_scan_path]
    assert [path.name for path in matches] == [
        "Depth (Max).Terrain A.tif",
        "Depth (Max).Terrain B.tif",
    ]


class _DummyRas:
    def __init__(self, project_folder: Path, project_name: str = "Demo"):
        self.project_folder = project_folder
        self.project_name = project_name
        self.ras_exe_path = project_folder / "hecras" / "Ras.exe"

    def check_initialized(self):
        return None


def _configure_store_maps_test(monkeypatch, tmp_path):
    """Create the minimum real-file layout needed by ``store_maps``."""
    project_name = "Demo"
    output_dir = tmp_path / "PlanShort"
    custom_output_dir = tmp_path / "custom_maps"
    rasmap_path = tmp_path / f"{project_name}.rasmap"
    plan_hdf_path = tmp_path / f"{project_name}.p01.hdf"

    (tmp_path / "hecras").mkdir()
    (tmp_path / "hecras" / "Ras.exe").write_text("", encoding="utf-8")
    output_dir.mkdir()
    custom_output_dir.mkdir()
    plan_hdf_path.write_text("", encoding="utf-8")
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Results>
    <Layer Name="PlanShort" Filename="Demo.p01.hdf" />
  </Results>
</RASMapper>
""",
        encoding="utf-8",
    )

    ras_obj = _DummyRas(project_folder=tmp_path, project_name=project_name)
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_rasmap_path",
        staticmethod(lambda ras_object=None: rasmap_path),
    )
    monkeypatch.setattr(
        RasProcess,
        "_get_plan_short_id",
        staticmethod(lambda hdf_path: "PlanShort"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_remove_stored_maps_from_rasmap",
        staticmethod(lambda *args, **kwargs: 0),
    )
    monkeypatch.setattr(
        RasProcess,
        "_add_stored_map_to_rasmap",
        staticmethod(lambda *args, **kwargs: True),
    )
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_water_surface_render_mode",
        staticmethod(lambda ras_object=None: "horizontal"),
    )
    return ras_obj, output_dir, custom_output_dir


def test_store_maps_raises_on_helper_failure_instead_of_returning_stale_output(
    monkeypatch,
    tmp_path,
):
    ras_obj, output_dir, custom_output_dir = _configure_store_maps_test(
        monkeypatch,
        tmp_path,
    )
    stale_default = output_dir / "Depth (Max).tif"
    stale_custom = custom_output_dir / "Depth (Max).tif"
    stale_default.write_text("old-default", encoding="utf-8")
    stale_custom.write_text("old-custom", encoding="utf-8")

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        lambda **kwargs: subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=9,
            stdout="",
            stderr="renderer failed\nextra diagnostic",
        ),
    )

    with pytest.raises(
        RuntimeError,
        match=r"StoreAllMaps failed for plan 01 \(exit code 9\): renderer failed",
    ):
        RasProcess.store_maps(
            plan_number="01",
            output_path=custom_output_dir,
            profile="Max",
            wse=False,
            depth=True,
            velocity=False,
            fix_georef=False,
            ras_object=ras_obj,
        )

    assert stale_default.read_text(encoding="utf-8") == "old-default"
    assert stale_custom.read_text(encoding="utf-8") == "old-custom"


def test_store_maps_success_without_fresh_output_does_not_return_stale_file(
    monkeypatch,
    tmp_path,
):
    ras_obj, output_dir, custom_output_dir = _configure_store_maps_test(
        monkeypatch,
        tmp_path,
    )
    (output_dir / "Depth (Max).tif").write_text("old-default", encoding="utf-8")
    stale_custom = custom_output_dir / "Depth (Max).tif"
    stale_custom.write_text("old-custom", encoding="utf-8")

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        lambda **kwargs: subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=0,
            stdout="Maps generated: 0",
            stderr="",
        ),
    )

    result = RasProcess.store_maps(
        plan_number="01",
        output_path=custom_output_dir,
        profile="Max",
        wse=False,
        depth=True,
        velocity=False,
        fix_georef=False,
        ras_object=ras_obj,
    )

    assert result == {}
    assert stale_custom.read_text(encoding="utf-8") == "old-custom"


def test_store_maps_serializes_concurrent_calls_for_same_project(
    monkeypatch,
    tmp_path,
):
    ras_obj, output_dir, first_output = _configure_store_maps_test(
        monkeypatch,
        tmp_path,
    )
    second_output = tmp_path / "custom_maps_2"
    state_lock = threading.Lock()
    state = {"active": 0, "maximum": 0, "calls": 0}

    def fake_run_store_all_maps_helper(**kwargs):
        with state_lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            state["calls"] += 1
            call_number = state["calls"]
        try:
            time.sleep(0.1)
            (output_dir / "Depth (Max).tif").write_text(
                f"depth-{call_number}",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                args=["RasStoreMapHelper.exe"],
                returncode=0,
                stdout="Maps generated: 1",
                stderr="",
            )
        finally:
            with state_lock:
                state["active"] -= 1

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        fake_run_store_all_maps_helper,
    )

    def run(output_path):
        return RasProcess.store_maps(
            plan_number="01",
            output_path=output_path,
            profile="Max",
            wse=False,
            depth=True,
            velocity=False,
            fix_georef=False,
            ras_object=ras_obj,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run, first_output),
            executor.submit(run, second_output),
        ]
        results = [future.result() for future in futures]

    assert state["maximum"] == 1
    assert results[0]["depth"] == [first_output / "Depth (Max).tif"]
    assert results[1]["depth"] == [second_output / "Depth (Max).tif"]
    assert not (tmp_path / ".Demo.storemaps.lock").exists()
    assert not list(tmp_path.glob(".*.rasmap.*.bak"))


def test_store_maps_moves_overwritten_outputs_to_custom_path(monkeypatch, tmp_path, caplog):
    project_folder = tmp_path
    project_name = "Demo"
    output_dir = project_folder / "PlanShort"
    custom_output_dir = project_folder / "custom_maps"
    rasmap_path = project_folder / f"{project_name}.rasmap"
    plan_hdf_path = project_folder / f"{project_name}.p01.hdf"

    (project_folder / "hecras").mkdir()
    (project_folder / "hecras" / "Ras.exe").write_text("", encoding="utf-8")
    plan_hdf_path.write_text("", encoding="utf-8")
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Results>
    <Layer Name="PlanShort" Filename="Demo.p01.hdf" />
  </Results>
</RASMapper>
""",
        encoding="utf-8",
    )

    output_dir.mkdir()
    (output_dir / "WSE (Max).tif").write_text("old", encoding="utf-8")

    ras_obj = _DummyRas(project_folder=project_folder, project_name=project_name)

    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_rasmap_path",
        staticmethod(lambda ras_object=None: rasmap_path),
    )
    monkeypatch.setattr(
        RasProcess,
        "_get_plan_short_id",
        staticmethod(lambda hdf_path: "PlanShort"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_remove_stored_maps_from_rasmap",
        staticmethod(lambda *args, **kwargs: 0),
    )
    monkeypatch.setattr(
        RasProcess,
        "_add_stored_map_to_rasmap",
        staticmethod(lambda *args, **kwargs: True),
    )
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_water_surface_render_mode",
        staticmethod(lambda ras_object=None: "horizontal"),
    )

    def fake_run_store_all_maps_helper(**kwargs):
        (output_dir / "WSE (Max).tif").write_text("newer", encoding="utf-8")
        (output_dir / "Depth (Max).tif").write_text("depth-map", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=0,
            stdout="Maps generated: 2",
            stderr="",
        )

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        fake_run_store_all_maps_helper,
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        results = RasProcess.store_maps(
            plan_number="01",
            output_path=custom_output_dir,
            profile="Max",
            wse=True,
            depth=True,
            velocity=False,
            clear_existing=True,
            fix_georef=False,
            ras_object=ras_obj,
        )

    assert results["wse"] == [custom_output_dir / "WSE (Max).tif"]
    assert results["depth"] == [custom_output_dir / "Depth (Max).tif"]
    assert (custom_output_dir / "WSE (Max).tif").read_text(
        encoding="utf-8"
    ) == "newer"
    assert (custom_output_dir / "Depth (Max).tif").read_text(
        encoding="utf-8"
    ) == "depth-map"
    assert not (output_dir / "WSE (Max).tif").exists()
    assert not (output_dir / "Depth (Max).tif").exists()
    info_messages = _messages(caplog, logging.INFO)
    assert info_messages == [
        "StoreAllMaps complete: plan=01; mode=horizontal; map_types=2; files=2"
    ]
    assert not any(str(tmp_path) in message for message in info_messages)


def test_store_maps_leaves_unchanged_files_in_default_folder(monkeypatch, tmp_path):
    project_folder = tmp_path
    project_name = "Demo"
    output_dir = project_folder / "PlanShort"
    custom_output_dir = project_folder / "custom_maps"
    rasmap_path = project_folder / f"{project_name}.rasmap"
    plan_hdf_path = project_folder / f"{project_name}.p01.hdf"

    (project_folder / "hecras").mkdir()
    (project_folder / "hecras" / "Ras.exe").write_text("", encoding="utf-8")
    plan_hdf_path.write_text("", encoding="utf-8")
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Results>
    <Layer Name="PlanShort" Filename="Demo.p01.hdf" />
  </Results>
</RASMapper>
""",
        encoding="utf-8",
    )

    output_dir.mkdir()
    benchmark_path = output_dir / "manual_benchmark.tif"
    benchmark_path.write_text("keep-me", encoding="utf-8")

    ras_obj = _DummyRas(project_folder=project_folder, project_name=project_name)

    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_rasmap_path",
        staticmethod(lambda ras_object=None: rasmap_path),
    )
    monkeypatch.setattr(
        RasProcess,
        "_get_plan_short_id",
        staticmethod(lambda hdf_path: "PlanShort"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_remove_stored_maps_from_rasmap",
        staticmethod(lambda *args, **kwargs: 0),
    )
    monkeypatch.setattr(
        RasProcess,
        "_add_stored_map_to_rasmap",
        staticmethod(lambda *args, **kwargs: True),
    )
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_water_surface_render_mode",
        staticmethod(lambda ras_object=None: "horizontal"),
    )

    def fake_run_store_all_maps_helper(**kwargs):
        (output_dir / "Depth (Max).tif").write_text("depth-map", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=0,
            stdout="Maps generated: 1",
            stderr="",
        )

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        fake_run_store_all_maps_helper,
    )

    results = RasProcess.store_maps(
        plan_number="01",
        output_path=custom_output_dir,
        profile="Max",
        wse=False,
        depth=True,
        velocity=False,
        clear_existing=True,
        fix_georef=False,
        ras_object=ras_obj,
    )

    assert results["depth"] == [custom_output_dir / "Depth (Max).tif"]
    assert benchmark_path.exists()
    assert benchmark_path.read_text(encoding="utf-8") == "keep-me"
    assert not (custom_output_dir / "manual_benchmark.tif").exists()


def test_store_maps_at_timesteps_routes_each_timestamp(monkeypatch, tmp_path, caplog):
    ras_obj = _DummyRas(project_folder=tmp_path)
    available = [
        "04FEB2024 00:00:00",
        "04FEB2024 01:00:00",
        "04FEB2024 02:00:00",
    ]
    calls = []

    monkeypatch.setattr(
        RasProcess,
        "get_plan_timestamps",
        staticmethod(lambda plan_number, ras_object=None: available),
    )

    def fake_store_maps(**kwargs):
        calls.append(kwargs)
        return {"depth": [tmp_path / f"{kwargs['profile']}.tif"]}

    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fake_store_maps))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        results = RasProcess.store_maps_at_timesteps(
            plan_number="02",
            output_path=tmp_path / "depth_frames",
            timesteps=[0, "2024-02-04 02:00"],
            depth=True,
            velocity=False,
            fix_georef=False,
            ras_object=ras_obj,
        )

    assert list(results) == ["04FEB2024 00:00:00", "04FEB2024 02:00:00"]
    assert [call["profile"] for call in calls] == list(results)
    assert all(call["plan_number"] == "02" for call in calls)
    assert all(call["depth"] is True and call["velocity"] is False for call in calls)
    assert all(call["_log_summary"] is False for call in calls)
    info_messages = _messages(caplog, logging.INFO)
    assert info_messages == [
        "StoreAllMaps timesteps complete: plan=02; timesteps=2; map_types=1; files=2"
    ]
    assert not any(str(tmp_path) in message for message in info_messages)


def test_add_stored_map_rasmap_setup_logs_debug_not_info(tmp_path, caplog):
    rasmap_path = tmp_path / "Demo.rasmap"
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Geometries />
</RASMapper>
""",
        encoding="utf-8",
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert RasProcess._add_stored_map_to_rasmap(
            rasmap_path=rasmap_path,
            plan_hdf_filename="Demo.p01.hdf",
            map_type="depth",
            profile_name="Max",
            output_folder="PlanShort",
        )

    assert _messages(caplog, logging.INFO) == []

    caplog.clear()
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Geometries />
</RASMapper>
""",
        encoding="utf-8",
    )
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        assert RasProcess._add_stored_map_to_rasmap(
            rasmap_path=rasmap_path,
            plan_hdf_filename="Demo.p01.hdf",
            map_type="depth",
            profile_name="Max",
            output_folder="PlanShort",
        )

    debug_messages = _messages(caplog, logging.DEBUG)
    assert any("Created Results element in rasmap" in message for message in debug_messages)
    assert any("Created plan layer 'PlanShort' in rasmap" in message for message in debug_messages)


def test_projection_info_discovers_all_tiffs_associated_with_terrain_hdf(tmp_path):
    terrain_dir = tmp_path / "Terrain"
    terrain_dir.mkdir()
    terrain_hdf = terrain_dir / "Composite Terrain.hdf"
    terrain_hdf.write_bytes(b"")
    expected_paths = (
        terrain_dir / "Composite Terrain.East.tif",
        terrain_dir / "Composite Terrain.West.tif",
    )
    for terrain_path in reversed(expected_paths):
        terrain_path.write_bytes(b"")
    (terrain_dir / "Unrelated Terrain.tif").write_bytes(b"")

    rasmap_path = tmp_path / "Demo.rasmap"
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Terrains>
    <Layer Name="Composite Terrain" Filename="./Terrain/Composite Terrain.hdf" />
  </Terrains>
</RASMapper>
""",
        encoding="utf-8",
    )

    projection_info = RasProcess._get_projection_info(rasmap_path)

    assert projection_info.terrain_path == expected_paths[0]
    assert projection_info.terrain_paths == expected_paths


def test_projection_info_ignores_explicitly_unchecked_terrain_layers(tmp_path):
    terrain_dir = tmp_path / "Terrain"
    terrain_dir.mkdir()
    active_hdf = terrain_dir / "Active.hdf"
    inactive_hdf = terrain_dir / "Inactive.hdf"
    active_hdf.write_bytes(b"")
    inactive_hdf.write_bytes(b"")
    active_tif = terrain_dir / "Active.Source.tif"
    inactive_tif = terrain_dir / "Inactive.Source.tif"
    active_tif.write_bytes(b"")
    inactive_tif.write_bytes(b"")
    rasmap_path = tmp_path / "Demo.rasmap"
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Terrains>
    <Layer Name="Active" Type="TerrainLayer" Checked="True"
           Filename="./Terrain/Active.hdf"><Surface On="True" /></Layer>
    <Layer Name="Inactive" Type="TerrainLayer" Checked="False"
           Filename="./Terrain/Inactive.hdf"><Surface On="False" /></Layer>
  </Terrains>
</RASMapper>
""",
        encoding="utf-8",
    )

    projection_info = RasProcess._get_projection_info(rasmap_path)

    assert projection_info.terrain_path == active_tif
    assert projection_info.terrain_paths == (active_tif,)


def test_terrain_for_stored_map_matches_each_stem_and_rejects_unmatched(tmp_path):
    east_terrain = tmp_path / "Composite Terrain.East.tif"
    west_terrain = tmp_path / "Composite Terrain.West.tif"
    terrain_paths = (east_terrain, west_terrain)

    assert RasProcess._terrain_for_stored_map(
        tmp_path / "Depth (Max).Composite Terrain.East.tif",
        terrain_paths,
    ) == east_terrain
    assert RasProcess._terrain_for_stored_map(
        tmp_path / "Depth (Max).Composite Terrain.West.tif",
        terrain_paths,
    ) == west_terrain
    assert (
        RasProcess._terrain_for_stored_map(
            tmp_path / "Depth (Max).Unknown Terrain.tif",
            terrain_paths,
        )
        is None
    )


def test_store_maps_applies_each_terrain_transform_to_its_output_tile(
    monkeypatch,
    tmp_path,
):
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    from rasterio.crs import CRS
    from rasterio.transform import from_origin

    output_dir = tmp_path / "PlanShort"
    terrain_dir = tmp_path / "Terrain"
    terrain_dir.mkdir()
    (tmp_path / "hecras").mkdir()
    (tmp_path / "hecras" / "Ras.exe").write_bytes(b"")
    (tmp_path / "Demo.p01.hdf").write_bytes(b"")
    (terrain_dir / "Composite Terrain.hdf").write_bytes(b"")

    rasmap_path = tmp_path / "Demo.rasmap"
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Terrains>
    <Layer Name="Composite Terrain" Filename="./Terrain/Composite Terrain.hdf" />
  </Terrains>
  <Results>
    <Layer Name="PlanShort" Filename="Demo.p01.hdf" />
  </Results>
</RASMapper>
""",
        encoding="utf-8",
    )

    terrain_transforms = {
        "East": from_origin(1000, 2000, 10, 10),
        "West": from_origin(5000, 8000, 25, 25),
    }
    crs = CRS.from_epsg(2871)
    data = np.arange(9, dtype="float32").reshape(3, 3)
    for tile_name, transform in terrain_transforms.items():
        terrain_path = terrain_dir / f"Composite Terrain.{tile_name}.tif"
        with rasterio.open(
            terrain_path,
            "w",
            driver="GTiff",
            height=3,
            width=3,
            count=1,
            dtype="float32",
            crs=crs,
            transform=transform,
        ) as dst:
            dst.write(data, 1)

    ras_obj = _DummyRas(project_folder=tmp_path)
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_rasmap_path",
        staticmethod(lambda ras_object=None: rasmap_path),
    )
    monkeypatch.setattr(
        RasProcess,
        "_get_plan_short_id",
        staticmethod(lambda hdf_path: "PlanShort"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_remove_stored_maps_from_rasmap",
        staticmethod(lambda *args, **kwargs: 0),
    )
    monkeypatch.setattr(
        RasProcess,
        "_add_stored_map_to_rasmap",
        staticmethod(lambda *args, **kwargs: True),
    )
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_water_surface_render_mode",
        staticmethod(lambda ras_object=None: "horizontal"),
    )

    raw_transform = from_origin(10, 20, 1, 1)

    def fake_run_store_all_maps_helper(**kwargs):
        for tile_name in terrain_transforms:
            output_path = output_dir / f"Depth (Max).Composite Terrain.{tile_name}.tif"
            with rasterio.open(
                output_path,
                "w",
                driver="GTiff",
                height=3,
                width=3,
                count=1,
                dtype="float32",
                transform=raw_transform,
            ) as dst:
                dst.write(data, 1)
        return subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=0,
            stdout="Maps generated: 2",
            stderr="",
        )

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        fake_run_store_all_maps_helper,
    )

    results = RasProcess.store_maps(
        plan_number="01",
        profile="Max",
        wse=False,
        depth=True,
        velocity=False,
        clear_existing=True,
        fix_georef=True,
        ras_object=ras_obj,
    )

    expected_outputs = [
        output_dir / f"Depth (Max).Composite Terrain.{tile_name}.tif"
        for tile_name in terrain_transforms
    ]
    assert results["depth"] == expected_outputs
    for tile_name, output_path in zip(terrain_transforms, expected_outputs):
        with rasterio.open(output_path) as src:
            assert src.crs == crs
            assert src.transform == terrain_transforms[tile_name]


def test_fix_georeferencing_rewrites_compressed_tiff(tmp_path):
    rasterio = __import__("pytest").importorskip("rasterio")
    np = __import__("pytest").importorskip("numpy")
    from rasterio.crs import CRS
    from rasterio.transform import from_origin

    terrain_path = tmp_path / "terrain.tif"
    depth_path = tmp_path / "depth.tif"
    terrain_transform = from_origin(1000, 2000, 10, 10)
    raw_transform = from_origin(0, 0, 1, 1)
    data = np.arange(9, dtype="float32").reshape(3, 3)

    terrain_profile = {
        "driver": "GTiff",
        "height": 3,
        "width": 3,
        "count": 1,
        "dtype": "float32",
        "crs": CRS.from_epsg(2871),
        "transform": terrain_transform,
    }
    with rasterio.open(terrain_path, "w", **terrain_profile) as dst:
        dst.write(data, 1)

    depth_profile = dict(terrain_profile)
    depth_profile.update(
        crs=None,
        transform=raw_transform,
        compress="deflate",
        tiled=True,
        blockxsize=16,
        blockysize=16,
        nodata=-9999.0,
    )
    with rasterio.open(depth_path, "w", **depth_profile) as dst:
        dst.write(data, 1)

    assert RasProcess._fix_georeferencing(depth_path, None, terrain_path)

    with rasterio.open(depth_path) as src:
        assert src.crs == CRS.from_epsg(2871)
        assert src.transform == terrain_transform
        assert np.array_equal(src.read(1), data)


def test_drop_unreadable_tifs_removes_corrupt_stored_map(tmp_path):
    pytest = __import__("pytest")
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    from rasterio.transform import from_origin

    valid_path = tmp_path / "Depth (04FEB2024 00 00 00).tif"
    corrupt_path = tmp_path / "Depth (04FEB2024 01 00 00).tif"

    with rasterio.open(
        valid_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        transform=from_origin(1000, 2000, 10, 10),
    ) as dst:
        dst.write(np.ones((2, 2), dtype="float32"), 1)

    corrupt_path.write_bytes(b"not a readable tiff")

    results = RasProcess._drop_unreadable_tifs(
        {"depth": [valid_path, corrupt_path]}
    )

    assert results["depth"] == [valid_path]
    assert valid_path.exists()
    assert not corrupt_path.exists()


def test_drop_unreadable_tifs_preserves_vector_outputs(tmp_path):
    boundary = tmp_path / "Inundation Boundary.shp"
    boundary.write_bytes(b"vector-output")

    results = RasProcess._drop_unreadable_tifs(
        {"inundation_boundary": [boundary]}
    )

    assert results["inundation_boundary"] == [boundary]
    assert boundary.read_bytes() == b"vector-output"
