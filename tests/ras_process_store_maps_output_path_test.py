from importlib import import_module
from pathlib import Path
import subprocess


ras_process_module = import_module("ras_commander.RasProcess")
RasProcess = ras_process_module.RasProcess


class _DummyRas:
    def __init__(self, project_folder: Path, project_name: str = "Demo"):
        self.project_folder = project_folder
        self.project_name = project_name
        self.ras_exe_path = project_folder / "hecras" / "Ras.exe"

    def check_initialized(self):
        return None


def test_store_maps_moves_overwritten_outputs_to_custom_path(monkeypatch, tmp_path):
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


def test_store_maps_at_timesteps_routes_each_timestamp(monkeypatch, tmp_path):
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
