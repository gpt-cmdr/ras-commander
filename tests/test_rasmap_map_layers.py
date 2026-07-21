import importlib
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, get_type_hints

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import (
    BenefitAreaConfig,
    RasMap,
    RasProcess,
    StoreMapPerformanceOptions,
)

RASMAP_LOGGER = "ras_commander.RasMap"
RASMAP_LAYER_HELPER_LOGGER = "ras_commander._rasmap_layer_helper"


def _make_project(tmp_path: Path, name: str = "MapLayerProject") -> Path:
    project_dir = tmp_path / name
    project_dir.mkdir()
    (project_dir / f"{name}.prj").write_text(
        "Proj Title=Map Layer Project\nCurrent Plan=\n",
        encoding="utf-8",
    )
    (project_dir / f"{name}.rasmap").write_text(
        (
            "<RASMapper>\n"
            "  <Results />\n"
            '  <MapLayers Checked="True" Expanded="True">\n'
            '    <Layer Name="USGS Topo" Type="WMSLayer" Checked="True" '
            'Filename="%LocalAppData%\\HEC\\Mapping\\5.1\\XML\\USGS Topo.xml">\n'
            "      <ResampleMethod>near</ResampleMethod>\n"
            "    </Layer>\n"
            '    <Layer Name="Reference Points" Type="PointFeatureLayer" '
            'Checked="True" Filename=".\\GIS\\points.shp" />\n'
            "  </MapLayers>\n"
            "</RASMapper>\n"
        ),
        encoding="utf-8",
    )
    return project_dir


def _write_geojson(path: Path, coordinates, crs_name: str | None = None) -> Path:
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": 1},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coordinates],
                },
            }
        ],
    }
    if crs_name is not None:
        geojson["crs"] = {
            "type": "name",
            "properties": {"name": crs_name},
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(geojson), encoding="utf-8")
    return path


def _make_geometry_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "GeometryLayerProject"
    project_dir.mkdir()
    (project_dir / "GeometryLayerProject.prj").write_text(
        "Proj Title=Geometry Layer Project\nCurrent Plan=\n",
        encoding="utf-8",
    )
    (project_dir / "GeometryLayerProject.rasmap").write_text(
        (
            "<RASMapper>\n"
            '  <Geometries Checked="True" Expanded="True">\n'
            '    <Layer Name="Current Geometry" Type="RASGeometry" '
            'Checked="True" Filename=".\\GeometryLayerProject.g04.hdf">\n'
            '      <Layer Type="RASRiver" Checked="True" />\n'
            '      <Layer Type="RASXS" Checked="True" />\n'
            '      <Layer Type="RASD2FlowArea" Checked="True" />\n'
            '      <Layer Type="MeshPerimeterLayer" />\n'
            '      <Layer Type="LateralStructureLayer" Checked="True" />\n'
            '      <Layer Type="StructureLayer" Checked="False" />\n'
            "    </Layer>\n"
            "  </Geometries>\n"
            '  <Results Checked="True">\n'
            '    <Layer Name="Plan A" Type="RASResults" Checked="True">\n'
            '      <Layer Name="Depth" Type="DepthLayer" Checked="True">\n'
            "        <Symbology>\n"
            '          <SurfaceFill RegenerateForScreen="False" />\n'
            "        </Symbology>\n"
            '        <Surface On="True" />\n'
            "      </Layer>\n"
            '      <Layer Name="WSE" Type="WSELayer" Checked="False" />\n'
            "    </Layer>\n"
            '    <Layer Name="Plan B" Type="RASResults" Checked="True">\n'
            '      <Layer Name="Depth" Type="DepthLayer" Checked="True" />\n'
            "    </Layer>\n"
            "  </Results>\n"
            '  <MapLayers Checked="True" Expanded="True">\n'
            '    <Layer Name="USGS Topo" Type="WMSLayer" Checked="True" '
            'Filename="%LocalAppData%\\HEC\\Mapping\\5.1\\XML\\USGS Topo.xml">\n'
            "      <ResampleMethod>near</ResampleMethod>\n"
            "    </Layer>\n"
            '    <Layer Name="Reference Lines" Type="PolylineFeatureLayer" '
            'Checked="True" Filename=".\\GIS\\reference_lines.shp" />\n'
            '    <Layer Name="Land Cover" Type="LandCoverLayer" Checked="True" '
            'Filename=".\\Land Classification\\landcover.hdf" />\n'
            "  </MapLayers>\n"
            '  <Terrains Checked="True" Expanded="True">\n'
            '    <Layer Name="Terrain" Type="TerrainLayer" Filename=".\\Terrain\\Terrain.hdf">\n'
            "      <Symbology>\n"
            '        <SurfaceFill RegenerateForScreen="False" />\n'
            "      </Symbology>\n"
            '      <Surface On="False" />\n'
            "    </Layer>\n"
            '    <Layer Name="TerrainWithChannel" Type="TerrainLayer" Checked="True" '
            'Filename=".\\Terrain\\TerrainWithChannel.hdf">\n'
            "      <Symbology>\n"
            '        <SurfaceFill RegenerateForScreen="False" />\n'
            "      </Symbology>\n"
            '      <Surface On="True" />\n'
            "    </Layer>\n"
            "  </Terrains>\n"
            "  <CurrentView>\n"
            "    <MaxX>100</MaxX>\n"
            "    <MinX>0</MinX>\n"
            "    <MaxY>50</MaxY>\n"
            "    <MinY>0</MinY>\n"
            "  </CurrentView>\n"
            "</RASMapper>\n"
        ),
        encoding="utf-8",
    )
    with h5py.File(project_dir / "GeometryLayerProject.g04.hdf", "w") as hdf:
        river = hdf.create_group("Geometry/River Centerlines")
        river.create_dataset(
            "Polyline Points",
            data=np.array([[0.0, 0.0], [100.0, 0.0]]),
        )
        xs = hdf.create_group("Geometry/Cross Sections")
        xs.create_dataset(
            "Polyline Points",
            data=np.array([[10.0, 10.0], [20.0, 20.0]]),
        )
        flow_areas = hdf.create_group("Geometry/2D Flow Areas")
        flow_dtype = np.dtype([("Name", "S32")])
        flow_areas.create_dataset(
            "Attributes",
            data=np.array([(b"Interior",)], dtype=flow_dtype),
        )
        flow_areas.create_dataset(
            "Polygon Info",
            data=np.array([[0, 4, 0, 1]], dtype=np.int32),
        )
        flow_areas.create_dataset(
            "Polygon Parts",
            data=np.array([[0, 4]], dtype=np.int32),
        )
        flow_areas.create_dataset(
            "Polygon Points",
            data=np.array(
                [
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [10.0, 10.0],
                    [0.0, 10.0],
                ]
            ),
        )
        area = hdf.create_group("Geometry/2D Flow Areas/Interior")
        area.create_dataset(
            "Perimeter",
            data=np.array(
                [
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [10.0, 10.0],
                    [0.0, 10.0],
                ]
            ),
        )
        breaklines = hdf.create_group("Geometry/2D Flow Area Break Lines")
        break_dtype = np.dtype([("Name", "S32")])
        breaklines.create_dataset(
            "Attributes",
            data=np.array([(b"Road Breakline",)], dtype=break_dtype),
        )
        breaklines.create_dataset(
            "Polyline Info",
            data=np.array([[0, 2, 0, 1]], dtype=np.int32),
        )
        breaklines.create_dataset(
            "Polyline Points",
            data=np.array([[70.0, 70.0], [80.0, 80.0]]),
        )
        structures = hdf.create_group("Geometry/Structures")
        structures.create_dataset(
            "Centerline Points",
            data=np.array(
                [
                    [50.0, 50.0],
                    [60.0, 60.0],
                    [150.0, 150.0],
                    [160.0, 160.0],
                    [500.0, 500.0],
                    [600.0, 600.0],
                ]
            ),
        )
        dtype = np.dtype([("Type", "S16")])
        structures.create_dataset(
            "Attributes",
            data=np.array([(b"Lateral",), (b"Lateral",), (b"Inline",)], dtype=dtype),
        )
        structures.create_dataset(
            "Centerline Info",
            data=np.array(
                [[0, 2, 0, 1], [2, 2, 1, 1], [4, 2, 2, 1]],
                dtype=np.int32,
            ),
        )
    return project_dir


def _rasmap_records(caplog):
    return [record for record in caplog.records if record.name == RASMAP_LOGGER]


def _map_layer_helper_records(caplog):
    return [
        record for record in caplog.records if record.name == RASMAP_LAYER_HELPER_LOGGER
    ]


def test_list_map_layers_splits_basemaps_and_reference_layers(tmp_path):
    project_dir = _make_project(tmp_path)

    layers = RasMap.list_map_layers(project_dir)
    references = RasMap.list_reference_map_layers(project_dir)
    basemaps = RasMap.list_basemap_layers(project_dir)

    assert isinstance(layers, pd.DataFrame)
    assert list(layers["category"]) == ["basemap", "reference"]
    assert list(references["name"]) == ["Reference Points"]
    assert list(basemaps["name"]) == ["USGS Topo"]
    assert bool(basemaps.iloc[0]["is_standard_basemap"]) is True

    parsed = RasMap.parse_rasmap(project_dir / "MapLayerProject.rasmap")
    assert parsed.at[0, "reference_map_layer_names"] == ["Reference Points"]
    assert parsed.at[0, "basemap_layer_names"] == ["USGS Topo"]


def test_read_only_rasmap_discovery_is_quiet_at_info(tmp_path, caplog):
    project_dir = _make_geometry_project(tmp_path)
    rasmap_path = project_dir / "GeometryLayerProject.rasmap"

    class DummyProject:
        project_folder = project_dir
        project_name = "GeometryLayerProject"

        def check_initialized(self):
            return None

    caplog.set_level(logging.INFO, logger=RASMAP_LOGGER)

    assert RasMap.get_terrain_names(rasmap_path) == ["Terrain", "TerrainWithChannel"]
    assert len(RasMap.list_map_layers(project_dir)) == 3
    assert len(RasMap.list_geometries(ras_object=DummyProject())) == 1
    assert len(RasMap.list_results_plans(ras_object=DummyProject())) == 2
    assert RasMap.list_results_map_layers(ras_object=DummyProject()) == []

    assert _rasmap_records(caplog) == []


def test_read_only_rasmap_discovery_keeps_details_at_debug(tmp_path, caplog):
    project_dir = _make_geometry_project(tmp_path)
    rasmap_path = project_dir / "GeometryLayerProject.rasmap"

    caplog.set_level(logging.DEBUG, logger=RASMAP_LOGGER)

    assert RasMap.get_terrain_names(rasmap_path) == ["Terrain", "TerrainWithChannel"]

    messages = [record.getMessage() for record in _rasmap_records(caplog)]
    assert any("Found 2 terrain layer(s)" in message for message in messages)
    assert any("TerrainWithChannel" in message for message in messages)


def test_add_basemap_layer_uses_standard_rasmapper_template(tmp_path):
    project_dir = _make_project(tmp_path)

    rasmap_path = RasMap.add_basemap_layer(project_dir, "Google Hybrid")
    basemaps = RasMap.list_basemap_layers(project_dir)

    assert rasmap_path == project_dir / "MapLayerProject.rasmap"
    google = basemaps.loc[basemaps["name"] == "Google Hybrid"].iloc[0]
    assert google["type"] == "WMSLayer"
    assert google["filename"].endswith(r"Google Hybrid.xml")
    assert google["resample_method"] == "near"


def test_add_reference_map_layer_validates_geojson_wgs84(tmp_path):
    project_dir = _make_project(tmp_path)
    good_geojson = _write_geojson(
        project_dir / "GIS" / "good.geojson",
        [
            [-82.1, 40.1],
            [-82.0, 40.1],
            [-82.0, 40.2],
            [-82.1, 40.2],
            [-82.1, 40.1],
        ],
    )
    bad_geojson = _write_geojson(
        project_dir / "GIS" / "bad.geojson",
        [
            [500000.0, 4100000.0],
            [500010.0, 4100000.0],
            [500010.0, 4100010.0],
            [500000.0, 4100010.0],
            [500000.0, 4100000.0],
        ],
    )
    explicit_bad_geojson = _write_geojson(
        project_dir / "GIS" / "explicit_bad.geojson",
        [
            [-82.1, 40.1],
            [-82.0, 40.1],
            [-82.0, 40.2],
            [-82.1, 40.2],
            [-82.1, 40.1],
        ],
        crs_name="EPSG:3857",
    )

    RasMap.add_reference_map_layer(
        project_dir,
        good_geojson,
        layer_name="Good GeoJSON",
    )
    references = RasMap.list_reference_map_layers(project_dir)
    assert "Good GeoJSON" in set(references["name"])
    assert (
        references.loc[
            references["name"] == "Good GeoJSON",
            "type",
        ].iloc[0]
        == "PolygonFeatureLayer"
    )

    with pytest.raises(ValueError, match="WGS84/EPSG:4326"):
        RasMap.add_reference_map_layer(
            project_dir,
            bad_geojson,
            layer_name="Bad GeoJSON",
        )
    with pytest.raises(ValueError, match="Detected CRS: EPSG:3857"):
        RasMap.add_reference_map_layer(
            project_dir,
            explicit_bad_geojson,
            layer_name="Explicit Bad GeoJSON",
        )


def test_add_map_layers_log_concise_info_and_debug_path(tmp_path, caplog):
    project_dir = _make_project(tmp_path)
    rasmap_path = project_dir / "MapLayerProject.rasmap"
    good_geojson = _write_geojson(
        project_dir / "GIS" / "good.geojson",
        [
            [-82.1, 40.1],
            [-82.0, 40.1],
            [-82.0, 40.2],
            [-82.1, 40.2],
            [-82.1, 40.1],
        ],
    )

    caplog.set_level(logging.DEBUG, logger=RASMAP_LAYER_HELPER_LOGGER)

    reference_result = RasMap.add_reference_map_layer(
        project_dir,
        good_geojson,
        layer_name="Good GeoJSON",
    )
    basemap_result = RasMap.add_basemap_layer(project_dir, "Google Hybrid")

    info_text = "\n".join(
        record.getMessage()
        for record in _map_layer_helper_records(caplog)
        if record.levelno == logging.INFO
    )
    debug_text = "\n".join(
        record.getMessage()
        for record in _map_layer_helper_records(caplog)
        if record.levelno == logging.DEBUG
    )

    assert reference_result == rasmap_path
    assert basemap_result == rasmap_path
    assert "Added reference map layer 'Good GeoJSON' in .rasmap" in info_text
    assert "Added basemap layer 'Google Hybrid' in .rasmap" in info_text
    assert str(project_dir) not in info_text
    assert str(rasmap_path) not in info_text
    assert f"Updated RASMapper file: {rasmap_path}" in debug_text


def test_legacy_add_map_layer_returns_bool_and_warns(tmp_path, monkeypatch):
    project_dir = _make_project(tmp_path)
    geojson = _write_geojson(
        project_dir / "GIS" / "legacy.geojson",
        [
            [-83.0, 41.0],
            [-82.9, 41.0],
            [-82.9, 41.1],
            [-83.0, 41.1],
            [-83.0, 41.0],
        ],
    )

    class FakeRas:
        project_folder = project_dir
        project_name = "MapLayerProject"

        @staticmethod
        def check_initialized():
            return None

    with pytest.warns(FutureWarning, match="legacy alias"):
        result = RasMap.add_map_layer(
            "Legacy GeoJSON",
            geojson,
            layer_type="PolygonFeatureLayer",
            ras_object=FakeRas(),
        )

    assert result is True
    references = RasMap.list_reference_map_layers(project_dir)
    assert "Legacy GeoJSON" in set(references["name"])


def test_legacy_list_map_layers_preserves_active_object_shape(tmp_path):
    project_dir = _make_project(tmp_path)

    class FakeRas:
        project_folder = project_dir
        project_name = "MapLayerProject"

        @staticmethod
        def check_initialized():
            return None

    with pytest.warns(FutureWarning, match="legacy list"):
        layers = RasMap.list_map_layers(ras_object=FakeRas())

    assert isinstance(layers, list)
    assert layers[0] == {
        "name": "USGS Topo",
        "type": "WMSLayer",
        "filename": r"%LocalAppData%\HEC\Mapping\5.1\XML\USGS Topo.xml",
        "checked": True,
    }


def test_list_geometry_layers_exposes_child_elements(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    layers = RasMap.list_geometry_layers(project_dir)
    elements = layers.loc[layers["category"] == "geometry_element"]

    assert set(elements["layer_type"]) == {
        "RASRiver",
        "RASXS",
        "RASD2FlowArea",
        "MeshPerimeterLayer",
        "LateralStructureLayer",
        "StructureLayer",
    }
    assert (
        layers.loc[layers["category"] == "geometry", "geometry_number"].iloc[0] == "04"
    )
    assert (
        bool(
            elements.loc[
                elements["layer_type"] == "RASD2FlowArea",
                "geometry_hdf_exists",
            ].iloc[0]
        )
        is True
    )


def test_set_geometry_layer_visibility_targets_child_layers(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    modified = RasMap.set_geometry_layer_visibility(
        project_dir,
        layer_type="RASXS",
        checked=False,
    )

    assert modified == 1
    layers = RasMap.list_geometry_layers(project_dir)
    xs_layer = layers.loc[layers["layer_type"] == "RASXS"].iloc[0]
    river_layer = layers.loc[layers["layer_type"] == "RASRiver"].iloc[0]
    assert bool(xs_layer["checked"]) is False
    assert bool(river_layer["checked"]) is True


def test_set_geometry_layer_visibility_accepts_multiple_layer_types(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    rasmap_path = project_dir / "GeometryLayerProject.rasmap"
    tree = ET.parse(rasmap_path)
    root = tree.getroot()
    root.find("./Geometries").set("Checked", "False")
    tree.write(rasmap_path, encoding="utf-8", xml_declaration=True)

    modified = RasMap.set_geometry_layer_visibility(
        project_dir,
        geometry_number="04",
        layer_type=["RASD2FlowArea", "LateralStructureLayer"],
        checked=True,
        exclusive=True,
    )

    assert modified > 0
    layers = RasMap.list_geometry_layers(project_dir)
    elements = layers.loc[layers["category"] == "geometry_element"].copy()
    visible = elements.loc[elements["checked"] == True, "layer_type"].tolist()
    assert visible == ["RASD2FlowArea", "LateralStructureLayer"]
    root = ET.parse(project_dir / "GeometryLayerProject.rasmap").getroot()
    assert root.find("./Geometries").attrib["Checked"] == "True"


def test_result_layer_visibility_can_hide_all_and_select_child_layer(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    result_layers = RasMap.list_result_layers(project_dir)
    assert set(result_layers["category"]) == {"result_plan", "result_layer"}
    assert {"Plan A", "Plan B"}.issubset(set(result_layers["plan_name"]))

    hidden = RasMap.set_result_layer_visibility(project_dir, checked=False)
    assert hidden > 0
    result_layers = RasMap.list_result_layers(project_dir)
    assert not result_layers["checked"].fillna(False).any()
    root = ET.parse(project_dir / "GeometryLayerProject.rasmap").getroot()
    assert root.find("./Results").attrib["Checked"] == "False"

    shown = RasMap.set_result_layer_visibility(
        project_dir,
        plan_name="Plan A",
        layer_name="Depth",
        checked=True,
        exclusive=True,
    )
    assert shown > 0
    result_layers = RasMap.list_result_layers(project_dir)
    visible = result_layers.loc[result_layers["checked"] == True]
    assert set(visible["layer_name"]) == {"Plan A", "Depth"}
    assert set(visible["plan_name"]) == {"Plan A"}
    root = ET.parse(project_dir / "GeometryLayerProject.rasmap").getroot()
    results = root.find("./Results")
    result_plans = results.findall("./Layer")
    assert results.attrib["Checked"] == "True"
    assert result_plans[0].attrib["Checked"] == "True"
    assert result_plans[1].attrib["Checked"] == "False"


def test_map_layer_visibility_can_hide_all_and_selective_layers(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    hidden = RasMap.set_map_layer_visibility(project_dir, checked=False)
    assert hidden > 0
    map_layers = RasMap.list_map_layers(project_dir)
    assert not map_layers["checked"].fillna(False).any()
    root = ET.parse(project_dir / "GeometryLayerProject.rasmap").getroot()
    assert root.find("./MapLayers").attrib["Checked"] == "False"

    shown = RasMap.set_map_layer_visibility(
        project_dir,
        category="land_classification",
        checked=True,
        exclusive=True,
    )
    assert shown > 0
    map_layers = RasMap.list_map_layers(project_dir)
    visible = map_layers.loc[map_layers["checked"] == True]
    assert visible["name"].tolist() == ["Land Cover"]
    root = ET.parse(project_dir / "GeometryLayerProject.rasmap").getroot()
    assert root.find("./MapLayers").attrib["Checked"] == "True"


def test_terrain_visibility_and_update_legend_with_view(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    terrain_modified = RasMap.set_terrain_layer_visibility(
        project_dir,
        terrain_name="TerrainWithChannel",
        checked=True,
        exclusive=True,
    )
    legend_modified = RasMap.set_update_legend_with_view(project_dir)

    assert terrain_modified > 0
    assert legend_modified == 3

    root = ET.parse(project_dir / "GeometryLayerProject.rasmap").getroot()
    terrain_layers = root.findall("./Terrains/Layer")
    assert terrain_layers[0].attrib["Checked"] == "False"
    assert terrain_layers[0].find("Surface").attrib["On"] == "False"
    assert terrain_layers[1].attrib["Checked"] == "True"
    assert terrain_layers[1].find("Surface").attrib["On"] == "True"

    surface_fills = root.findall(".//SurfaceFill")
    assert surface_fills
    assert all(
        surface_fill.attrib.get("RegenerateForScreen") == "True"
        for surface_fill in surface_fills
    )


def test_current_view_roundtrip_and_zoom_to_geometry_layer(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    view = RasMap.get_current_view(project_dir)
    assert view["min_x"] == 0.0
    assert view["max_y"] == 50.0

    updated = RasMap.set_current_view(
        project_dir,
        min_x=1.0,
        min_y=2.0,
        max_x=3.0,
        max_y=4.0,
    )
    assert updated["min_x"] == 1.0
    assert updated["max_y"] == 4.0

    zoomed = RasMap.zoom_to_geometry_layer(
        project_dir,
        layer_type="RASD2FlowArea",
        geometry_number="g04",
        padding_fraction=0.1,
    )
    assert zoomed["bounds"] == {
        "min_x": 0.0,
        "min_y": 0.0,
        "max_x": 10.0,
        "max_y": 10.0,
    }
    assert zoomed["view"]["min_x"] == -1.0
    assert zoomed["view"]["max_x"] == 11.0

    combined_zoom = RasMap.zoom_to_geometry_layer(
        project_dir,
        layer_type=["RASD2FlowArea", "LateralStructureLayer"],
        geometry_number="g04",
        padding_fraction=0.0,
    )
    assert combined_zoom["bounds"]["max_x"] == 160.0
    assert combined_zoom["bounds"]["max_y"] == 160.0


def test_lateral_structure_bounds_filter_lateral_records(tmp_path):
    project_dir = _make_geometry_project(tmp_path)
    hdf_path = project_dir / "GeometryLayerProject.g04.hdf"

    lateral = RasMap.get_geometry_layer_bounds(
        hdf_path,
        layer_type="LateralStructureLayer",
    )
    structures = RasMap.get_geometry_layer_bounds(
        hdf_path,
        layer_type="StructureLayer",
    )

    assert lateral["has_bounds"] is True
    assert lateral["max_x"] == 160.0
    assert structures["max_x"] == 600.0


def test_breakline_and_sa2d_layer_aliases_resolve_hdf_bounds(tmp_path):
    project_dir = _make_geometry_project(tmp_path)
    hdf_path = project_dir / "GeometryLayerProject.g04.hdf"

    breakline = RasMap.get_geometry_layer_bounds(
        hdf_path,
        layer_type="RASBreakLines",
    )
    sa2d = RasMap.get_geometry_layer_bounds(
        hdf_path,
        layer_type="SA2DStructureLayer",
    )
    breakline_features = RasMap.list_geometry_features(
        hdf_path,
        layer_type="RASBreakLines",
    )

    assert breakline["has_bounds"] is True
    assert breakline["max_x"] == 80.0
    assert sa2d["has_bounds"] is True
    assert sa2d["max_x"] == 600.0
    assert breakline_features.iloc[0]["feature_name"] == "Road Breakline"


def test_list_geometry_features_and_zoom_to_selected_feature(tmp_path):
    project_dir = _make_geometry_project(tmp_path)
    hdf_path = project_dir / "GeometryLayerProject.g04.hdf"

    lateral_features = RasMap.list_geometry_features(
        hdf_path,
        layer_type="LateralStructureLayer",
    )
    assert list(lateral_features["feature_index"]) == [0, 1]
    assert list(lateral_features["max_x"]) == [60.0, 160.0]

    second_lateral = RasMap.get_geometry_feature_bounds(
        hdf_path,
        layer_type="LateralStructureLayer",
        feature_index=1,
    )
    assert second_lateral["has_bounds"] is True
    assert second_lateral["min_x"] == 150.0
    assert second_lateral["max_x"] == 160.0

    zoomed = RasMap.zoom_to_geometry_layer(
        project_dir,
        layer_type="LateralStructureLayer",
        geometry_number="04",
        feature_index=1,
    )
    assert zoomed["bounds"]["min_x"] == 150.0
    assert zoomed["bounds"]["max_x"] == 160.0
    assert zoomed["uses_feature_bounds"] is True
    assert zoomed["padding_fraction"] == 0.25
    assert zoomed["view_expansion_fraction"] == 0.5
    assert zoomed["view"]["min_x"] == 147.5
    assert zoomed["view"]["max_x"] == 162.5


def test_create_spatial_review_package_writes_audit_bundle(tmp_path):
    project_dir = _make_geometry_project(tmp_path)
    output_dir = tmp_path / "review_package"

    state = RasMap.create_spatial_review_package(
        project_dir,
        output_dir=output_dir,
        geometry_number="04",
        layer_type=["RASD2FlowArea", "LateralStructureLayer"],
        feature_index=1,
        terrain_name="TerrainWithChannel",
        viewport_width=1440,
        viewport_height=900,
        dpi=96,
        expanded_tree_paths=["Results/Plan A", "Geometries/Geometry 04"],
        ramp_id="ras.depth",
        range_mode="current-view",
        selected_layer="depth-max",
        result_profile="Max",
        render_mode="slopingPretty",
        basemap="hybrid",
        ras_version="7.0",
        web_manifest_url="https://rascommander.info/data/muncie/viewer/manifest.json",
    )

    assert state["passed"] is True
    assert state["snapshot"]["requested"] is False
    assert state["current_view_after"]["min_x"] == 147.5
    assert state["current_view_after"]["max_x"] == 162.5

    artifacts = state["artifacts"]
    for key in (
        "rasmap_before",
        "rasmap_after",
        "geometry_layers",
        "result_layers",
        "geometry_features",
        "selected_features",
        "selected_result_layers",
        "selected_map_layers",
        "map_layers",
        "layers",
        "review_state",
        "findings_template",
    ):
        assert Path(artifacts[key]).exists()

    review_state = json.loads(Path(artifacts["review_state"]).read_text())
    assert review_state["view_spec"]["terrain_name"] == "TerrainWithChannel"
    assert review_state["view_spec"]["layer_type"] == [
        "LateralStructureLayer",
        "RASD2FlowArea",
    ]
    assert review_state["view_spec"]["feature_index"] == 1
    assert review_state["view_spec"]["include_results"] is False
    assert review_state["view_spec"]["include_map_layers"] is False
    assert review_state["view_spec"]["padding_fraction"] == 0.25
    assert review_state["view_spec"]["view_expansion_fraction"] == 0.5
    assert review_state["view_spec"]["snapshot_timeout_seconds"] == 1800.0
    assert review_state["view_spec"]["viewport"] == {"width": 1440, "height": 900}
    assert review_state["view_spec"]["dpi"] == 96
    assert review_state["view_spec"]["expanded_tree_paths"] == [
        "Geometries/Geometry 04",
        "Results/Plan A",
    ]
    assert review_state["view_spec"]["ramp_id"] == "ras.depth"
    assert review_state["view_spec"]["range_mode"] == "current-view"
    assert review_state["view_spec"]["selected_layer"] == "depth-max"
    assert review_state["view_spec"]["result_profile"] == "Max"
    assert review_state["view_spec"]["render_mode"] == "slopingPretty"
    assert review_state["view_spec"]["basemap"] == "hybrid"
    assert review_state["view_spec"]["ras_version"] == "7.0"
    assert review_state["view_spec"]["web_manifest_url"].endswith("manifest.json")
    assert any(
        check["code"] == "selected_geometry_layers_found" and check["passed"]
        for check in review_state["preflight"]
    )
    assert any(
        check["code"] == "selected_geometry_features_found" and check["passed"]
        for check in review_state["preflight"]
    )

    layers = pd.read_csv(artifacts["layers"])
    assert {
        "RASD2FlowArea",
        "LateralStructureLayer",
    }.issubset(set(layers["type"]))
    assert {"geometry", "result", "map"}.issubset(set(layers["source"]))

    selected_features = pd.read_csv(artifacts["selected_features"])
    assert len(selected_features) == 1
    assert selected_features.iloc[0]["feature_index"] == 1
    assert selected_features.iloc[0]["max_x"] == 160.0

    geometry_layers = RasMap.list_geometry_layers(project_dir)
    visible = geometry_layers.loc[
        (geometry_layers["category"] == "geometry_element")
        & (geometry_layers["checked"] == True),
        "layer_type",
    ].tolist()
    assert visible == ["RASD2FlowArea", "LateralStructureLayer"]

    result_layers = pd.read_csv(artifacts["result_layers"])
    assert not result_layers["checked"].fillna(False).any()
    map_layers = pd.read_csv(artifacts["map_layers"])
    assert not map_layers["checked"].fillna(False).any()


def test_create_spatial_review_package_defaults_to_screenshots_folder(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    state = RasMap.create_spatial_review_package(
        project_dir,
        geometry_number="04",
        layer_type="RASD2FlowArea",
        capture_snapshot=False,
    )

    expected_dir = project_dir / "RASMapper Screenshots"
    assert Path(state["output_dir"]) == expected_dir
    assert Path(state["artifacts"]["review_state"]).parent == expected_dir
    assert expected_dir.exists()


def test_spatial_review_requires_complete_viewport_dimensions(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    with pytest.raises(ValueError, match="provided together"):
        RasMap.create_spatial_review_package(
            project_dir,
            geometry_number="04",
            layer_type="RASD2FlowArea",
            viewport_width=1440,
        )


def test_create_spatial_review_package_can_select_result_and_map_layers(tmp_path):
    project_dir = _make_geometry_project(tmp_path)
    output_dir = tmp_path / "review_package_with_context"

    state = RasMap.create_spatial_review_package(
        project_dir,
        output_dir=output_dir,
        geometry_number="04",
        layer_type=["RASD2FlowArea", "LateralStructureLayer"],
        feature_index=1,
        terrain_name="TerrainWithChannel",
        result_plan_name="Plan A",
        result_layer_name="Depth",
        map_layer_category="land_classification",
    )

    assert state["passed"] is True
    assert state["view_spec"]["result_plan_name"] == ["Plan A"]
    assert state["view_spec"]["map_layer_category"] == ["land_classification"]
    assert any(
        check["code"] == "selected_result_layers_found" and check["passed"]
        for check in state["preflight"]
    )
    assert any(
        check["code"] == "selected_map_layers_found" and check["passed"]
        for check in state["preflight"]
    )

    result_layers = pd.read_csv(state["artifacts"]["result_layers"])
    visible_results = result_layers.loc[result_layers["checked"] == True]
    assert set(visible_results["layer_name"]) == {"Plan A", "Depth"}

    map_layers = pd.read_csv(state["artifacts"]["map_layers"])
    visible_maps = map_layers.loc[map_layers["checked"] == True]
    assert visible_maps["name"].tolist() == ["Land Cover"]


def test_ensure_results_plan_layer_creates_and_updates_rasresults(tmp_path, caplog):
    project_dir = _make_project(tmp_path)
    plan_path = project_dir / "MapLayerProject.p03"
    plan_path.write_text(
        "Plan Title=Encroached Plan\nShort Identifier=Encroached\n",
        encoding="utf-8",
    )
    (project_dir / "MapLayerProject.p03.hdf").write_bytes(b"")
    caplog.set_level(logging.INFO, logger=RASMAP_LOGGER)

    record = RasMap.ensure_results_plan_layer(
        plan_path,
        name="Encroached Result",
        checked=True,
    )
    assert record["name"] == "Encroached Result"
    assert record["filename"] == r".\MapLayerProject.p03.hdf"

    updated = RasMap.ensure_results_plan_layer(
        plan_path,
        checked=False,
        expanded=False,
    )
    assert updated["name"] == "Encroached"

    root = ET.parse(project_dir / "MapLayerProject.rasmap").getroot()
    layers = root.findall("./Results/Layer[@Type='RASResults']")
    assert len(layers) == 1
    assert layers[0].get("Name") == "Encroached"
    assert layers[0].get("Filename") == r".\MapLayerProject.p03.hdf"
    assert layers[0].get("Checked") == "False"
    assert layers[0].get("Expanded") == "False"

    messages = [record.getMessage() for record in _rasmap_records(caplog)]
    assert "Ensured RASResults layer 'Encroached Result'" in messages
    assert "Ensured RASResults layer 'Encroached'" in messages
    assert all(str(project_dir) not in message for message in messages)


def test_add_wse_comparison_layers_uses_project_rasmap_for_terrains(tmp_path):
    project_dir = _make_geometry_project(tmp_path)

    class DummyProject:
        project_folder = project_dir
        project_name = "GeometryLayerProject"

        def check_initialized(self):
            return None

    created = RasMap.add_wse_comparison_layers(
        plan_pairs=[{"exist_plan": "Plan A", "prop_plan": "Plan B", "tag": "A_B"}],
        exist_terrain="Terrain",
        prop_terrain="TerrainWithChannel",
        ras_object=DummyProject(),
    )

    assert created == ["CompareWSE_A_B"]
    script_path = project_dir / "Calculated Layers" / "CompareWSE_A_B.rasscript"
    assert script_path.exists()

    layers = RasMap.list_calculated_layers(ras_object=DummyProject())
    assert len(layers) == 1
    assert layers[0]["name"] == "CompareWSE_A_B"
    assert layers[0]["parent_plan"] == "Plan B"
    assert layers[0]["terrains"] == ["Terrain", "TerrainWithChannel"]


def test_initialize_rasmap_df_logs_missing_file_once_at_info(tmp_path, caplog):
    class DummyProject:
        project_folder = tmp_path
        project_name = "NoRasmap"

        def check_initialized(self):
            return None

    caplog.set_level(logging.INFO, logger=RASMAP_LOGGER)

    df = RasMap.initialize_rasmap_df(ras_object=DummyProject())

    assert len(df) == 1
    records = _rasmap_records(caplog)
    warnings = [
        record.getMessage() for record in records if record.levelno == logging.WARNING
    ]
    assert warnings == [f"RASMapper file not found: {tmp_path / 'NoRasmap.rasmap'}"]
    assert all(
        "Creating empty rasmap_df" not in record.getMessage() for record in records
    )


def test_screenshot_model_success_logs_name_at_info_and_full_path_at_debug(
    tmp_path,
    monkeypatch,
    caplog,
):
    project_dir = tmp_path / "ScreenshotProject"
    project_dir.mkdir()
    prj_path = project_dir / "ScreenshotProject.prj"
    prj_path.write_text("Proj Title=Screenshot Project\n", encoding="utf-8")
    output_path = project_dir / "review" / "model_capture.png"

    from ras_commander import _rasmap_control_helper as rasmap_control

    class DummyProcess:
        pid = 12345

    def fake_capture_rasmapper_snapshot(*, output_path, **_kwargs):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"png")
        return output_path

    monkeypatch.setattr(
        rasmap_control,
        "open_rasmapper",
        lambda *_args, **_kwargs: DummyProcess(),
    )
    monkeypatch.setattr(
        rasmap_control,
        "capture_rasmapper_snapshot",
        fake_capture_rasmapper_snapshot,
    )
    monkeypatch.setattr(
        rasmap_control,
        "close_rasmapper",
        lambda **_kwargs: 1,
    )
    caplog.set_level(logging.DEBUG, logger=RASMAP_LOGGER)

    result = RasMap.screenshot_model(
        prj_path,
        output_path=output_path,
        configure_layers=False,
    )

    assert result == output_path
    info_messages = [
        record.getMessage()
        for record in _rasmap_records(caplog)
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in _rasmap_records(caplog)
        if record.levelno == logging.DEBUG
    ]
    assert info_messages == ["Screenshot saved: model_capture.png"]
    assert all(str(project_dir) not in message for message in info_messages)
    assert any(str(output_path) in message for message in debug_messages)


def test_store_all_maps_uses_aggregate_info_and_debug_details(
    tmp_path,
    monkeypatch,
    caplog,
):
    project_dir = tmp_path / "StoreProject"
    project_dir.mkdir()
    (project_dir / "StoreProject.rasmap").write_text("<RASMapper />", encoding="utf-8")
    (project_dir / "StoreProject.p01.hdf").write_bytes(b"")
    (project_dir / "StoreProject.p02.hdf").write_bytes(b"")
    hecras_dir = tmp_path / "HEC-RAS" / "6.6"
    hecras_dir.mkdir(parents=True)

    class DummyProject:
        project_folder = project_dir
        project_name = "StoreProject"
        ras_version = "6.6"
        ras_exe_path = hecras_dir / "Ras.exe"
        plan_df = pd.DataFrame(
            [
                {"plan_number": "01", "Short Identifier": "PlanOne"},
                {"plan_number": "02", "Short Identifier": "PlanTwo"},
            ]
        )

        def check_initialized(self):
            return None

    class DummyProcess:
        def __init__(self, returncode, stdout, stderr):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run_store_all_maps_helper(*, result_hdf_path, **_kwargs):
        if Path(result_hdf_path).name.endswith("p02.hdf"):
            return DummyProcess(2, "verbose stdout", "verbose stderr")
        return DummyProcess(0, "success stdout", "")

    rasmap_module = importlib.import_module("ras_commander.RasMap")
    monkeypatch.setattr(
        rasmap_module,
        "run_store_all_maps_helper",
        fake_run_store_all_maps_helper,
    )
    caplog.set_level(logging.DEBUG, logger=RASMAP_LOGGER)

    result = RasMap.store_all_maps(
        ["01", "02"],
        render_mode="horizontal",
        ras_object=DummyProject(),
    )

    assert result["success"] is False
    records = _rasmap_records(caplog)
    info_messages = [
        record.getMessage() for record in records if record.levelno == logging.INFO
    ]
    error_messages = [
        record.getMessage() for record in records if record.levelno == logging.ERROR
    ]
    debug_messages = [
        record.getMessage() for record in records if record.levelno == logging.DEBUG
    ]

    assert info_messages == [
        "Stored map generation complete: 1/2 plans succeeded (mode=horizontal)"
    ]
    assert error_messages == ["Plan 02: StoreAllMaps failed (exit code 2)"]
    assert any(
        "Generating stored maps for plan 01" in message for message in debug_messages
    )
    assert any(
        "Plan 01: StoreAllMaps completed successfully" in message
        for message in debug_messages
    )
    assert any("verbose stderr" in message for message in debug_messages)
    assert all("verbose stderr" not in message for message in error_messages)


def test_store_all_maps_selected_mode_forwards_typed_performance(
    tmp_path,
    monkeypatch,
):
    class DummyProject:
        project_folder = tmp_path
        project_name = "Unified"
        plan_df = pd.DataFrame([{"plan_number": "01"}])

        @staticmethod
        def check_initialized():
            return None

    calls = []

    def fake_store_maps(**kwargs):
        calls.append(kwargs)
        output = tmp_path / "chosen" / "Depth (Max).tif"
        return {"depth": [output], "velocity": []}

    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fake_store_maps))
    performance = StoreMapPerformanceOptions(max_workers=2)

    result = RasMap.store_all_maps(
        "01",
        mode="selected",
        output_folder="rasmap-subdir",
        map_types=("depth", "velocity"),
        output_path=tmp_path / "chosen",
        performance=performance,
        ras_object=DummyProject(),
    )

    assert result == {
        "success": True,
        "mode": "selected",
        "plans": {
            "01": {
                "success": True,
                "output_dir": str(tmp_path / "chosen"),
                "files": [str(tmp_path / "chosen" / "Depth (Max).tif")],
                "files_by_type": {
                    "depth": [str(tmp_path / "chosen" / "Depth (Max).tif")],
                    "velocity": [],
                },
            }
        },
        "render_mode": None,
    }
    assert len(calls) == 1
    assert calls[0]["performance"] is performance
    assert calls[0]["output_folder"] == "rasmap-subdir"
    assert calls[0]["output_path"] == tmp_path / "chosen"
    assert calls[0]["depth"] is True
    assert calls[0]["velocity"] is True
    assert calls[0]["wse"] is False


def test_store_all_maps_all_plans_and_timesteps_are_canonical_modes(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "Unified.p01.hdf").write_bytes(b"hdf")

    class DummyProject:
        project_folder = tmp_path
        project_name = "Unified"
        plan_df = pd.DataFrame([{"plan_number": "01"}, {"plan_number": "02"}])

        @staticmethod
        def check_initialized():
            return None

    map_calls = []
    timestep_calls = []

    def fake_store_maps(**kwargs):
        map_calls.append(kwargs)
        return {"wse": [tmp_path / "maps" / "WSE.tif"]}

    def fake_timesteps(
        plan_number,
        output_path=None,
        timesteps=None,
        max_timesteps=None,
        wse=False,
        depth=True,
        velocity=False,
        froude=False,
        shear_stress=False,
        depth_x_velocity=False,
        depth_x_velocity_sq=False,
        render_mode=None,
        clear_existing=True,
        fix_georef=True,
        ras_object=None,
        ras_version=None,
        timeout=600,
        *,
        performance=None,
    ):
        timestep_calls.append(
            {
                "plan_number": plan_number,
                "output_path": output_path,
                "timesteps": timesteps,
                "max_timesteps": max_timesteps,
                "wse": wse,
                "depth": depth,
                "velocity": velocity,
                "froude": froude,
                "shear_stress": shear_stress,
                "depth_x_velocity": depth_x_velocity,
                "depth_x_velocity_sq": depth_x_velocity_sq,
                "render_mode": render_mode,
                "clear_existing": clear_existing,
                "fix_georef": fix_georef,
                "ras_object": ras_object,
                "ras_version": ras_version,
                "timeout": timeout,
                "performance": performance,
            }
        )
        return {"01JAN2026 00:00:00": {"depth": [tmp_path / "Depth.tif"]}}

    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fake_store_maps))
    monkeypatch.setattr(
        RasProcess,
        "store_maps_at_timesteps",
        staticmethod(fake_timesteps),
    )
    project = DummyProject()

    all_plans = RasMap.store_all_maps(
        mode="all_plans",
        output_path=tmp_path / "all",
        ras_object=project,
    )
    timesteps = RasMap.store_all_maps(
        "01",
        mode="timesteps",
        timesteps=[0],
        map_types=("depth",),
        ras_object=project,
    )
    multi_plan_timesteps = RasMap.store_all_maps(
        ["01", "02"],
        mode="timesteps",
        output_path=tmp_path / "timesteps",
        timesteps=[0],
        map_types="depth",
        ras_object=project,
    )

    assert all_plans["success"] is True
    assert list(all_plans["plans"]) == ["01"]
    assert map_calls[0]["output_path"] == tmp_path / "all" / "plan_01"
    assert timesteps["plans"]["01"]["timesteps"] == {
        "01JAN2026 00:00:00": {"depth": [str(tmp_path / "Depth.tif")]}
    }
    assert "output_folder" not in timestep_calls[0]
    assert "profile" not in timestep_calls[0]
    assert timestep_calls[0]["depth"] is True
    assert timestep_calls[0]["wse"] is False
    assert list(multi_plan_timesteps["plans"]) == ["01", "02"]
    assert timestep_calls[1]["output_path"] == tmp_path / "timesteps" / "plan_01"
    assert timestep_calls[2]["output_path"] == tmp_path / "timesteps" / "plan_02"


def test_store_all_maps_auto_routes_all_modes_and_serializes(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "Unified.p01.hdf").write_bytes(b"hdf")

    class DummyProject:
        project_folder = tmp_path
        project_name = "Unified"
        plan_df = pd.DataFrame([{"plan_number": "01"}])

        @staticmethod
        def check_initialized():
            return None

    configured_layer_calls = []
    configured_calls = []
    timestep_calls = []

    def fake_configured(plan_number, render_mode=None, ras_object=None, timeout=600):
        configured_layer_calls.append((plan_number, render_mode, ras_object, timeout))
        return {
            "success": True,
            "plans": {"01": {"success": True, "files": []}},
            "render_mode": "horizontal",
        }

    def fake_store_maps(**kwargs):
        configured_calls.append(kwargs)
        return {"depth": [tmp_path / "Depth.tif"]}

    def fake_timesteps(
        plan_number,
        output_path=None,
        timesteps=None,
        max_timesteps=None,
        wse=False,
        depth=True,
        velocity=False,
        froude=False,
        shear_stress=False,
        depth_x_velocity=False,
        depth_x_velocity_sq=False,
        render_mode=None,
        clear_existing=True,
        fix_georef=True,
        ras_object=None,
        ras_version=None,
        timeout=600,
        *,
        performance=None,
    ):
        timestep_calls.append(
            {
                "plan_number": plan_number,
                "max_timesteps": max_timesteps,
                "depth": depth,
                "wse": wse,
                "velocity": velocity,
            }
        )
        return {"01JAN2026 00:00:00": {"depth": [tmp_path / "Depth.tif"]}}

    monkeypatch.setattr(
        RasMap,
        "_store_all_maps_configured",
        staticmethod(fake_configured),
    )
    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fake_store_maps))
    monkeypatch.setattr(
        RasProcess,
        "store_maps_at_timesteps",
        staticmethod(fake_timesteps),
    )
    project = DummyProject()

    configured = RasMap.store_all_maps(1, "horizontal", project, 17)
    selected = RasMap.store_all_maps(
        "01",
        output_path=tmp_path / "selected",
        map_types="depth",
        ras_object=project,
    )
    timesteps = RasMap.store_all_maps(
        "01",
        max_timesteps=2,
        ras_object=project,
    )
    all_plans = RasMap.store_all_maps(ras_object=project)

    assert configured["mode"] == "configured"
    assert configured_layer_calls == [("01", "horizontal", project, 17)]
    assert selected["mode"] == "selected"
    assert timesteps["mode"] == "timesteps"
    assert timestep_calls == [
        {
            "plan_number": "01",
            "max_timesteps": 2,
            "depth": True,
            "wse": False,
            "velocity": False,
        }
    ]
    assert all_plans["mode"] == "all_plans"
    assert configured_calls[-1]["plan_number"] == "01"
    for summary in (configured, selected, timesteps, all_plans):
        json.dumps(summary)


def test_store_all_maps_native_is_deprecated_configured_alias(monkeypatch):
    class DummyProject:
        @staticmethod
        def check_initialized():
            return None

    monkeypatch.setattr(
        RasMap,
        "_store_all_maps_configured",
        staticmethod(
            lambda *_args, **_kwargs: {
                "success": True,
                "plans": {},
                "render_mode": "horizontal",
            }
        ),
    )

    with pytest.warns(DeprecationWarning, match="Use mode='configured'"):
        result = RasMap.store_all_maps(
            "01",
            mode="native",
            ras_object=DummyProject(),
        )

    assert result["mode"] == "configured"


def test_store_all_maps_type_hints_are_runtime_resolvable():
    hints = get_type_hints(RasMap.store_all_maps)

    assert hints["benefit_area"] == Optional[BenefitAreaConfig]
    assert hints["performance"] == Optional[StoreMapPerformanceOptions]


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"output_folder": "maps"}, "output_folder"),
        ({"profile": "Min"}, "profile"),
        ({"arrival_depth": 0.1}, "arrival_depth"),
        ({"terrain_name": "Terrain"}, "terrain_name"),
        ({"map_types": ("arrival_time",)}, "arrival_time"),
    ],
)
def test_store_all_maps_timesteps_rejects_unsupported_options(
    tmp_path,
    kwargs,
    message,
):
    class DummyProject:
        @staticmethod
        def check_initialized():
            return None

    with pytest.raises(ValueError, match=message):
        RasMap.store_all_maps(
            "01",
            mode="timesteps",
            timesteps=[0],
            ras_object=DummyProject(),
            **kwargs,
        )


def test_store_all_maps_rejects_empty_selections_and_misplaced_timestep_cap(
    tmp_path,
):
    class DummyProject:
        @staticmethod
        def check_initialized():
            return None

    project = DummyProject()
    with pytest.raises(ValueError, match="at least one plan"):
        RasMap.store_all_maps([], mode="configured", ras_object=project)
    with pytest.raises(ValueError, match="At least one stored-map product"):
        RasMap.store_all_maps(
            "01",
            mode="selected",
            map_types=(),
            ras_object=project,
        )
    with pytest.raises(ValueError, match="At least one stored-map product"):
        RasMap.store_all_maps(
            "01",
            mode="selected",
            wse=False,
            depth=False,
            velocity=False,
            ras_object=project,
        )
    with pytest.raises(ValueError, match="max_timesteps is only valid"):
        RasMap.store_all_maps(
            "01",
            mode="selected",
            max_timesteps=2,
            ras_object=project,
        )


def test_store_all_maps_configured_mode_rejects_selected_options(tmp_path):
    class DummyProject:
        @staticmethod
        def check_initialized():
            return None

    with pytest.raises(ValueError, match="mode='configured' only accepts"):
        RasMap.store_all_maps(
            "01",
            mode="configured",
            output_path=tmp_path,
            ras_object=DummyProject(),
        )


def test_rasprocess_store_all_maps_is_compatibility_forwarder(
    tmp_path,
    monkeypatch,
):
    calls = []

    def fake_canonical(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "success": True,
            "mode": "all_plans",
            "render_mode": None,
            "plans": {
                "01": {
                    "success": True,
                    "files_by_type": {"depth": [str(tmp_path / "Depth.tif")]},
                }
            },
        }

    monkeypatch.setattr(RasMap, "store_all_maps", staticmethod(fake_canonical))

    with pytest.warns(DeprecationWarning, match="compatibility alias") as caught:
        result = RasProcess.store_all_maps(output_path=tmp_path)

    assert result == {"01": {"depth": [tmp_path / "Depth.tif"]}}
    assert calls[0][1]["mode"] == "all_plans"
    assert Path(caught[0].filename).resolve() == Path(__file__).resolve()


def test_get_results_raster_multiple_matches_raises_without_error_log(
    tmp_path,
    monkeypatch,
    caplog,
):
    mapping_folder = tmp_path / "Plan01"
    mapping_folder.mkdir()
    (mapping_folder / "WSE (Max).vrt").write_text("", encoding="utf-8")
    (mapping_folder / "WSE (Min).vrt").write_text("", encoding="utf-8")

    class DummyProject:
        def check_initialized(self):
            return None

    monkeypatch.setattr(
        RasMap,
        "get_results_folder",
        staticmethod(lambda *_args, **_kwargs: mapping_folder),
    )
    caplog.set_level(logging.DEBUG, logger=RASMAP_LOGGER)

    with pytest.raises(ValueError, match="Multiple .vrt files"):
        RasMap.get_results_raster("01", "WSE", ras_object=DummyProject())

    records = _rasmap_records(caplog)
    assert all(record.levelno < logging.ERROR for record in records)
    assert any(
        "Multiple .vrt files match 'WSE'" in record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    )


def test_add_terrain_layer_logs_one_visible_summary_per_mutation(tmp_path, caplog):
    project_dir = _make_project(tmp_path)
    terrain_hdf = project_dir / "Terrain" / "Terrain.hdf"
    terrain_hdf.parent.mkdir()
    terrain_hdf.write_bytes(b"")
    rasmap_path = project_dir / "MapLayerProject.rasmap"

    caplog.set_level(logging.INFO, logger=RASMAP_LOGGER)

    RasMap.add_terrain_layer(
        terrain_hdf,
        rasmap_path,
        layer_name="ReviewTerrain",
    )

    messages = [record.getMessage() for record in _rasmap_records(caplog)]
    assert messages == ["Added terrain layer 'ReviewTerrain' in .rasmap"]

    caplog.clear()
    RasMap.add_terrain_layer(
        terrain_hdf,
        rasmap_path,
        layer_name="ReviewTerrain",
    )

    messages = [record.getMessage() for record in _rasmap_records(caplog)]
    assert messages == ["Replaced terrain layer 'ReviewTerrain' in .rasmap"]


def test_calculated_layer_script_file_logs_are_debug_only(tmp_path, caplog):
    project_dir = _make_geometry_project(tmp_path)

    class DummyProject:
        project_folder = project_dir
        project_name = "GeometryLayerProject"

        def check_initialized(self):
            return None

    caplog.set_level(logging.INFO, logger=RASMAP_LOGGER)

    added = RasMap.add_calculated_layer(
        layer_name="ReviewCalc",
        host_plan_name="Plan A",
        script_content="' review calculation\n",
        raster_maps=[{"result": "Plan A"}],
        terrain_names=["Terrain"],
        ras_object=DummyProject(),
    )

    assert added is True
    messages = [record.getMessage() for record in _rasmap_records(caplog)]
    assert messages == ["Added calculated layer 'ReviewCalc' to plan 'Plan A'"]

    caplog.clear()
    removed = RasMap.remove_calculated_layer(
        "ReviewCalc",
        host_plan_name="Plan A",
        delete_script=True,
        ras_object=DummyProject(),
    )

    assert removed is True
    messages = [record.getMessage() for record in _rasmap_records(caplog)]
    assert messages == ["Removed calculated layer 'ReviewCalc' from 'Plan A'"]
