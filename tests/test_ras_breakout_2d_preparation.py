from pathlib import Path
from importlib import import_module

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon

from ras_commander import (
    Breakout2DPreflight,
    Breakout2DSpec,
    RasBreakout2D,
)
from ras_commander.schemas import DATAFRAME_SCHEMAS


breakout_module = import_module("ras_commander.RasBreakout2D")


class _FakeRas:
    def __init__(
        self,
        plan_df=None,
        geom_df=None,
        boundaries_df=None,
        project_folder=None,
    ):
        self.plan_df = plan_df if plan_df is not None else pd.DataFrame()
        self.geom_df = geom_df if geom_df is not None else pd.DataFrame()
        self.boundaries_df = (
            boundaries_df if boundaries_df is not None else pd.DataFrame()
        )
        self.current_plan = None
        self.project_folder = Path(project_folder) if project_folder else Path.cwd()
        self.project_name = "Model"

    def check_initialized(self):
        return None

    def get_plan_entries(self):
        return self.plan_df

    def get_geom_entries(self):
        return self.geom_df

    def set_current_plan(self, plan_number):
        self.current_plan = str(plan_number).zfill(2)


def _empty_features(crs="EPSG:3857"):
    return {
        name: gpd.GeoDataFrame(
            columns=["geometry"],
            geometry="geometry",
            crs=crs,
        )
        for name in (
            "bc_line",
            "breakline",
            "refinement_region",
            "reference_line",
            "reference_point",
        )
    }


def _preflight(tmp_path: Path) -> Breakout2DPreflight:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_plan = tmp_path / "Model.p01"
    source_geom = tmp_path / "Model.g01"
    source_hdf = tmp_path / "Model.g01.hdf"
    source_unsteady = tmp_path / "Model.u01"
    for path in (source_plan, source_geom, source_hdf):
        path.write_bytes(b"fixture")
    source_unsteady.write_bytes(b"Flow Title=Source\r\nBoundary Location=Area,Line\r\n")
    child = Polygon([(1, 1), (9, 1), (9, 9), (1, 9)])
    frame = gpd.GeoDataFrame(geometry=[child], crs="EPSG:3857")
    return Breakout2DPreflight(
        spec=Breakout2DSpec(
            source_plan="01",
            source_2d_area="Area",
            child_boundary=frame,
            breakout_id="test",
        ),
        source_plan_path=source_plan,
        source_plan_hdf=None,
        source_geometry_number="01",
        source_geometry_path=source_geom,
        source_geometry_hdf=source_hdf,
        source_unsteady_number="01",
        source_unsteady_path=source_unsteady,
        base_cell_size=1.0,
        parent_boundary=gpd.GeoDataFrame(
            {"mesh_name": ["Area"], "geometry": [child.buffer(1)]},
            geometry="geometry",
            crs=frame.crs,
        ),
        child_boundary=frame,
        boundary_segments=gpd.GeoDataFrame(
            {"segment_type": ["artificial_cut"], "length": [child.length]},
            geometry=[child.boundary],
            crs=frame.crs,
        ),
        feature_actions=gpd.GeoDataFrame(
            [
                {
                    "feature_type": "mesh_area",
                    "feature_id": "0",
                    "name": "Area",
                    "action": "replace",
                    "reason": "test",
                    "source_measure": 100.0,
                    "retained_measure": 64.0,
                    "retained_fraction": 0.64,
                    "geometry": child,
                }
            ],
            geometry="geometry",
            crs=frame.crs,
        ),
        existing_boundaries=pd.DataFrame(),
        checks=pd.DataFrame(
            [{"check_id": "ready", "passed": True, "blocking": True, "message": "ok"}]
        ),
        source_features=_empty_features(),
    )


def test_boundary_partition_identifies_inherited_and_cut_segments():
    parent = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    child = Polygon([(0, 2), (6, 2), (6, 8), (0, 8)])

    result = RasBreakout2D.classify_boundary_segments(
        parent,
        child,
        crs="EPSG:3857",
    )

    assert set(result["segment_type"]) == {"inherited", "artificial_cut"}
    assert result["length"].sum() == pytest.approx(child.length)


def test_preflight_preserves_boundary_scope_and_trims_mesh_features(
    tmp_path,
    monkeypatch,
):
    plan_path = tmp_path / "Model.p01"
    geom_path = tmp_path / "Model.g01"
    geom_hdf = tmp_path / "Model.g01.hdf"
    unsteady_path = tmp_path / "Model.u01"
    for path in (plan_path, geom_path, geom_hdf, unsteady_path):
        path.write_text("fixture", encoding="utf-8")
    plan_df = pd.DataFrame(
        [
            {
                "plan_number": "01",
                "geometry_number": "01",
                "unsteady_number": "01",
                "full_path": str(plan_path),
                "HDF_Results_Path": None,
                "geometry_type": "2D",
                "plan_type": "unsteady_2d",
                "plan_classification_valid": True,
            }
        ]
    )
    geom_df = pd.DataFrame(
        [
            {
                "geom_number": "01",
                "full_path": str(geom_path),
                "hdf_path": str(geom_hdf),
                **{column: 0 for column in breakout_module._UNSUPPORTED_STRUCTURE_COLUMNS},
            }
        ]
    )
    boundaries = pd.DataFrame(
        [
            {
                "unsteady_number": "01",
                "boundary_condition_number": 1,
                "bc_line_name": "Parent BC",
                "bc_type": "Normal Depth",
            }
        ]
    )
    ras = _FakeRas(plan_df, geom_df, boundaries)
    parent = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
    child = Polygon([(2, 2), (18, 2), (18, 18), (2, 18)])
    features = _empty_features()
    features["bc_line"] = gpd.GeoDataFrame(
        {"bc_line_id": [0], "Name": ["Parent BC"]},
        geometry=[LineString([(0, 0), (0, 20)])],
        crs="EPSG:3857",
    )
    features["breakline"] = gpd.GeoDataFrame(
        {
            "bl_id": [0],
            "Name": ["Crossing"],
            "cell_spacing_near": [2.0],
            "cell_spacing_far": [4.0],
            "near_repeats": [1],
            "protection_radius": [0],
        },
        geometry=[LineString([(0, 10), (20, 10)])],
        crs="EPSG:3857",
    )
    monkeypatch.setattr(
        breakout_module.RasPlan,
        "get_unsteady_path",
        staticmethod(lambda *_args, **_kwargs: unsteady_path),
    )
    monkeypatch.setattr(
        breakout_module.HdfMesh,
        "get_mesh_areas",
        staticmethod(
            lambda *_args, **_kwargs: gpd.GeoDataFrame(
                {"mesh_name": ["Area"]},
                geometry=[parent],
                crs="EPSG:3857",
            )
        ),
    )
    monkeypatch.setattr(breakout_module, "_read_spatial_features", lambda *_: features)
    monkeypatch.setattr(breakout_module, "_base_cell_size", lambda *_: 1.0)

    result = RasBreakout2D.preflight(
        Breakout2DSpec(
            "01",
            "Area",
            child,
            "contained",
            child_boundary_crs="EPSG:3857",
        ),
        ras_object=ras,
    )

    bc_actions = result.feature_actions[
        result.feature_actions["feature_type"].isin(
            ["bc_line", "unsteady_boundary"]
        )
    ]
    assert set(bc_actions["action"]) == {"preserve"}
    breakline = result.feature_actions[
        result.feature_actions["feature_type"] == "breakline"
    ].iloc[0]
    assert breakline["action"] == "clip"
    assert breakline.geometry.bounds == pytest.approx((3.0, 10.0, 17.0, 10.0))
    assert result.is_ready


def test_clone_plan_components_keeps_unsteady_file_byte_identical(
    tmp_path,
    monkeypatch,
):
    preflight = _preflight(tmp_path / "source")
    working = tmp_path / "working"
    working.mkdir()
    for source_path in (
        preflight.source_plan_path,
        preflight.source_geometry_path,
        preflight.source_geometry_hdf,
        preflight.source_unsteady_path,
    ):
        (working / source_path.name).write_bytes(source_path.read_bytes())
    clone_unsteady = working / "Model.u02"
    clone_geometry = working / "Model.g02"
    clone_geometry.write_bytes(b"cloned geometry")
    clone_geometry.with_suffix(".g02.hdf").write_bytes(b"cloned hdf")
    plan_path = working / "Model.p02"
    plan_path.write_bytes(b"plan")
    ras = _FakeRas(
        plan_df=pd.DataFrame(
            [
                {
                    "plan_number": "02",
                    "geometry_number": "02",
                    "unsteady_number": "02",
                    "full_path": str(plan_path),
                }
            ]
        ),
        project_folder=working,
    )

    monkeypatch.setattr(
        breakout_module.RasGeo,
        "clone_geom",
        staticmethod(lambda *_args, **_kwargs: "02"),
    )
    registered = []
    monkeypatch.setattr(
        breakout_module.RasMap,
        "clone_geometry_layer",
        staticmethod(
            lambda source, target, **_kwargs: registered.append((source, target))
        ),
    )

    def clone_unsteady_file(*_args, **_kwargs):
        clone_unsteady.write_bytes(preflight.source_unsteady_path.read_bytes())
        return "02"

    monkeypatch.setattr(
        breakout_module.RasPlan,
        "clone_unsteady",
        staticmethod(clone_unsteady_file),
    )
    monkeypatch.setattr(
        breakout_module.RasPlan,
        "clone_plan",
        staticmethod(lambda *_args, **_kwargs: "02"),
    )
    monkeypatch.setattr(
        breakout_module.RasPlan,
        "get_unsteady_path",
        staticmethod(lambda *_args, **_kwargs: clone_unsteady),
    )
    monkeypatch.setattr(
        breakout_module.RasPlan,
        "get_geom_path",
        staticmethod(lambda *_args, **_kwargs: clone_geometry),
    )

    result = RasBreakout2D.clone_plan_components(
        preflight,
        ras_object=ras,
        plan_title="Contained breakout",
        geometry_title="Contained geometry",
    )

    assert result.boundaries_unchanged
    assert result.plan_number == "02"
    assert result.geometry_number == "02"
    assert result.unsteady_number == "02"
    assert registered == [("01", "02")]
    assert ras.current_plan == "02"


def test_clone_rejects_in_place_source_project(tmp_path):
    preflight = _preflight(tmp_path / "source")
    ras = _FakeRas(project_folder=preflight.source_plan_path.parent)

    with pytest.raises(ValueError, match="isolated working project copy"):
        RasBreakout2D.clone_plan_components(preflight, ras_object=ras)


def test_clone_rejects_working_source_drift(tmp_path):
    preflight = _preflight(tmp_path / "source")
    working = tmp_path / "working"
    working.mkdir()
    for source_path in (
        preflight.source_plan_path,
        preflight.source_geometry_path,
        preflight.source_geometry_hdf,
        preflight.source_unsteady_path,
    ):
        (working / source_path.name).write_bytes(source_path.read_bytes())
    (working / "Model.g01").write_bytes(b"divergent geometry")
    ras = _FakeRas(project_folder=working)

    with pytest.raises(ValueError, match="geometry source does not match"):
        RasBreakout2D.clone_plan_components(preflight, ras_object=ras)


def test_flux_zone_combination_keeps_direction_separate():
    faces = gpd.GeoDataFrame(
        {
            "face_id": [1, 2, 3],
            "face_length": [1.0, 1.0, 1.0],
            "boundary_station": [0.0, 1.0, 2.0],
            "orientation_multiplier": [1.0, 1.0, 1.0],
            "normal_x": [1.0, 1.0, 1.0],
            "normal_y": [0.0, 0.0, 0.0],
            "significant": [True, True, True],
            "dominant_direction": ["outflow", "outflow", "inflow"],
            "absolute_volume": [10.0, 10.0, 10.0],
        },
        geometry=[
            LineString([(0, 0), (0, 1)]),
            LineString([(0, 1), (0, 2)]),
            LineString([(0, 2), (0, 3)]),
        ],
        crs="EPSG:3857",
    )
    flow = pd.DataFrame(
        {1: [0.0, 3.0], 2: [0.0, 2.0], 3: [0.0, -4.0]},
        index=pd.to_timedelta([0, 1], unit="h"),
    )

    zones = breakout_module._combine_flux_locations(
        faces,
        flow,
        gap_multiplier=3.0,
    )

    assert zones["dominant_direction"].tolist() == ["outflow", "inflow"]
    assert zones["face_count"].tolist() == [2, 1]
    assert zones["peak_abs_flow"].tolist() == pytest.approx([5.0, 4.0])


def test_breakout_public_dataframes_have_declared_schemas():
    expected = {
        "ras_breakout_2d_boundaries",
        "ras_breakout_2d_boundary_segments",
        "ras_breakout_2d_feature_actions",
        "ras_breakout_2d_checks",
        "ras_breakout_2d_boundary_faces",
        "ras_breakout_2d_flux_zones",
        "ras_breakout_2d_face_flow",
    }

    assert expected <= set(DATAFRAME_SCHEMAS)
    feature_columns = [
        item["name"]
        for item in DATAFRAME_SCHEMAS["ras_breakout_2d_feature_actions"][
            "columns"
        ]
    ]
    assert feature_columns == breakout_module.FEATURE_ACTION_COLUMNS
