from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import inspect
import threading
import time
import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pytest
import rasterio
from affine import Affine


def _terrain_tif(path: Path) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        transform=Affine(10.0, 0.0, 0.0, 0.0, -10.0, 40.0),
        crs="EPSG:2278",
        nodata=-9999.0,
    ) as dst:
        dst.write(np.ones((4, 4), dtype=np.float32), 1)
    return path


def _write_plan_terrain_association(
    path: Path,
    terrain_hdf_name: str,
) -> Path:
    relative = f".\\Terrain\\{terrain_hdf_name}"
    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Terrain Filename"] = relative.encode("utf-8")
        geometry.attrs["Terrain Layername"] = Path(terrain_hdf_name).stem.encode(
            "utf-8"
        )
        area = hdf.create_group("Geometry/2D Flow Areas/Main")
        area.attrs["Terrain Filename"] = relative.encode("utf-8")
    return path


def test_store_maps_benefit_mode_is_depth_only_by_default(monkeypatch, tmp_path):
    from ras_commander.RasBenefits import BenefitAreaConfig
    from ras_commander.RasProcess import RasProcess

    captured = {}

    def fake_store_benefit_area(post_plan_number, config, **kwargs):
        captured.update(
            post_plan_number=post_plan_number,
            config=config,
            **kwargs,
        )
        return {"benefit_area": [tmp_path / "benefit.tif"]}

    monkeypatch.setattr(
        RasProcess,
        "store_benefit_area",
        staticmethod(fake_store_benefit_area),
    )
    config = BenefitAreaConfig(
        pre_plan_number="01",
        terrain_tif=tmp_path / "terrain.tif",
    )

    result = RasProcess.store_maps(plan_number="02", benefit_area=config)

    assert result["benefit_area"] == [tmp_path / "benefit.tif"]
    assert captured["post_plan_number"] == "02"
    assert captured["include_wse"] is False
    assert captured["post_velocity"] is False
    assert captured["post_depth"] is True


def test_store_maps_benefit_mode_honors_optional_wse_and_native_post_map(
    monkeypatch, tmp_path
):
    from ras_commander.RasBenefits import BenefitAreaConfig
    from ras_commander.RasProcess import RasProcess

    captured = {}

    def fake_store_benefit_area(post_plan_number, config, **kwargs):
        captured.update(kwargs)
        return {"benefit_area": []}

    monkeypatch.setattr(
        RasProcess,
        "store_benefit_area",
        staticmethod(fake_store_benefit_area),
    )
    config = BenefitAreaConfig(
        pre_plan_number="01",
        terrain_tif=tmp_path / "terrain.tif",
        include_wse=True,
    )

    RasProcess.store_maps(
        plan_number="02",
        benefit_area=config,
        velocity=True,
    )

    assert captured["include_wse"] is True
    assert captured["post_velocity"] is True


def test_store_maps_benefit_mode_rejects_depth_disabled(tmp_path):
    from ras_commander.RasBenefits import BenefitAreaConfig
    from ras_commander.RasProcess import RasProcess

    config = BenefitAreaConfig("01", tmp_path / "terrain.tif")
    with pytest.raises(ValueError, match="Depth generation cannot be disabled"):
        RasProcess.store_maps(
            plan_number="02",
            benefit_area=config,
            depth=False,
        )


def test_store_maps_benefit_keywords_do_not_shift_legacy_positional_parameters():
    from ras_commander.RasProcess import RasProcess

    parameters = list(inspect.signature(RasProcess.store_maps).parameters)
    assert parameters[17:23] == [
        "clear_existing",
        "fix_georef",
        "ras_object",
        "ras_version",
        "timeout",
        "_log_summary",
    ]
    assert parameters[-2:] == ["terrain_name", "benefit_area"]


def test_store_maps_benefit_mode_rejects_ambiguous_output_folder(tmp_path):
    from ras_commander.RasBenefits import BenefitAreaConfig
    from ras_commander.RasProcess import RasProcess

    config = BenefitAreaConfig("01", tmp_path / "terrain.tif")
    with pytest.raises(ValueError, match="use output_path"):
        RasProcess.store_maps(
            plan_number="02",
            output_folder="legacy-name",
            benefit_area=config,
        )


def test_store_benefit_area_orchestrates_separate_plan_outputs(
    monkeypatch, tmp_path
):
    from ras_commander.RasBenefits import BenefitAreaConfig, BenefitAreaResult, RasBenefits
    from ras_commander.RasProcess import RasProcess

    terrain = _terrain_tif(tmp_path / "terrain.tif")
    calls = []

    def fake_store_maps(plan_number, **kwargs):
        calls.append((plan_number, kwargs))
        output = Path(kwargs["output_path"])
        output.mkdir(parents=True, exist_ok=True)
        depth = output / "Depth (Max).tif"
        depth.touch()
        result = {"depth": [depth]}
        if kwargs["wse"]:
            wse = output / "WSE (Max).tif"
            wse.touch()
            result["wse"] = [wse]
        if kwargs["velocity"]:
            velocity = output / "Velocity (Max).tif"
            velocity.touch()
            result["velocity"] = [velocity]
        return result

    def fake_create(pre_depth, post_depth, terrain_tif, output_tif, **kwargs):
        output_tif = Path(output_tif)
        output_tif.touch()
        polygon = kwargs.get("polygon_output")
        if polygon:
            polygon = Path(polygon)
            polygon.touch()
        return BenefitAreaResult(
            raster_path=output_tif,
            polygon_path=polygon,
            pre_depth_path=Path(pre_depth),
            post_depth_path=Path(post_depth),
            terrain_path=Path(terrain_tif),
            statistics={},
            flood_min_depth=0.05,
            benefit_min_depth=0.25,
            minimum_region_pixels=16,
        )

    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fake_store_maps))
    monkeypatch.setattr(
        RasProcess,
        "_resolve_benefit_terrain_name",
        staticmethod(lambda *args, **kwargs: "Consolidated"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_require_common_benefit_terrain_association",
        staticmethod(lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        RasBenefits,
        "create_benefit_area",
        staticmethod(fake_create),
    )
    ras = SimpleNamespace(
        project_folder=tmp_path,
        project_name="Model",
        check_initialized=lambda: None,
    )
    config = BenefitAreaConfig(
        pre_plan_number="01",
        terrain_tif=terrain,
        polygon_output=True,
    )

    result = RasProcess.store_benefit_area(
        post_plan_number="02",
        config=config,
        output_path=tmp_path / "maps",
        post_velocity=True,
        ras_object=ras,
    )

    assert [call[0] for call in calls] == ["01", "02"]
    assert calls[0][1]["depth"] is True
    assert calls[0][1]["wse"] is False
    assert calls[0][1]["velocity"] is False
    assert calls[1][1]["depth"] is True
    assert calls[1][1]["wse"] is False
    assert calls[1][1]["velocity"] is True
    assert Path(calls[0][1]["output_path"]).name == "p01"
    assert Path(calls[1][1]["output_path"]).name == "p02"
    assert result["benefit_source_pre_depth"][0].parent.name == "p01"
    assert result["benefit_source_post_depth"][0].parent.name == "p02"
    assert result["benefit_area"][0].suffix == ".tif"
    assert result["benefit_area_polygon"][0].suffix == ".gpkg"


def test_store_benefit_area_generates_wse_only_when_requested(monkeypatch, tmp_path):
    from ras_commander.RasBenefits import BenefitAreaConfig, BenefitAreaResult, RasBenefits
    from ras_commander.RasProcess import RasProcess

    terrain = _terrain_tif(tmp_path / "terrain.tif")
    calls = []

    def fake_store_maps(plan_number, **kwargs):
        calls.append(kwargs)
        output = Path(kwargs["output_path"])
        output.mkdir(parents=True, exist_ok=True)
        depth = output / "Depth.tif"
        wse = output / "WSE.tif"
        depth.touch()
        wse.touch()
        return {"depth": [depth], "wse": [wse]}

    def fake_create(pre_depth, post_depth, terrain_tif, output_tif, **kwargs):
        Path(output_tif).touch()
        return BenefitAreaResult(
            Path(output_tif), None, Path(pre_depth), Path(post_depth), Path(terrain_tif),
            {}, 0.05, 0.25, 16,
        )

    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fake_store_maps))
    monkeypatch.setattr(
        RasProcess,
        "_resolve_benefit_terrain_name",
        staticmethod(lambda *args, **kwargs: "Terrain"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_require_common_benefit_terrain_association",
        staticmethod(lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(RasBenefits, "create_benefit_area", staticmethod(fake_create))
    ras = SimpleNamespace(project_folder=tmp_path, check_initialized=lambda: None)

    result = RasProcess.store_benefit_area(
        "02",
        BenefitAreaConfig("01", terrain, include_wse=True),
        output_path=tmp_path / "maps",
        ras_object=ras,
    )

    assert all(call["wse"] is True for call in calls)
    assert "benefit_source_pre_wse" in result
    assert "benefit_source_post_wse" in result


def test_store_benefit_area_validates_requested_wse_before_deriving_output(
    monkeypatch,
    tmp_path,
):
    from ras_commander import BenefitAreaConfig, RasBenefits
    from ras_commander.RasProcess import RasProcess

    terrain = _terrain_tif(tmp_path / "terrain.tif")
    create_called = False

    def fake_store_maps(plan_number, **kwargs):
        output = Path(kwargs["output_path"])
        output.mkdir(parents=True, exist_ok=True)
        result = {"depth": [output / "Depth.tif"]}
        if str(plan_number) == "02":
            result["wse"] = [output / "WSE.tif"]
        return result

    def fail_if_create_is_called(*args, **kwargs):
        nonlocal create_called
        create_called = True
        raise AssertionError("BenefitArea must not be derived without both WSE maps")

    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fake_store_maps))
    monkeypatch.setattr(
        RasProcess,
        "_resolve_benefit_terrain_name",
        staticmethod(lambda *args, **kwargs: "Terrain"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_require_common_benefit_terrain_association",
        staticmethod(lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        RasBenefits,
        "create_benefit_area",
        staticmethod(fail_if_create_is_called),
    )
    ras = SimpleNamespace(project_folder=tmp_path, check_initialized=lambda: None)

    with pytest.raises(RuntimeError, match="exactly one Wse GeoTIFF"):
        RasProcess.store_benefit_area(
            "02",
            BenefitAreaConfig("01", terrain, include_wse=True),
            output_path=tmp_path / "maps",
            ras_object=ras,
        )

    assert create_called is False
    assert not list((tmp_path / "maps").glob("Benefit Area*.tif"))


def test_direct_store_benefit_area_serializes_the_complete_pair_workflow(
    monkeypatch,
    tmp_path,
):
    from ras_commander import BenefitAreaConfig, BenefitAreaResult, RasBenefits
    from ras_commander.RasProcess import RasProcess

    terrain = _terrain_tif(tmp_path / "terrain.tif")
    state_lock = threading.Lock()
    state = {"active": 0, "maximum": 0}

    def fake_store_maps(plan_number, **kwargs):
        output = Path(kwargs["output_path"])
        output.mkdir(parents=True, exist_ok=True)
        depth = output / "Depth.tif"
        depth.touch()
        return {"depth": [depth]}

    def fake_create(pre_depth, post_depth, terrain_tif, output_tif, **kwargs):
        with state_lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        try:
            time.sleep(0.1)
            Path(output_tif).touch()
            return BenefitAreaResult(
                Path(output_tif),
                None,
                Path(pre_depth),
                Path(post_depth),
                Path(terrain_tif),
                {},
                0.05,
                0.25,
                16,
            )
        finally:
            with state_lock:
                state["active"] -= 1

    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fake_store_maps))
    monkeypatch.setattr(
        RasProcess,
        "_resolve_benefit_terrain_name",
        staticmethod(lambda *args, **kwargs: "Terrain"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_require_common_benefit_terrain_association",
        staticmethod(lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        RasBenefits,
        "create_benefit_area",
        staticmethod(fake_create),
    )
    ras = SimpleNamespace(
        project_folder=tmp_path,
        project_name="Model",
        check_initialized=lambda: None,
    )
    config = BenefitAreaConfig("01", terrain)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                RasProcess.store_benefit_area,
                "02",
                config,
                output_path=tmp_path / f"maps_{index}",
                ras_object=ras,
            )
            for index in range(2)
        ]
        results = [future.result() for future in futures]

    assert state["maximum"] == 1
    assert all(result["benefit_area"] for result in results)
    assert not (tmp_path / ".Model.storemaps.lock").exists()


def test_store_benefit_area_requires_exactly_one_depth_per_plan(
    monkeypatch, tmp_path
):
    from ras_commander.RasBenefits import BenefitAreaConfig
    from ras_commander.RasProcess import RasProcess

    terrain = _terrain_tif(tmp_path / "terrain.tif")
    monkeypatch.setattr(
        RasProcess,
        "_resolve_benefit_terrain_name",
        staticmethod(lambda *args, **kwargs: "Terrain"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_require_common_benefit_terrain_association",
        staticmethod(lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        RasProcess,
        "store_maps",
        staticmethod(lambda *args, **kwargs: {"depth": [tmp_path / "a.tif", tmp_path / "b.tif"]}),
    )
    ras = SimpleNamespace(project_folder=tmp_path, check_initialized=lambda: None)

    with pytest.raises(RuntimeError, match="exactly one Depth GeoTIFF"):
        RasProcess.store_benefit_area(
            "02",
            BenefitAreaConfig("01", terrain),
            output_path=tmp_path / "maps",
            ras_object=ras,
        )


def test_select_terrain_for_mapping_is_exclusive_and_case_insensitive(tmp_path):
    from ras_commander.RasProcess import RasProcess

    terrain_dir = tmp_path / "Terrain"
    terrain_dir.mkdir()
    (terrain_dir / "First.hdf").write_bytes(b"hdf")
    (terrain_dir / "Second.hdf").write_bytes(b"hdf")
    rasmap_path = tmp_path / "Demo.rasmap"
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Terrains Checked="True">
    <Layer Name="First" Type="TerrainLayer" Checked="True"
           Filename="./Terrain/First.hdf"><Surface On="True" /></Layer>
    <Layer Name="Second" Type="TerrainLayer" Checked="False"
           Filename="./Terrain/Second.hdf"><Surface On="False" /></Layer>
  </Terrains>
</RASMapper>
""",
        encoding="utf-8",
    )

    RasProcess._select_terrain_for_mapping(rasmap_path, "second")

    layers = ET.parse(rasmap_path).getroot().findall("./Terrains/Layer")
    states = {
        layer.get("Name"): (
            layer.get("Checked"),
            layer.find("Surface").get("On"),
        )
        for layer in layers
    }
    assert states == {
        "First": ("False", "False"),
        "Second": ("True", "True"),
    }


def test_benefit_preflight_allows_multiple_registered_terrains_when_both_plans_match(
    tmp_path,
):
    from ras_commander.RasProcess import RasProcess

    terrain_dir = tmp_path / "Terrain"
    terrain_dir.mkdir()
    common = terrain_dir / "Common.hdf"
    other = terrain_dir / "Other.hdf"
    common.write_bytes(b"common")
    other.write_bytes(b"other")
    (tmp_path / "Model.rasmap").write_text(
        """<RASMapper><Terrains>
<Layer Name="Common" Type="TerrainLayer" Filename=".\\Terrain\\Common.hdf" />
<Layer Name="Other" Type="TerrainLayer" Filename=".\\Terrain\\Other.hdf" />
</Terrains></RASMapper>""",
        encoding="utf-8",
    )
    _write_plan_terrain_association(tmp_path / "Model.p01.hdf", "Common.hdf")
    _write_plan_terrain_association(tmp_path / "Model.p02.hdf", "Common.hdf")
    ras = SimpleNamespace(
        project_folder=tmp_path,
        project_name="Model",
        check_initialized=lambda: None,
    )

    selected = RasProcess._require_common_benefit_terrain_association(
        ras,
        ("01", "02"),
        "Common",
    )

    assert selected == common.resolve()


def test_benefit_preflight_rejects_plan_pinned_to_a_different_terrain(tmp_path):
    from ras_commander.RasProcess import RasProcess

    terrain_dir = tmp_path / "Terrain"
    terrain_dir.mkdir()
    (terrain_dir / "Common.hdf").write_bytes(b"common")
    (terrain_dir / "Other.hdf").write_bytes(b"other")
    (tmp_path / "Model.rasmap").write_text(
        """<RASMapper><Terrains>
<Layer Name="Common" Type="TerrainLayer" Filename=".\\Terrain\\Common.hdf" />
<Layer Name="Other" Type="TerrainLayer" Filename=".\\Terrain\\Other.hdf" />
</Terrains></RASMapper>""",
        encoding="utf-8",
    )
    _write_plan_terrain_association(tmp_path / "Model.p01.hdf", "Common.hdf")
    _write_plan_terrain_association(tmp_path / "Model.p02.hdf", "Other.hdf")
    ras = SimpleNamespace(
        project_folder=tmp_path,
        project_name="Model",
        check_initialized=lambda: None,
    )

    with pytest.raises(ValueError, match="Plan p02 records") as exc_info:
        RasProcess._require_common_benefit_terrain_association(
            ras,
            ("01", "02"),
            "Common",
        )

    message = str(exc_info.value)
    assert "same registered single-TIFF terrain" in message
    assert "terrain visibility alone does not override" in message
    assert "RasMap.associate_geometry_layers" in message
