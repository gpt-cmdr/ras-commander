from contextlib import nullcontext
from importlib import import_module
import logging
from pathlib import Path
import subprocess
from types import SimpleNamespace

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
