import json
import xml.etree.ElementTree as ET
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import RasMap


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
            "  <MapLayers Checked=\"True\" Expanded=\"True\">\n"
            "    <Layer Name=\"USGS Topo\" Type=\"WMSLayer\" Checked=\"True\" "
            "Filename=\"%LocalAppData%\\HEC\\Mapping\\5.1\\XML\\USGS Topo.xml\">\n"
            "      <ResampleMethod>near</ResampleMethod>\n"
            "    </Layer>\n"
            "    <Layer Name=\"Reference Points\" Type=\"PointFeatureLayer\" "
            "Checked=\"True\" Filename=\".\\GIS\\points.shp\" />\n"
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
            "  <Geometries Checked=\"True\" Expanded=\"True\">\n"
            "    <Layer Name=\"Current Geometry\" Type=\"RASGeometry\" "
            "Checked=\"True\" Filename=\".\\GeometryLayerProject.g04.hdf\">\n"
            "      <Layer Type=\"RASRiver\" Checked=\"True\" />\n"
            "      <Layer Type=\"RASXS\" Checked=\"True\" />\n"
            "      <Layer Type=\"RASD2FlowArea\" Checked=\"True\" />\n"
            "      <Layer Type=\"MeshPerimeterLayer\" />\n"
            "      <Layer Type=\"LateralStructureLayer\" Checked=\"True\" />\n"
            "      <Layer Type=\"StructureLayer\" Checked=\"False\" />\n"
            "    </Layer>\n"
            "  </Geometries>\n"
            "  <Results Checked=\"True\">\n"
            "    <Layer Name=\"Plan A\" Type=\"RASResults\" Checked=\"True\">\n"
            "      <Layer Name=\"Depth\" Type=\"DepthLayer\" Checked=\"True\">\n"
            "        <Symbology>\n"
            "          <SurfaceFill RegenerateForScreen=\"False\" />\n"
            "        </Symbology>\n"
            "        <Surface On=\"True\" />\n"
            "      </Layer>\n"
            "      <Layer Name=\"WSE\" Type=\"WSELayer\" Checked=\"False\" />\n"
            "    </Layer>\n"
            "    <Layer Name=\"Plan B\" Type=\"RASResults\" Checked=\"True\">\n"
            "      <Layer Name=\"Depth\" Type=\"DepthLayer\" Checked=\"True\" />\n"
            "    </Layer>\n"
            "  </Results>\n"
            "  <MapLayers Checked=\"True\" Expanded=\"True\">\n"
            "    <Layer Name=\"USGS Topo\" Type=\"WMSLayer\" Checked=\"True\" "
            "Filename=\"%LocalAppData%\\HEC\\Mapping\\5.1\\XML\\USGS Topo.xml\">\n"
            "      <ResampleMethod>near</ResampleMethod>\n"
            "    </Layer>\n"
            "    <Layer Name=\"Reference Lines\" Type=\"PolylineFeatureLayer\" "
            "Checked=\"True\" Filename=\".\\GIS\\reference_lines.shp\" />\n"
            "    <Layer Name=\"Land Cover\" Type=\"LandCoverLayer\" Checked=\"True\" "
            "Filename=\".\\Land Classification\\landcover.hdf\" />\n"
            "  </MapLayers>\n"
            "  <Terrains Checked=\"True\" Expanded=\"True\">\n"
            "    <Layer Name=\"Terrain\" Type=\"TerrainLayer\" Filename=\".\\Terrain\\Terrain.hdf\">\n"
            "      <Symbology>\n"
            "        <SurfaceFill RegenerateForScreen=\"False\" />\n"
            "      </Symbology>\n"
            "      <Surface On=\"False\" />\n"
            "    </Layer>\n"
            "    <Layer Name=\"TerrainWithChannel\" Type=\"TerrainLayer\" Checked=\"True\" "
            "Filename=\".\\Terrain\\TerrainWithChannel.hdf\">\n"
            "      <Symbology>\n"
            "        <SurfaceFill RegenerateForScreen=\"False\" />\n"
            "      </Symbology>\n"
            "      <Surface On=\"True\" />\n"
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
    assert references.loc[
        references["name"] == "Good GeoJSON",
        "type",
    ].iloc[0] == "PolygonFeatureLayer"

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
    assert layers.loc[layers["category"] == "geometry", "geometry_number"].iloc[0] == "04"
    assert bool(
        elements.loc[
            elements["layer_type"] == "RASD2FlowArea",
            "geometry_hdf_exists",
        ].iloc[0]
    ) is True


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
