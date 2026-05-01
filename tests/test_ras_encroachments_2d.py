import math
import xml.etree.ElementTree as ET
from pathlib import Path

import h5py
import numpy as np

from ras_commander import RasEncroachments, RasMap, RasPrj, init_ras_project


def _make_2d_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "Floodway2D"
    project_dir.mkdir()
    (project_dir / "Floodway2D.prj").write_text(
        (
            "Proj Title=Floodway 2D\n"
            "Current Plan=p02\n"
            "Plan File=p01\n"
            "Plan Title=Base Plan\n"
            "Plan File=p02\n"
            "Plan Title=Encroach Plan\n"
            "Geom File=g01\n"
            "Unsteady File=u01\n"
        ),
        encoding="utf-8",
    )
    (project_dir / "Floodway2D.p01").write_text(
        (
            "Plan Title=Base Plan\n"
            "Program Version=6.60\n"
            "Short Identifier=Base\n"
            "Geom File=g01\n"
            "Flow File=u01\n"
            "Computation Interval=1MIN\n"
            "Mapping Interval=1HOUR\n"
        ),
        encoding="utf-8",
    )
    (project_dir / "Floodway2D.p02").write_text(
        (
            "Plan Title=Encroach Plan\n"
            "Program Version=6.60\n"
            "Short Identifier=Encroach\n"
            "Geom File=g01\n"
            "Flow File=u01\n"
            "Computation Interval=1MIN\n"
            "Mapping Interval=1HOUR\n"
        ),
        encoding="utf-8",
    )
    (project_dir / "Floodway2D.g01").write_text("Geom Title=Geometry\n", encoding="utf-8")
    (project_dir / "Floodway2D.u01").write_text("Flow Title=Unsteady\n", encoding="utf-8")
    (project_dir / "Floodway2D.g01.hdf").write_bytes(b"")
    (project_dir / "Floodway2D.rasmap").write_text(
        (
            "<RASMapper>\n"
            "  <Results Checked=\"True\">\n"
            "    <Layer Name=\"Encroach\" Type=\"RASResults\" Checked=\"True\" "
            "Filename=\".\\Floodway2D.p02.hdf\" />\n"
            "  </Results>\n"
            "  <Terrains Checked=\"True\">\n"
            "    <Layer Name=\"USGSTerrain\" Type=\"TerrainLayer\" "
            "Filename=\".\\Terrain\\USGSTerrain.hdf\" />\n"
            "  </Terrains>\n"
            "</RASMapper>\n"
        ),
        encoding="utf-8",
    )
    return project_dir


def test_2d_encroachment_regions_zones_and_settings_round_trip(tmp_path):
    project_dir = _make_2d_project(tmp_path)
    base_plan = project_dir / "Floodway2D.p01"
    encroach_plan = project_dir / "Floodway2D.p02"

    settings = RasEncroachments.set_2d_encroachment_plan_settings(
        encroach_plan,
        base_plan=base_plan,
        target_rise=1.0,
        fill_slope=0.001,
        additional_fill=0.25,
    )
    regions = RasEncroachments.set_2d_encroachment_regions(
        encroach_plan,
        [
            {
                "name": "Left Fill",
                "polygon": [(0, 0), (10, 0), (10, 5), (0, 5)],
                "fill_slope": 0.001,
                "additional_fill_rise": 0.5,
            },
            {
                "name": "Multipart Fill",
                "parts": [
                    [(20, 0), (25, 0), (25, 5), (20, 5)],
                    [(30, 0), (35, 0), (35, 5), (30, 5)],
                ],
            },
        ],
    )
    zones = RasEncroachments.set_2d_encroachment_zones(
        encroach_plan,
        [
            {
                "name": "Zone A",
                "polygon": [(1, 1), (4, 1), (4, 4), (1, 4)],
                "value": 1.25,
            }
        ],
    )

    gis_hdf = project_dir / "Floodway2D.p02.GIS.hdf"
    assert gis_hdf.exists()
    assert settings["base_plan_filename"] == r".\Floodway2D.p01"
    assert settings["maximum_target_rise"] == 1.0
    assert np.isclose(settings["fill_slope"], 0.001)
    assert np.isclose(settings["additional_fill"], 0.25)

    assert list(regions["name"]) == ["Left Fill", "Multipart Fill"]
    assert regions.loc[0, "polygon"][0] == [0.0, 0.0]
    assert regions.loc[0, "polygon"][-1] == [0.0, 0.0]
    assert regions.loc[1, "part_count"] == 2
    assert math.isnan(regions.loc[1, "fill_slope"])
    assert list(zones["name"]) == ["Zone A"]
    assert np.isclose(zones.loc[0, "value"], 1.25)

    with h5py.File(gis_hdf, "r") as hdf:
        encroachments = hdf["Plan Data/Encroachments"]
        assert encroachments.attrs["Base Plan Filename"] == r".\Floodway2D.p01"
        assert float(encroachments.attrs["Maximum Target Rise"]) == 1.0
        assert np.isclose(float(encroachments.attrs["Fill Slope"]), 0.001)
        assert np.isclose(float(encroachments.attrs["Additional Fill"]), 0.25)

        region_group = hdf["Plan Data/Encroachments/Regions"]
        assert region_group["Attributes"].dtype.names == (
            "Name",
            "Fill Slope",
            "Additional Fill Rise",
        )
        assert region_group["Polygon Info"].shape == (2, 4)
        assert region_group["Polygon Parts"].shape == (3, 2)
        assert region_group["Polygon Points"].shape == (15, 2)
        assert region_group["Polygon Info"].attrs["Feature Type"] == b"Polygon"

        zone_group = hdf["Plan Data/Encroachments/Zones"]
        assert zone_group["Attributes"].dtype.names == ("Name", "Value")
        assert zone_group["Polygon Info"].shape == (1, 4)


def test_2d_floodway_workflow_updates_rasmap_layers_and_result_map(tmp_path):
    project_dir = _make_2d_project(tmp_path)
    project = RasPrj()
    init_ras_project(project_dir, "6.6", ras_object=project, load_results_summary=False)

    result = RasEncroachments.setup_2d_floodway_encroachment_plan(
        "02",
        base_plan="01",
        target_rise=0.75,
        regions=[
            {
                "name": "Fill Region",
                "polygon": [(0, 0), (10, 0), (10, 10), (0, 10)],
            }
        ],
        zones=[
            {
                "name": "Zone 1",
                "polygon": [(2, 2), (8, 2), (8, 8), (2, 8)],
            }
        ],
        default_fill_slope=0.002,
        default_additional_fill=0.4,
        zone_contour_overrides={"Zone 1": 1.1},
        add_depth_velocity_map=True,
        terrain_name="USGSTerrain",
        ras_object=project,
    )

    assert result["plan_number"] == "02"
    assert result["settings"]["base_plan_filename"] == r".\Floodway2D.p01"
    assert np.isclose(result["settings"]["fill_slope"], 0.002)
    assert np.isclose(result["settings"]["additional_fill"], 0.4)
    assert np.isclose(result["regions"].loc[0, "fill_slope"], 0.002)
    assert np.isclose(result["regions"].loc[0, "additional_fill_rise"], 0.4)
    assert np.isclose(result["zones"].loc[0, "value"], 1.1)

    tree = ET.parse(project_dir / "Floodway2D.rasmap")
    root = tree.getroot()
    plan_layer = root.find("./Plans/Layer[@Type='RASPlan']")
    assert plan_layer is not None
    assert plan_layer.get("Name") == "Encroach"
    assert plan_layer.get("Filename") == r".\Floodway2D.p02"
    assert plan_layer.get("GeometryHDF") == r".\Floodway2D.g01.hdf"
    child_types = {child.get("Type") for child in plan_layer.findall("Layer")}
    assert child_types == {
        "RASEncroachments",
        "RASEncroachmentZones",
        "RASEncroachmentPolygons",
    }

    result_maps = RasMap.list_results_map_layers(ras_object=project)
    assert len(result_maps) == 1
    assert result_maps[0]["name"] == "Depth * Velocity"
    assert result_maps[0]["parent_plan"] == "Encroach"
    assert result_maps[0]["map_parameters"]["MapType"] == "depth and velocity"
    assert result_maps[0]["map_parameters"]["Terrain"] == "USGSTerrain"
